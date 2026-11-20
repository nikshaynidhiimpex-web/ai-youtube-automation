"""Motion-graphics video rendering with FFmpeg.

Per scene: stock video / Ken-Burns photo / animated gradient + flash-in.
Final pass: animated subtitles, progress bar, optional background music,
loudness normalisation for Shorts (-14 LUFS).
"""
import random
from pathlib import Path

from . import subtitles
from .common import env, run_ffmpeg

W, H, FPS = 1080, 1920, 30
PALETTES = [
    ("0x0f2027", "0x2c5364"), ("0x141e30", "0x243b55"), ("0x42275a", "0x734b6d"),
    ("0x0f0c29", "0x302b63"), ("0x1d4350", "0xa43931"), ("0x232526", "0x414345"),
]
FINISH = ("fps=30,setsar=1,eq=brightness=-0.05:saturation=1.12,"
          "vignette=angle=PI/5,format=yuv420p,fade=t=in:st=0:d=0.18")
MUSIC_DIR = Path("assets/music")


def _encode_args(dur, out):
    return ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-r", str(FPS), "-t", f"{dur:.3f}", out]


def _scene_clip(media, dur, out, variant):
    frames = max(1, int(round(dur * FPS)))
    if media["type"] == "video":
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{FINISH}"
        run_ffmpeg(["-stream_loop", "-1", "-i", media["path"], "-vf", vf,
                    *_encode_args(dur, out)])
        return

    if media["type"] == "image":
        # Ken Burns: zoom in / zoom out / slow pan, alternating per scene
        mode = variant % 3
        z = {0: f"1+0.15*on/{frames}", 1: f"1.15-0.15*on/{frames}", 2: "1.12"}[mode]
        x = f"(iw-iw/zoom)*on/{frames}" if mode == 2 else "iw/2-(iw/zoom/2)"
        vf = ("scale=1620:2880:force_original_aspect_ratio=increase,crop=1620:2880,"
              f"zoompan=z='{z}':x='{x}':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},"
              + FINISH)
        run_ffmpeg(["-loop", "1", "-framerate", str(FPS), "-i", media["path"],
                    "-vf", vf, *_encode_args(dur, out)])
        return

    c0, c1 = PALETTES[variant % len(PALETTES)]
    try:
        src = f"gradients=s={W}x{H}:r={FPS}:c0={c0}:c1={c1}:speed=0.02:d={dur:.3f}"
        run_ffmpeg(["-f", "lavfi", "-i", src, "-vf", FINISH, *_encode_args(dur, out)])
    except RuntimeError:
        src = f"color=c={c0}:s={W}x{H}:r={FPS}:d={dur:.3f}"
        run_ffmpeg(["-f", "lavfi", "-i", src, "-vf", FINISH, *_encode_args(dur, out)])


def _subtitle_filter(ass_name):
    fonts_dir = env("SUB_FONTS_DIR", "/usr/share/fonts/truetype/noto")
    if Path(fonts_dir).is_dir():
        escaped = fonts_dir.replace("\\", "/").replace(":", "\\:")
        return f"subtitles={ass_name}:fontsdir='{escaped}'"
    return f"subtitles={ass_name}"


def _pick_music():
    if not MUSIC_DIR.is_dir():
        return None
    tracks = [p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav")]
    return random.choice(tracks).resolve() if tracks else None


def render_short(script, audios, media, workdir):
    workdir = Path(workdir)
    durations = [a["duration"] + 0.25 for a in audios]
    durations[-1] += 0.9  # breathing room for the call-to-action
    offsets, t = [], 0.0
    for d in durations:
        offsets.append(t)
        t += d
    total = t

    # 1. Scene clips
    for i, (m, d) in enumerate(zip(media, durations)):
        _scene_clip(m, d, workdir / f"scene_{i}.mp4", i)
    (workdir / "scenes.txt").write_text(
        "".join(f"file 'scene_{i}.mp4'\n" for i in range(len(durations))),
        encoding="utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", "scenes.txt", "-c", "copy",
                "video_raw.mp4"], cwd=workdir)

    # 2. Narration track, each scene padded to its clip length
    inputs, chains = [], []
    for i, (a, d) in enumerate(zip(audios, durations)):
        inputs += ["-i", Path(a["path"]).name]
        chains.append(f"[{i}:a]aformat=sample_rates=44100:channel_layouts=mono,"
                      f"apad=whole_dur={d:.3f},atrim=duration={d:.3f}[a{i}]")
    chains.append("".join(f"[a{i}]" for i in range(len(audios)))
                  + f"concat=n={len(audios)}:v=0:a=1[aout]")
    run_ffmpeg([*inputs, "-filter_complex", ";".join(chains), "-map", "[aout]",
                "narration.wav"], cwd=workdir)

    # 3. Subtitles
    (workdir / "subs.ass").write_text(
        subtitles.build_video_ass(script, audios, offsets, durations), encoding="utf-8")

    # 4. Final composite
    music = _pick_music()
    args = ["-i", "video_raw.mp4", "-i", "narration.wav"]
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]
        print("MUSIC:", music.name)
    video_chain = (
        f"[0:v]{_subtitle_filter('subs.ass')}[vs];"
        f"color=c=0xFFD400:s={W}x12:r={FPS}:d={total:.3f}[bar];"
        f"[vs][bar]overlay=x='-w+w*t/{total:.3f}':y=H-h-8[v]"
    )
    loud = "loudnorm=I=-14:TP=-1.5:LRA=11"
    if music:
        audio_chain = (f"[2:a]volume=0.12,afade=t=in:d=1,"
                       f"afade=t=out:st={max(0, total - 1.5):.3f}:d=1.5[m];"
                       f"[1:a][m]amix=inputs=2:duration=first:normalize=0,{loud}[a]")
    else:
        audio_chain = f"[1:a]{loud}[a]"
    run_ffmpeg([*args, "-filter_complex", f"{video_chain};{audio_chain}",
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
                "-t", f"{total:.3f}", "-movflags", "+faststart", "short.mp4"], cwd=workdir)
    return workdir / "short.mp4", total


def make_thumbnail(script, workdir):
    workdir = Path(workdir)
    (workdir / "thumb.ass").write_text(
        subtitles.build_thumbnail_ass(script["thumbnail_text"]), encoding="utf-8")
    run_ffmpeg(["-ss", "0.8", "-i", "scene_0.mp4", "-frames:v", "1",
                "-vf", f"eq=brightness=-0.12,{_subtitle_filter('thumb.ass')}",
                "-q:v", "2", "thumbnail.jpg"], cwd=workdir)
    return workdir / "thumbnail.jpg"
