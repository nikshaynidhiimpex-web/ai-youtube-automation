"""Daily Hindi YouTube Short: analyse -> write -> voice -> visuals -> render -> upload.

Environment:
  GEMINI_API_KEY, YOUTUBE_TOKEN_JSON, YOUTUBE_EXPECTED_CHANNEL_NAME  (required)
  PEXELS_API_KEY        free stock videos/photos (optional, strongly recommended)
  PUBLISH_MODE          public (scheduled at best time) | private | unlisted
  FORCE_RUN=1           make a video even if today's public video exists
  DRY_RUN=1             only render the video, no YouTube calls
  SCRIPT_FILE=path      use an existing script JSON instead of Gemini (testing)
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from shorts import analytics, render, script_writer, visuals, voice, youtube
from shorts.common import IST, env

OUT = Path("output")


def main():
    OUT.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    mode = env("PUBLISH_MODE", "private").lower()
    dry_run = env("DRY_RUN") == "1"
    print(f"RUN at {now.astimezone(IST):%Y-%m-%d %H:%M} IST | mode={mode} | dry_run={dry_run}")

    history = analytics.load()
    if mode == "public" and not dry_run and env("FORCE_RUN") != "1" \
            and analytics.already_published_today(history, now):
        print("Today's public video already exists. Nothing to do.")
        return

    # 1. Learn from past videos
    yt = yta = None
    if not dry_run:
        yt, yta = youtube.connect()
        try:
            analytics.refresh(history, yt, yta, now)
            analytics.save(history)
        except Exception as error:
            print("ANALYTICS REFRESH FAILED (continuing):", str(error)[:500])
    insights = analytics.build_insights(history)
    explore = analytics.should_explore(history)
    print("\n" + insights + f"\nEXPLORE={explore}\n")

    # 2. Script
    if env("SCRIPT_FILE"):
        script = script_writer.validate_generated_script(
            json.loads(Path(env("SCRIPT_FILE")).read_text(encoding="utf-8")))
    else:
        script = script_writer.generate_script(
            insights, analytics.recent_titles(history), explore)
    (OUT / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    print("TITLE:", script["title"])

    # 3. Voice, visuals, render
    audios = voice.synthesize_scenes(script["scenes"], OUT)
    media = visuals.fetch_scene_media(script["scenes"], OUT)
    video, duration = render.render_short(script, audios, media, OUT)
    thumb = render.make_thumbnail(script, OUT)
    print(f"RENDERED {video} ({duration:.1f}s)")

    if dry_run:
        print("DRY_RUN: skipping upload.")
        return

    # 4. Pick publish time and upload
    publish_at = None
    if mode == "public":
        publish_at, reason = analytics.choose_publish_time(history, now)
        print("PUBLISH_TIME:", f"{publish_at:%Y-%m-%d %H:%M} IST" if publish_at else "now",
              "|", reason)
    sources = sorted({m["source"] for m in media if m.get("source")})
    credits = f"Visuals: {', '.join(sources)}" if sources else ""
    attributions = [m["attribution"] for m in media if m.get("attribution")]
    if attributions:
        credits += "\nImage credits:\n" + "\n".join(f"- {a}" for a in attributions)
    video_id = youtube.upload(yt, video, thumb, script, mode, publish_at, credits)

    published = publish_at or now.astimezone(IST)
    analytics.record_upload(history, {
        "video_id": video_id,
        "created_at": now.astimezone(IST).isoformat(timespec="minutes"),
        "publish_at": published.isoformat(timespec="minutes"),
        "slot_hour_ist": published.hour,
        "mode": mode,
        "title": script["title"],
        "topic": script["topic"],
        "category": script["category"],
        "hook_style": script["hook_style"],
        "model": script.get("model"),
        "voice": audios[0]["engine"],
        "duration": round(duration, 1),
        "scenes": len(script["scenes"]),
        "media": [m["type"] for m in media],
    })
    analytics.save(history)


if __name__ == "__main__":
    main()
