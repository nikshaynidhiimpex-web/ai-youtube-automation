"""Channel memory: what was uploaded when, how it performed, and what to do next.

Stored in data/history.json (committed back to the repo by the workflow).
"""
import json
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from . import youtube
from .common import IST, env

HISTORY_FILE = Path("data/history.json")
TRACK_DAYS = 45


def load():
    if HISTORY_FILE.exists():
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    return {"videos": []}


def save(history):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2),
                            encoding="utf-8")


def _public(history):
    return [v for v in history["videos"] if v.get("mode") == "public" and v.get("video_id")]


def already_published_today(history, now):
    today = now.astimezone(IST).date().isoformat()
    return any(v.get("created_at", "")[:10] == today for v in _public(history))


def recent_titles(history, n=30):
    return [v["title"] for v in history["videos"][-n:] if v.get("title")]


# ------------------------------------------------------------------ stats
def _update_views_24h(video):
    """Interpolate views at exactly 24h after publish from snapshots."""
    if video.get("views_24h") is not None:
        return
    snaps = sorted(video.get("snapshots", []), key=lambda s: s["hours"])
    prev = {"hours": 0.0, "views": 0}
    for snap in snaps:
        if snap["hours"] >= 24:
            span = snap["hours"] - prev["hours"]
            if span <= 0:
                return
            frac = (24 - prev["hours"]) / span
            video["views_24h"] = int(round(prev["views"] + frac * (snap["views"] - prev["views"])))
            video["views_24h_estimated"] = snap["hours"] > 36
            return
        prev = snap


def score(video):
    """Higher = audience liked it more. Mainly 24h views, boosted by
    engagement (likes/comments/shares per view) and retention."""
    v24 = video.get("views_24h")
    if v24 is None:
        return None
    stats = video.get("stats", {})
    an = video.get("analytics", {})
    views = max(stats.get("views", 0), 1)
    engagement = (stats.get("likes", 0) + 2 * stats.get("comments", 0)
                  + 3 * an.get("shares", 0)) / views
    s = math.log1p(v24) * (1 + min(engagement, 0.3) * 3)
    retention = an.get("averageViewPercentage")
    if retention:
        s *= 0.5 + min(retention, 150) / 100  # Shorts loops can exceed 100%
    return round(s, 3)


def refresh(history, yt, yta, now):
    tracked = []
    for v in _public(history):
        published = datetime.fromisoformat(v["publish_at"])
        if (now - published).days <= TRACK_DAYS:
            tracked.append((v, published))
    if not tracked:
        print("ANALYTICS: no published videos to track yet.")
        return

    stats = youtube.fetch_video_stats(yt, [v["video_id"] for v, _ in tracked])
    for v, published in tracked:
        s = stats.get(v["video_id"])
        hours = (now - published).total_seconds() / 3600
        if s is None:
            v["missing"] = True
            continue
        if hours < 0:
            continue  # scheduled, not public yet
        v["stats"] = s
        v.setdefault("snapshots", []).append(
            {"at": now.isoformat(timespec="minutes"), "hours": round(hours, 1), **s})
        v["snapshots"] = v["snapshots"][-20:]
        _update_views_24h(v)

    try:
        start = min(p for _, p in tracked).astimezone(IST).date().isoformat()
        data = youtube.fetch_analytics(
            yta, [v["video_id"] for v, _ in tracked], start,
            now.astimezone(IST).date().isoformat())
        for v, _ in tracked:
            if v["video_id"] in data:
                v["analytics"] = data[v["video_id"]]
    except Exception as error:
        print("ANALYTICS API skipped:", str(error)[:300])

    for v, _ in tracked:
        v["score"] = score(v)
    print(f"ANALYTICS: refreshed {len(tracked)} videos.")


