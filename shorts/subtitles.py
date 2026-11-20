"""ASS subtitle generation: karaoke word captions, animated scene captions, CTA.

libass (used by ffmpeg's subtitles filter) shapes Devanagari correctly,
which ffmpeg drawtext does not do reliably.
"""
from .common import env

FONT = env("SUB_FONT", "Noto Sans Devanagari")

# Colours are &HAABBGGRR
HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Words,{FONT},96,&H0000D7FF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,8,4,5,70,70,0,1
Style: Hook,{FONT},84,&H00FFFFFF,&H00FFFFFF,&H003C3CE6,&H00000000,-1,0,0,0,100,100,0,0,3,22,0,8,80,80,300,1
Style: Caption,{FONT},66,&H00FFFFFF,&H00FFFFFF,&H50141414,&H00000000,-1,0,0,0,100,100,0,0,3,18,0,8,90,90,320,1
Style: CTA,{FONT},56,&H00FFFFFF,&H00FFFFFF,&H000050FF,&H00000000,-1,0,0,0,100,100,0,0,3,16,0,2,90,90,240,1
Style: Thumb,{FONT},170,&H0000D7FF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,10,6,5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

CTA_TEXT = env("CTA_TEXT", "ऐसे ही facts के लिए Subscribe करें")
WORDS_Y = 1150


def _ts(seconds):
    cs = int(round(max(0.0, seconds) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(text):
    return (str(text).replace("\\", "").replace("{", "(").replace("}", ")")
            .replace("\n", " ").strip())


def _event(start, end, style, text, layer=0):
    return f"Dialogue: {layer},{_ts(start)},{_ts(end)},{style},,0,0,0,,{text}\n"


def _chunks(words, max_words=3, max_chars=18):
    chunks, current = [], []
    for word in words:
        current.append(word)
        text = " ".join(w["text"] for w in current)
        if (len(current) >= max_words or len(text) >= max_chars
                or word["text"].endswith(("।", "?", "!", ",", "."))):
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def build_video_ass(script, audios, offsets, durations):
    out = [HEADER]
    total = offsets[-1] + durations[-1]

    for i, (scene, audio) in enumerate(zip(script["scenes"], audios)):
        offset, dur = offsets[i], durations[i]

        # Top caption card (scene 1 = red hook card)
        if scene.get("caption"):
            style = "Hook" if i == 0 else "Caption"
            anim = r"{\fad(150,120)\fscx60\fscy60\t(0,220,\fscx100\fscy100)}"
            out.append(_event(offset + 0.05, offset + dur - 0.05, style,
                              anim + _esc(scene["caption"]), layer=1))

        # Karaoke word captions: words turn yellow as they are spoken
        chunks = _chunks(audio["words"])
        for ci, chunk in enumerate(chunks):
            start = offset + chunk[0]["start"]
            if ci + 1 < len(chunks):
                end = offset + chunks[ci + 1][0]["start"]
            else:
                end = offset + min(chunk[-1]["end"] + 0.35, dur)
            parts = []
            for wi, word in enumerate(chunk):
                nxt = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else word["end"]
                k = max(1, int(round((nxt - word["start"]) * 100)))
                parts.append(f"{{\\k{k}}}{_esc(word['text'])}")
            pop = rf"{{\pos(540,{WORDS_Y})\fscx85\fscy85\t(0,110,\fscx100\fscy100)}}"
            out.append(_event(start, end, "Words", pop + " ".join(parts), layer=2))

    # Call to action in the last 2.5 seconds
    out.append(_event(max(0, total - 2.5), total, "CTA",
                      r"{\fad(200,0)}" + _esc(CTA_TEXT), layer=3))
    return "".join(out)


def build_thumbnail_ass(text):
    return HEADER + _event(0, 10, "Thumb", r"{\pos(540,900)}" + _esc(text))
