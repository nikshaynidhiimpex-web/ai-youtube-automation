import os, json, re, subprocess, textwrap, random, time
from datetime import datetime, timezone
from pathlib import Path
from google import genai
from google.genai import types
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

OUT = Path("output")
OUT.mkdir(exist_ok=True)
API_KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
client = genai.Client(api_key=API_KEY)



# ============================================================
# DYNAMIC GEMINI MODEL CONFIGURATION
# ============================================================

MODEL_CANDIDATES = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]

MODEL_TIMEOUT_SECONDS = 35
TOTAL_GENERATION_BUDGET = 480
MAX_MODEL_CYCLES = 2
CYCLE_PAUSE_SECONDS = 10

# SDK automatic retries disabled.
# Our own model rotation handles retries and switching.
client = genai.Client(
    api_key=API_KEY,
    http_options=types.HttpOptions(
        timeout=MODEL_TIMEOUT_SECONDS * 1000,
        retry_options=types.HttpRetryOptions(
            attempts=1
        ),
    ),
)


def get_gemini_error_status(error):
    status = (
        getattr(error, "code", None)
        or getattr(error, "status_code", None)
    )

    if status is not None:
        try:
            return int(status)
        except (ValueError, TypeError):
            pass

    match = re.search(
        r"\b(400|401|403|404|408|429|500|502|503|504)\b",
        str(error)
    )

    return int(match.group(1)) if match else None


def is_gemini_network_error(error):
    network_errors = {
        "RemoteProtocolError",
        "ConnectError",
        "ReadError",
        "WriteError",
        "TimeoutException",
        "ConnectTimeout",
        "ReadTimeout",
        "PoolTimeout",
    }

    return (
        type(error).__name__ in network_errors
        or "server disconnected without sending a response"
        in str(error).lower()
        or "connection reset" in str(error).lower()
    )


def validate_generated_script(data):

    if not isinstance(data, dict):
        raise ValueError("Invalid JSON object")

    required = [
        "title",
        "description",
        "narration",
        "visuals"
    ]

    if any(key not in data for key in required):
        raise ValueError("Missing required script fields")

    if not isinstance(data["visuals"], list):
        raise ValueError("Visuals must be a list")

    if len(data["visuals"]) < 3:
        raise ValueError("At least 3 visuals are required")

    for visual in data["visuals"][:3]:
        if not isinstance(visual, dict):
            raise ValueError("Invalid visual entry")

        if not visual.get("query") or not visual.get("caption"):
            raise ValueError("Visual query/caption missing")

    return data


def generate_script():

    prompt = """
Write one original Hindi YouTube Short script (Devanagari Hindi), 35-45 seconds.

Topic: an interesting, verifiable science/history/technology fact suitable for a
general Indian audience. Avoid medical, financial, political, sensational or
dangerous claims. Do not invent statistics, dates, quotes or sources.

Use this exact JSON schema and output JSON only:
{
 "title":"Hindi title, under 65 characters",
 "description":"2-3 Hindi sentences plus relevant hashtags",
 "narration":"Natural spoken Hindi, 85-105 words",
 "visuals":[
   {"query":"English visual search phrase","caption":"short Hindi on-screen caption"},
   {"query":"English visual search phrase","caption":"short Hindi on-screen caption"},
   {"query":"English visual search phrase","caption":"short Hindi on-screen caption"}
 ]
}

Choose a topic that can be explained accurately without needing current news.
Make the opening 2 seconds a strong curiosity hook and end with a question.
"""

    start_time = time.monotonic()
    deadline = start_time + TOTAL_GENERATION_BUDGET

    last_error = None

    print("=" * 55)
    print("DYNAMIC GEMINI MODEL ROTATION STARTED")
    print("Available models:", len(MODEL_CANDIDATES))
    print("Maximum cycles:", MAX_MODEL_CYCLES)
    print("Per model timeout:", MODEL_TIMEOUT_SECONDS, "seconds")
    print("Total time budget:", TOTAL_GENERATION_BUDGET, "seconds")
    print("=" * 55)

    for cycle in range(1, MAX_MODEL_CYCLES + 1):

        print(f"\nSTARTING MODEL CYCLE {cycle}/{MAX_MODEL_CYCLES}")

        for index, model_name in enumerate(
            MODEL_CANDIDATES, start=1
        ):

            remaining = deadline - time.monotonic()

            # Never start a request that cannot fit inside the budget.
            if remaining < MODEL_TIMEOUT_SECONDS:
                print("TIME BUDGET LOW. STOPPING MODEL ROTATION.")
                break

            print("\n-----------------------------------")
            print(f"MODEL {index}/{len(MODEL_CANDIDATES)}")
            print("CURRENT MODEL:", model_name)
            print("-----------------------------------")

            try:

                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.7,
                    )
                )

                if not response.text:
                    raise ValueError("Empty Gemini response")

                data = json.loads(response.text)
                data = validate_generated_script(data)

                elapsed = time.monotonic() - start_time

                print("\n===================================")
                print("SCRIPT_GENERATION_SUCCESS")
                print("SUCCESSFUL MODEL:", model_name)
                print(f"TOTAL TIME: {elapsed:.1f} seconds")
                print("===================================")

                return data

            except Exception as error:

                last_error = error

                status = get_gemini_error_status(error)
                network_error = is_gemini_network_error(error)

                print("MODEL FAILED:", model_name)
                print("ERROR:", type(error).__name__)
                print("STATUS:", status)
                print("DETAILS:", str(error)[:1000])

                # Invalid API credentials affect every model.
                if status in (401, 403):
                    raise RuntimeError(
                        "Gemini authentication failed. "
                        "Check GEMINI_API_KEY."
                    ) from error

                # A malformed request will generally fail on every model.
                if status == 400:
                    raise RuntimeError(
                        "Gemini rejected the request. "
                        "Check prompt/configuration."
                    ) from error

                # Temporary errors or model-specific availability errors:
                # immediately skip this model.
                switch_to_next = (
                    status in (
                        404, 408, 429,
                        500, 502, 503, 504
                    )
                    or network_error
                    or isinstance(error, ValueError)
                    or isinstance(error, json.JSONDecodeError)
                )

                if switch_to_next:

                    print(
                        f"SKIPPING {model_name}. "
                        "SWITCHING TO NEXT MODEL..."
                    )

                    continue

                raise

        # All models have been attempted once.
        if cycle < MAX_MODEL_CYCLES:

            remaining = deadline - time.monotonic()

            if remaining <= CYCLE_PAUSE_SECONDS + MODEL_TIMEOUT_SECONDS:
                break

            print("\nALL MODELS FAILED IN THIS CYCLE.")
            print(
                f"Waiting {CYCLE_PAUSE_SECONDS} seconds "
                "before restarting model rotation."
            )

            time.sleep(CYCLE_PAUSE_SECONDS)

    elapsed = time.monotonic() - start_time

    raise RuntimeError(
        "ALL GEMINI MODELS FAILED. "
        f"Cycles: {MAX_MODEL_CYCLES}. "
        f"Elapsed: {elapsed:.1f} seconds. "
        f"Last error: {last_error}"
    ) from last_error

