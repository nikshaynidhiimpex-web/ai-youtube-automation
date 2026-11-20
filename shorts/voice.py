"""Hindi narration: Microsoft Edge neural voice (free), espeak-ng fallback.

Each scene is voiced separately so scene visuals and subtitles stay in sync.
Word timings come from edge-tts WordBoundary events.
"""
import asyncio
import subprocess

from .common import env, run_ffmpeg, wav_duration


async def _edge_tts(text, voice, rate, mp3_path):
    import edge_tts

    try:
        communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    except TypeError:  # older edge-tts versions emit WordBoundary by default
        communicate = edge_tts.Communicate(text, voice, rate=rate)

    words = []
    with open(mp3_path, "wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({
                    "start": start,
                    "end": start + chunk["duration"] / 1e7,
                    "text": chunk["text"],
                })
    return words


def _even_words(text, duration):
    """Approximate word timings when the TTS engine gives none."""
    tokens = text.split()
    total_chars = sum(len(t) for t in tokens) or 1
    usable = duration * 0.95
    t, words = 0.0, []
    for token in tokens:
        d = usable * len(token) / total_chars
        words.append({"start": t, "end": t + d, "text": token})
        t += d
    return words


def _voice_edge(scenes, workdir, voice, rate):
    results = []
    for i, scene in enumerate(scenes):
        mp3 = workdir / f"voice_{i}.mp3"
        wav = workdir / f"voice_{i}.wav"
        last_error = None
        for _attempt in range(3):
            try:
                words = asyncio.run(_edge_tts(scene["narration"], voice, rate, mp3))
                if mp3.stat().st_size < 2000:
                    raise RuntimeError("edge-tts returned empty audio")
                break
            except Exception as error:  # transient network errors are common
                last_error = error
        else:
            raise RuntimeError(f"edge-tts failed: {last_error}")
        run_ffmpeg(["-i", mp3, "-ar", "44100", "-ac", "1", wav])
        duration = wav_duration(wav)
        results.append({
            "path": wav,
            "duration": duration,
            "words": words or _even_words(scene["narration"], duration),
            "engine": "edge-tts",
        })
    return results


def _voice_espeak(scenes, workdir):
    results = []
    for i, scene in enumerate(scenes):
        raw = workdir / f"voice_{i}_raw.wav"
        wav = workdir / f"voice_{i}.wav"
        subprocess.run(["espeak-ng", "-v", "hi", "-s", "150", "-w", str(raw),
                        scene["narration"]], check=True)
        run_ffmpeg(["-i", raw, "-ar", "44100", "-ac", "1", wav])
        duration = wav_duration(wav)
        results.append({
            "path": wav,
            "duration": duration,
            "words": _even_words(scene["narration"], duration),
            "engine": "espeak-ng",
        })
    return results


def synthesize_scenes(scenes, workdir):
    voice = env("TTS_VOICE", "hi-IN-MadhurNeural")
    rate = env("TTS_RATE", "+8%")
    try:
        results = _voice_edge(scenes, workdir, voice, rate)
        print(f"VOICE: edge-tts {voice} rate={rate}")
        return results
    except Exception as error:
        print("EDGE_TTS_FAILED, falling back to espeak-ng:", error)
        return _voice_espeak(scenes, workdir)
