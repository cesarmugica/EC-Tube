"""Karaoke: letra con tiempos → video con la letra iluminándose (subtítulos ASS con \\kf, FFmpeg + libass).

La página y este módulo usan la MISMA regla para acomodar las líneas (layout), así
la vista previa se ve igual que el video final.

Formato de la letra: un renglón = una línea en pantalla. Las palabras se separan con
espacios; con «/» se parte una palabra en sílabas que se iluminan por separado
(«co/ra/zón»). Un renglón vacío solo separa estrofas.
"""

from __future__ import annotations

import re

SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
LEAD_IN = 3.0       # una línea aparece hasta 3 s antes de cantarse
HOLD_AFTER = 0.6    # y se queda 0.6 s después de su última palabra
COUNTDOWN_GAP = 6.0 # si antes de una línea hay 6 s o más sin cantar: cuenta regresiva ● ● ●


def parse_lyrics(text: str) -> list[list[dict]]:
    """Texto → líneas → unidades (palabras o sílabas). Cada unidad: {"text", "space"} (space = va seguida de espacio)."""
    lines = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        units = []
        words = raw.split()
        for w_index, word in enumerate(words):
            parts = [p for p in word.split("/") if p] or [word.replace("/", "")]
            for p_index, part in enumerate(parts):
                units.append({"text": part, "space": p_index == len(parts) - 1 and w_index < len(words) - 1})
        if units:
            lines.append(units)
    return lines


def layout(lines: list[list[dict]], offset: float = 0.0) -> list[dict]:
    """Cuándo aparece y desaparece cada línea y en qué renglón de la pantalla (0 o 1, alternando)."""
    result = []
    timed = []
    for index, units in enumerate(lines):
        starts = [u["start"] + offset for u in units if u.get("start") is not None]
        ends = [u["end"] + offset for u in units if u.get("end") is not None]
        if not starts or not ends:
            continue
        timed.append((index, min(starts), max(ends)))
    for k, (index, start, end) in enumerate(timed):
        appear = max(0.0, start - LEAD_IN)
        if k >= 2:
            appear = max(appear, timed[k - 2][2] + HOLD_AFTER)  # no encimar con la que ocupaba ese renglón
        if k >= 1:
            appear = max(appear, min(start - 0.25, timed[k - 1][1]))  # no antes de que empiece la anterior
        appear = min(appear, start - 0.05)
        disappear = end + HOLD_AFTER
        if k + 2 < len(timed):
            disappear = min(disappear, max(end + 0.1, timed[k + 2][1] - LEAD_IN))
        gap_before = start - (timed[k - 1][2] if k else 0.0)
        result.append({"line": index, "slot": k % 2, "appear": round(appear, 3), "disappear": round(disappear, 3),
                       "start": start, "end": end, "countdown": gap_before >= COUNTDOWN_GAP and start >= 3.2})
    return result


def font_size(units: list[dict], width: int, height: int) -> int:
    """Tamaño de letra: grande, pero que la línea quepa (estimación: 0.56 × tamaño por carácter)."""
    base = round(min(width, height) * (0.085 if width > height else 0.075))
    chars = sum(len(u["text"]) + (1 if u["space"] else 0) for u in units) or 1
    fit = (width * 0.9) / (chars * 0.56)
    return int(max(28, min(base, fit)))


def slot_y(slot: int, width: int, height: int) -> int:
    if width > height:  # horizontal
        return round(height * (0.70 if slot == 0 else 0.83))
    return round(height * (0.62 if slot == 0 else 0.71))


def _ass_color(hex_color: str) -> str:
    match = re.fullmatch(r"#?([0-9a-fA-F]{6})", hex_color or "")
    rgb = match.group(1) if match else "36C5F0"
    return f"&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def _ts(seconds: float) -> str:
    seconds = max(0.0, seconds)
    cs = int(round(seconds * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _clean(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def build_ass(project: dict, fmt: str) -> str:
    width, height = SIZES.get(fmt, SIZES["16:9"])
    lines = project["lines"]
    offset = float(project.get("offset") or 0)
    sung = _ass_color(project.get("sung_color") or "#36C5F0")
    outline = max(3, round(min(width, height) * 0.006))
    title_size = round(min(width, height) * 0.08)
    out = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        # Primary = ya cantado (se va llenando con \kf); Secondary = por cantar (blanco)
        f"Style: K,Arial,60,{sung},&H00FFFFFF,&H00101010,&H96000000,-1,0,0,0,100,100,0,0,1,{outline},2,5,20,20,20,1",
        f"Style: T,Arial,{title_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H96000000,-1,0,0,0,100,100,0,0,1,{outline},2,5,40,40,20,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    placed = layout(lines, offset)
    title = _clean(project.get("title") or "")
    if title and placed and placed[0]["appear"] > 1.5:
        out.append(f"Dialogue: 0,{_ts(0.4)},{_ts(placed[0]['appear'] - 0.2)},T,,0,0,0,,{{\\an5\\pos({width // 2},{height // 2})\\fad(400,300)}}{title}")
    for item in placed:
        units = lines[item["line"]]
        size = font_size(units, width, height)
        y = slot_y(item["slot"], width, height)
        cursor = item["appear"]
        text = []
        for unit in units:
            start = (unit.get("start") if unit.get("start") is not None else cursor - offset) + offset
            end = (unit.get("end") if unit.get("end") is not None else start - offset + 0.3) + offset
            gap = max(0, round((start - cursor) * 100))
            if gap:
                text.append(f"{{\\k{gap}}}")
            dur = max(1, round((end - max(start, cursor)) * 100))
            text.append(f"{{\\kf{dur}}}{_clean(unit['text'])}{' ' if unit['space'] else ''}")
            cursor = max(cursor, start) + dur / 100
        out.append(f"Dialogue: 1,{_ts(item['appear'])},{_ts(item['disappear'])},K,,0,0,0,,"
                   f"{{\\an5\\pos({width // 2},{y})\\fs{size}\\fad(150,150)}}" + "".join(text))
        if item["countdown"]:
            cy = y - round(size * 1.15)
            for n in range(3, 0, -1):
                start = item["start"] - n
                out.append(f"Dialogue: 2,{_ts(start)},{_ts(start + 1)},K,,0,0,0,,"
                           f"{{\\an5\\pos({width // 2},{cy})\\fs{round(size * 0.7)}\\1c{sung}}}" + " ".join(["●"] * n))
    return "\n".join(out) + "\n"
