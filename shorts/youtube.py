"""YouTube Data API (upload, stats) and YouTube Analytics API (retention, shares)."""
import json
import os
from datetime import timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .common import env

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"


def connect():
    info = json.loads(os.environ["YOUTUBE_TOKEN_JSON"])
    # Use the scopes the token was actually granted; asking for more on
    # refresh makes Google reject it with invalid_scope.
    creds = Credentials.from_authorized_user_info(info)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())

    if ANALYTICS_SCOPE not in (info.get("scopes") or []):
        print("WARNING: token has no yt-analytics.readonly scope. Retention/shares "
              "analytics will be skipped. Re-create the token with get_token.py.")

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    yta = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    channels = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    if not channels:
        raise RuntimeError("No YouTube channel found.")
    actual = channels[0]["snippet"]["title"]
    expected = env("YOUTUBE_EXPECTED_CHANNEL_NAME", "Sayar Hu Sayad")
    print("AUTHORIZED_YOUTUBE_CHANNEL:", actual)
    if actual != expected:
        raise RuntimeError(f"Channel mismatch: expected '{expected}', but OAuth "
                           f"authorized '{actual}'. Upload stopped.")
    print("CHANNEL_VERIFICATION: PASSED")
    return yt, yta


def _trim_tags(tags, limit=450):
    out, used = [], 0
    for tag in tags:
        cost = len(tag) + (2 if " " in tag else 0) + 1
        if used + cost > limit:
            break
        out.append(tag)
        used += cost
    return out


def upload(yt, video, thumb, script, privacy, publish_at=None, credits=""):
    description = script["description"]
    if credits:
        description += f"\n\n{credits}"
    status = {"selfDeclaredMadeForKids": False}
    if privacy == "public" and publish_at:
        # Uploaded as private, YouTube makes it public automatically at publishAt
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        status["privacyStatus"] = privacy

    body = {
        "snippet": {
            "title": script["title"][:100],
            "description": description[:5000],
            "categoryId": "27",
            "defaultLanguage": "hi",
            "defaultAudioLanguage": "hi",
            "tags": _trim_tags(script["tags"] + ["shorts", "Hindi facts"]),
        },
        "status": status,
    }
    response = yt.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True),
    ).execute()
    video_id = response["id"]
    try:
        yt.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg"),
        ).execute()
    except Exception as error:
        print("Thumbnail upload skipped:", str(error)[:300])
    print("UPLOAD_SUCCESS video_id=", video_id, "status=", status)
    return video_id


def fetch_video_stats(yt, ids):
    stats = {}
    for i in range(0, len(ids), 50):
        batch = ids[i:i + 50]
        items = yt.videos().list(part="statistics", id=",".join(batch)).execute().get("items", [])
        for item in items:
            s = item.get("statistics", {})
            stats[item["id"]] = {
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
            }
    return stats


def _query(yta, metrics, ids, start_date, end_date):
    res = yta.reports().query(
        ids="channel==MINE", startDate=start_date, endDate=end_date,
        metrics=metrics, dimensions="video", filters="video==" + ",".join(ids),
        maxResults=200, sort="-views",
    ).execute()
    headers = [h["name"] for h in res.get("columnHeaders", [])]
    return {row[0]: dict(zip(headers[1:], row[1:])) for row in res.get("rows", []) or []}


def fetch_analytics(yta, ids, start_date, end_date):
    """Lifetime analytics per video. Analytics data lags ~1-2 days."""
    if not ids:
        return {}
    ids = ids[:200]
    data = _query(yta, "views,estimatedMinutesWatched,averageViewDuration,"
                       "averageViewPercentage,likes,shares,comments,subscribersGained",
                  ids, start_date, end_date)
    # Optional metrics: not available for every channel/API version.
    for extra in ("engagedViews", "videoThumbnailImpressions,videoThumbnailImpressionsClickRate"):
        try:
            for vid, values in _query(yta, extra, ids, start_date, end_date).items():
                data.setdefault(vid, {}).update(values)
        except Exception as error:
            print(f"Analytics metric '{extra}' not available:", str(error)[:200])
    return data
