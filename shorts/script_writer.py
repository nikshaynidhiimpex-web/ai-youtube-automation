"""Gemini script generation with model rotation and performance-aware prompt."""
import json
import os
import re
import time

from google import genai
from google.genai import types

from .common import env

# ============================================================
# DYNAMIC GEMINI MODEL CONFIGURATION
# ============================================================
# GEMINI_MODEL (GitHub variable) is tried first if set.
DEFAULT_MODELS = [
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


def model_candidates():
    preferred = env("GEMINI_MODEL")
    if not preferred:
        return list(DEFAULT_MODELS)
    return [preferred] + [m for m in DEFAULT_MODELS if m != preferred]


def make_client():
    # SDK automatic retries disabled; our own model rotation handles retries.
    return genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(
            timeout=MODEL_TIMEOUT_SECONDS * 1000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def get_gemini_error_status(error):
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    if status is not None:
        try:
            return int(status)
        except (ValueError, TypeError):
            pass
    match = re.search(r"\b(400|401|403|404|408|429|500|502|503|504)\b", str(error))
    return int(match.group(1)) if match else None


def is_gemini_network_error(error):
    network_errors = {
        "RemoteProtocolError", "ConnectError", "ReadError", "WriteError",
        "TimeoutException", "ConnectTimeout", "ReadTimeout", "PoolTimeout",
    }
    text = str(error).lower()
    return (
        type(error).__name__ in network_errors
        or "server disconnected without sending a response" in text
        or "connection reset" in text
    )


def validate_generated_script(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid JSON object")
    for key in ("title", "description", "scenes"):
        if key not in data:
            raise ValueError(f"Missing required field: {key}")

    scenes = data["scenes"]
    if not isinstance(scenes, list) or not 4 <= len(scenes) <= 9:
        raise ValueError("Need 4-9 scenes")
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError("Invalid scene entry")
        scene["narration"] = str(scene.get("narration", "")).strip()
        scene["query"] = str(scene.get("query", "")).strip()
        scene["caption"] = str(scene.get("caption", "")).strip()
        if not scene["narration"] or not scene["query"]:
            raise ValueError("Scene narration/query missing")

    words = sum(len(s["narration"].split()) for s in scenes)
    if not 60 <= words <= 160:
        raise ValueError(f"Narration length out of range: {words} words")
    data["narration"] = " ".join(s["narration"] for s in scenes)

    tags = data.get("tags") if isinstance(data.get("tags"), list) else []
    data["tags"] = [str(t).strip().lstrip("#") for t in tags if str(t).strip()][:15]
    data["title"] = str(data["title"]).strip()
    data["description"] = str(data["description"]).strip()
    if "#shorts" not in data["description"].lower():
        data["description"] += "\n\n#shorts"
    data["thumbnail_text"] = str(data.get("thumbnail_text") or data["title"]).strip()
    for field in ("topic", "category", "hook_style"):
        data[field] = str(data.get(field) or "unknown").strip().lower()
    return data


def build_prompt(insights, recent_titles, explore):
    avoid = "\n".join(f"- {t}" for t in recent_titles) or "- (none yet)"
    explore_line = (
        "EXPERIMENT TODAY: pick a category or hook style that has NOT been used "
        "much yet, so we learn what else the audience likes."
        if explore else
        "Use the performance data above: lean toward the categories, hook styles "
        "and title styles of the best videos (without copying them)."
    )
    return f"""
You are the head writer of a Hindi YouTube Shorts channel that explains
fascinating, verifiable facts (science, space, history, technology, nature,
human body, geography, inventions, animals).

Write ONE original Short, 35-50 seconds when spoken.

RULES
- Natural spoken Hindi in Devanagari. Common English words (science, planet)
  are fine, written in Devanagari.
- Accurate, verifiable facts only. No medical, financial, political,
  sensational or dangerous claims. Do not invent numbers, dates, quotes or
  sources. If you are not sure about a number, do not use it.
- Scene 1 is the HOOK: max 12 words, creates strong curiosity in the first
  2 seconds. No greetings (no "नमस्ते दोस्तों").
- Each scene narration: 1-2 short sentences (8-22 words).
- Last scene: punchy payoff + a question that invites comments.
- 5-7 scenes, total narration 85-120 words.
- caption: 2-5 Hindi words shown on screen, the key idea of the scene
  (do not copy the narration).
- query: 2-4 simple English words for stock-footage search, concrete and
  visual (e.g. "night sky stars", "ancient pyramid desert"). No real
  people's names, no brands.
- title: under 60 characters, Hindi, curiosity-driven, honest (no false
  clickbait).
- description: 2-3 Hindi sentences + 4-6 hashtags including #shorts.
- tags: 6-10 tags, mix of Hindi and English.
- thumbnail_text: 2-4 Hindi words.

RECENT VIDEOS — do NOT repeat these topics:
{avoid}

{insights}

{explore_line}

Output JSON only, exactly this schema:
{{
 "topic": "short English topic label",
 "category": "one word, e.g. space / history / science / technology / nature / body / animals",
 "hook_style": "one of: question / shocking-fact / myth-buster / story / comparison",
 "title": "...",
 "description": "...",
 "tags": ["..."],
 "thumbnail_text": "...",
 "scenes": [
   {{"narration": "Hindi sentence(s)", "caption": "short Hindi on-screen text", "query": "english stock search"}}
 ]
}}
"""


def generate_script(insights="", recent_titles=(), explore=False):
    client = make_client()
    prompt = build_prompt(insights, recent_titles, explore)
    models = model_candidates()

    start_time = time.monotonic()
    deadline = start_time + TOTAL_GENERATION_BUDGET
    last_error = None

    print("=" * 55)
    print("DYNAMIC GEMINI MODEL ROTATION STARTED")
    print("Models:", ", ".join(models))
    print("=" * 55)

    for cycle in range(1, MAX_MODEL_CYCLES + 1):
        print(f"\nSTARTING MODEL CYCLE {cycle}/{MAX_MODEL_CYCLES}")
        for index, model_name in enumerate(models, start=1):
            if deadline - time.monotonic() < MODEL_TIMEOUT_SECONDS:
                print("TIME BUDGET LOW. STOPPING MODEL ROTATION.")
                break
            print(f"\nMODEL {index}/{len(models)}: {model_name}")
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.9,
                    ),
                )
                if not response.text:
                    raise ValueError("Empty Gemini response")
                data = validate_generated_script(json.loads(response.text))
                data["model"] = model_name
                print(f"SCRIPT_GENERATION_SUCCESS model={model_name} "
                      f"time={time.monotonic() - start_time:.1f}s")
                return data
            except Exception as error:
                last_error = error
                status = get_gemini_error_status(error)
                print("MODEL FAILED:", model_name, type(error).__name__,
                      "status=", status, str(error)[:500])
                if status in (401, 403):
                    raise RuntimeError(
                        "Gemini authentication failed. Check GEMINI_API_KEY."
                    ) from error
                if status == 400:
                    raise RuntimeError(
                        "Gemini rejected the request. Check prompt/configuration."
                    ) from error
                if (status in (404, 408, 429, 500, 502, 503, 504)
                        or is_gemini_network_error(error)
                        or isinstance(error, ValueError)):
                    continue
                raise

        if cycle < MAX_MODEL_CYCLES:
            if deadline - time.monotonic() <= CYCLE_PAUSE_SECONDS + MODEL_TIMEOUT_SECONDS:
                break
            print(f"\nALL MODELS FAILED IN THIS CYCLE. Waiting {CYCLE_PAUSE_SECONDS}s.")
            time.sleep(CYCLE_PAUSE_SECONDS)

    raise RuntimeError(
        f"ALL GEMINI MODELS FAILED after {time.monotonic() - start_time:.1f}s. "
        f"Last error: {last_error}"
    ) from last_error
