import os, json, re, subprocess, textwrap, random
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
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json")
    )
    data = json.loads(response.text)
    required = ["title", "description", "narration", "visuals"]
    if any(k not in data for k in required) or len(data["visuals"]) < 3:
        raise ValueError("Model response did not match the required schema")
    return data

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
    creds = Credentials.from_authorized_user_info(
        info, scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)

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