# --------------------------------------------------------------- insights
def _line(v):
    an = v.get("analytics", {})
    st = v.get("stats", {})
    parts = [
        f'"{v["title"]}"', f"category={v.get('category')}", f"hook={v.get('hook_style')}",
        f"published={v.get('slot_hour_ist')}:00 IST", f"views_24h={v.get('views_24h')}",
        f"likes={st.get('likes', 0)}", f"comments={st.get('comments', 0)}",
    ]
    if an.get("averageViewPercentage") is not None:
        parts.append(f"retention={an['averageViewPercentage']:.0f}%")
    if an.get("shares") is not None:
        parts.append(f"shares={an['shares']}")
    if an.get("videoThumbnailImpressionsClickRate") is not None:
        parts.append(f"ctr={an['videoThumbnailImpressionsClickRate']:.1f}%")
    parts.append(f"score={v['score']}")
    return "- " + " | ".join(parts)


def _group(videos, key):
    groups = defaultdict(list)
    for v in videos:
        groups[v.get(key) or "unknown"].append(v["score"])
    rows = sorted(groups.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))
    return ", ".join(f"{k}: {sum(s) / len(s):.2f} (n={len(s)})" for k, s in rows)


def build_insights(history):
    scored = [v for v in _public(history) if v.get("score") is not None]
    if len(scored) < 3:
        return ("CHANNEL PERFORMANCE DATA: not enough data yet "
                f"({len(scored)} videos with 24h results). Try varied categories and "
                "hook styles so we can learn what this audience likes.")
    ranked = sorted(scored, key=lambda v: -v["score"])
    top, bottom = ranked[:3], ranked[-3:] if len(ranked) >= 6 else []
    text = ["CHANNEL PERFORMANCE DATA (real YouTube results, learn from it):",
            "Best videos:", *map(_line, top)]
    if bottom:
        text += ["Weak videos (avoid what made these weak):", *map(_line, bottom)]
    text += [f"Average score by category: {_group(scored, 'category')}",
             f"Average score by hook style: {_group(scored, 'hook_style')}"]
    return "\n".join(text)


def should_explore(history):
    scored = [v for v in _public(history) if v.get("score") is not None]
    return len(scored) < 5 or random.random() < 0.25


# --------------------------------------------------------------- schedule
def _slots():
    raw = env("PUBLISH_SLOTS_IST", "9,11,13,15,17,18,19,20,21")
    return sorted({int(x) for x in raw.split(",") if x.strip().isdigit() and 0 <= int(x) <= 23})


def choose_publish_time(history, now):
    """Pick today's publish time (IST). Tries every slot at least once, then
    mostly uses the best-performing hour, sometimes explores another one.
    Returns (datetime or None for 'publish now', reason)."""
    slots = _slots()
    by_slot = defaultdict(list)
    for v in _public(history):
        if v.get("score") is not None and v.get("slot_hour_ist") in slots:
            by_slot[v["slot_hour_ist"]].append(v["score"])
    untried = [s for s in slots if s not in by_slot]

    if untried and (not by_slot or random.random() < 0.6):
        hour, reason = random.choice(untried), "exploring a new time slot"
    elif by_slot and random.random() < 0.75:
        hour = max(by_slot, key=lambda s: sum(by_slot[s]) / len(by_slot[s]))
        reason = "best performing time slot so far"
    else:
        hour, reason = random.choice(slots), "random exploration"

    now_ist = now.astimezone(IST)
    earliest = now_ist + timedelta(minutes=40)  # time for upload + processing
    minute = random.randint(0, 45)  # vary the exact time every day
    pick = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if pick < earliest:
        later = [s for s in slots if now_ist.replace(hour=s, minute=0) >= earliest]
        if not later:
            return None, "all slots passed today, publishing immediately"
        pick = now_ist.replace(hour=later[0], minute=random.randint(0, 45),
                               second=0, microsecond=0)
        reason += " (chosen slot passed, moved to next one)"
    return pick, reason


def record_upload(history, entry):
    history["videos"].append(entry)