def make_voice(text):
    # espeak-ng is a free, offline Hindi TTS fallback. Quality varies by runner voice.
    wav = OUT / "voice.wav"
    subprocess.run(["espeak-ng", "-v", "hi", "-s", "145", "-w", str(wav), text],
                   check=True)
    return wav

def make_thumbnail(title):
    img = Image.new("RGB", (1080, 1920), (12, 20, 38))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf", 76)
    except Exception:
        font = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf", 54)
    lines = textwrap.wrap(title, width=17)[:4]
    y = 620
    for line in lines:
        d.text((70, y), line, font=font, fill="white", stroke_width=2, stroke_fill="black")
        y += 105
    d.text((70, 1500), "जानिए कुछ नया!", font=font, fill=(255, 210, 70))
    path = OUT / "thumbnail.jpg"
    img.save(path, quality=90)
    return path

def render_video(script, wav):
    # Simple original motion-card video. This starter intentionally avoids
    # downloading copyrighted clips or scraping YouTube videos.
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(wav)
    ]).decode().strip())
    duration = max(20, min(duration + 1.5, 58))
    title = script["title"].replace("'", "").replace(":", " ")
    safe_title = title.replace("\\", " ").replace("%", " ")
    # Render a subtle animated gradient background with readable title and captions.
    vf = (
      "scale=1080:1920,format=yuv420p,"
      "drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf:"
      f"text='{safe_title[:65]}':fontcolor=white:fontsize=66:"
      "x=(w-text_w)/2:y=500:box=1:boxcolor=black@0.35:boxborderw=30,"
      "drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf:"
      "text='पूरी कहानी सुनिए':fontcolor=yellow:fontsize=46:"
      "x=(w-text_w)/2:y=1250"
    )
    video = OUT / "short.mp4"
    subprocess.run([
      "ffmpeg", "-y", "-f", "lavfi", "-i",
      "color=c=#101d36:s=1080x1920:r=30:d=" + str(duration),
      "-i", str(wav), "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
      "-t", str(duration), "-c:a", "aac", "-b:a", "128k",
      "-shortest", "-movflags", "+faststart", str(video)
    ], check=True)
    return video


def youtube_service():
    raw = os.environ["YOUTUBE_TOKEN_JSON"]
    info = json.loads(raw)

    youtube_scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]

    creds = Credentials.from_authorized_user_info(
        info, scopes=youtube_scopes
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    youtube = build("youtube", "v3", credentials=creds)

    # Verify channel identity before uploading
    channels = youtube.channels().list(
        part="snippet", mine=True
    ).execute().get("items", [])

    if not channels:
        raise RuntimeError("No YouTube channel found.")

    actual_channel = channels[0]["snippet"]["title"]
    expected_channel = os.getenv(
        "YOUTUBE_EXPECTED_CHANNEL_NAME", "Sayar Hu Sayad"
    ).strip()

    print("AUTHORIZED_YOUTUBE_CHANNEL:", actual_channel)

    if actual_channel != expected_channel:
        raise RuntimeError(
            f"Channel mismatch: expected '{expected_channel}', "
            f"but OAuth authorized '{actual_channel}'. Upload stopped."
        )

    print("CHANNEL_VERIFICATION: PASSED")

    return youtube


def upload(video, script, thumb):
    youtube = youtube_service()
    privacy = os.getenv("YOUTUBE_PRIVACY_STATUS", "private")
    body = {
      "snippet": {
        "title": script["title"][:100],
        "description": script["description"][:5000],
        "categoryId": "27",
        "defaultLanguage": "hi",
        "tags": ["Hindi facts", "ज्ञान", "shorts"]
      },
      "status": {
        "privacyStatus": privacy,
      }
    }
    request = youtube.videos().insert(
      part="snippet,status", body=body,
      media_body=MediaFileUpload(str(video), mimetype="video/mp4",
                                 resumable=True)
    )
    response = request.execute()
    video_id = response["id"]
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")
        ).execute()
    except Exception as e:
        print("Thumbnail upload skipped:", e)
    print("UPLOAD_SUCCESS video_id=", video_id, "privacy=", privacy)

def main():
    script = generate_script()
    (OUT / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    wav = make_voice(script["narration"])
    thumb = make_thumbnail(script["title"])
    video = render_video(script, wav)
    upload(video, script, thumb)

if __name__ == "__main__":
    main()
