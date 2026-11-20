"""Shared helpers: env vars, time zone, ffmpeg runner."""
import os
import subprocess
import wave
from datetime import timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
FFMPEG = os.getenv("FFMPEG_BIN") or "ffmpeg"


def env(name, default=""):
    """Read an env var; empty strings (e.g. unset GitHub vars) count as unset."""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def run_ffmpeg(args, cwd=None):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)]
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-2500:]}")


def wav_duration(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / float(w.getframerate())
