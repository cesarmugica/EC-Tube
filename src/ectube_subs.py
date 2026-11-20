"""EC-Tube: subtítulos en bloques (como en las películas). Leer los de YouTube, armar el .srt y el .ass con el estilo."""
from __future__ import annotations

import html
import json
import re

FONTS = ["Arial", "Arial Black", "Segoe UI", "Segoe UI Black", "Impact", "Verdana", "Tahoma", "Trebuchet MS",
         "Georgia", "Comic Sans MS", "Bahnschrift", "Courier New", "Times New Roman"]
POSITIONS = {"bottom": 2, "middle": 5, "top": 8}
HEX = re.compile(r"#[0-9a-fA-F]{6}")

DEFAULT_STYLE = {"font": "Arial Black", "size": 6.0, "fill": "#FFE600", "outline": "#000000", "outline_w": 3.0,
                 "shadow": 1.0, "box": False, "box_color": "#000000", "box_alpha": 0.6, "pos": "bottom", "margin": 6.0,
                 "bold": True, "upper": False}


def clean_style(raw: dict | None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    s = dict(DEFAULT_STYLE)
    if raw.get("font") in FONTS:
        s["font"] = raw["font"]
    for key, lo, hi in (("size", 2.0, 16.0), ("outline_w", 0.0, 12.0), ("shadow", 0.0, 8.0), ("box_alpha", 0.0, 1.0), ("margin", 0.0, 40.0)):
        try:
            s[key] = max(lo, min(hi, float(raw.get(key, s[key]))))
        except (TypeError, ValueError):
            pass
    for key in ("fill", "outline", "box_color"):
        if HEX.fullmatch(str(raw.get(key) or "")):
            s[key] = str(raw[key]).upper()
    if raw.get("pos") in POSITIONS:
        s["pos"] = raw["pos"]
    for key in ("box", "bold", "upper"):
        if key in raw:
            s[key] = bool(raw[key])
    return s


def clean_blocks(raw) -> list[dict]:
    out = []
    for item in (raw or [])[:5000]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").replace("\r", "")[:500]
        try:
            start = float(item["start"]) if item.get("start") is not None else None
            end = float(item["end"]) if item.get("end") is not None else None
        except (TypeError, ValueError):
            start = end = None
        out.append({"text": text, "start": None if start is None else round(max(0.0, start), 3),
                    "end": None if end is None else round(max(0.0, end), 3)})
    return out


def timed(blocks: list[dict]) -> list[dict]:
    """Solo los bloques con texto y tiempos válidos, en orden."""
    good = [b for b in blocks if b.get("text", "").strip() and b.get("start") is not None and b.get("end") is not None
            and b["end"] - b["start"] >= 0.05]
    return sorted(good, key=lambda b: b["start"])


# ---------- .srt ----------
def _srt_ts(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def build_srt(blocks: list[dict], upper: bool = False) -> str:
    rows = []
    for n, b in enumerate(timed(blocks), 1):
        text = b["text"].strip()
        rows.append(f"{n}\n{_srt_ts(b['start'])} --> {_srt_ts(b['end'])}\n{text.upper() if upper else text}\n")
    return "\n".join(rows)


def parse_srt(text: str) -> list[dict]:
    """Leer un .srt o .vtt (por si alguien ya tiene sus subtítulos)."""
    out = []
    ts = r"(\d+):(\d\d):(\d\d)[.,](\d{1,3})|(\d\d):(\d\d)[.,](\d{1,3})"

    def sec(m: re.Match) -> float:
        if m.group(1) is not None:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4).ljust(3, "0")) / 1000
        return int(m.group(5)) * 60 + int(m.group(6)) + int(m.group(7).ljust(3, "0")) / 1000

    for chunk in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = [x for x in chunk.split("\n") if x.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, b = line.split("-->", 1)
                ma, mb = re.search(ts, a), re.search(ts, b)
                if ma and mb:
                    body = "\n".join(re.sub(r"<[^>]+>", "", x) for x in lines[i + 1:]).strip()
                    if body:
                        out.append({"start": round(sec(ma), 3), "end": round(sec(mb), 3), "text": html.unescape(body)})
                break
    return out


# ---------- subtítulos de YouTube ----------
def _group(words: list[tuple[float, float, str]], max_chars: int = 84, max_dur: float = 6.0, gap: float = 1.2) -> list[dict]:
    """Juntar palabras (o pedacitos) en bloques de una o dos líneas, como en las películas."""
    blocks: list[dict] = []
    cur: list[tuple[float, float, str]] = []

    def flush() -> None:
        if cur:
            text = re.sub(r"\s+", " ", " ".join(w[2] for w in cur)).strip()
            if text:
                blocks.append({"start": round(cur[0][0], 3), "end": round(cur[-1][1], 3), "text": text})
        cur.clear()

    for w in words:
        if cur and (w[0] - cur[-1][1] > gap or w[1] - cur[0][0] > max_dur
                    or len(" ".join(x[2] for x in cur)) + len(w[2]) + 1 > max_chars):
            flush()
        cur.append(w)
        if re.search(r"[.!?…]$", w[2]) and len(" ".join(x[2] for x in cur)) > 25:
            flush()
    flush()
    # que cada bloque dure al menos 1 s (sin encimarse con el siguiente)
    for i, b in enumerate(blocks):
        nxt = blocks[i + 1]["start"] if i + 1 < len(blocks) else b["end"] + 2
        b["end"] = round(min(max(b["end"], b["start"] + 1.0), nxt - 0.05 if nxt - 0.05 > b["start"] + 0.3 else b["end"]), 3)
    return [_two_lines(b) for b in blocks]


def _two_lines(block: dict, limit: int = 42) -> dict:
    """Partir en dos renglones parejos si el texto es largo."""
    text = block["text"]
    if len(text) <= limit or "\n" in text:
        return block
    words = text.split(" ")
    best, cut = 10 ** 9, len(words) // 2
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        if abs(len(a) - len(b)) < best:
            best, cut = abs(len(a) - len(b)), i
    return {**block, "text": " ".join(words[:cut]) + "\n" + " ".join(words[cut:])}


def parse_json3(data: str | dict) -> list[dict]:
    """El formato json3 de YouTube (normal o automático). En los automáticos cada palabra trae su tiempo."""
    obj = json.loads(data) if isinstance(data, str) else data
    events = [e for e in obj.get("events", []) if e.get("segs")]
    words: list[tuple[float, float, str]] = []
    auto = any(len(e["segs"]) > 1 and any("tOffsetMs" in s for s in e["segs"]) for e in events)
    for i, ev in enumerate(events):
        start = ev.get("tStartMs", 0) / 1000
        dur = ev.get("dDurationMs", 0) / 1000
        nxt = events[i + 1].get("tStartMs", 0) / 1000 if i + 1 < len(events) else start + dur
        segs = [s for s in ev["segs"] if (s.get("utf8") or "").strip()]
        if not segs:
            continue
        if auto:
            for j, s in enumerate(segs):
                ws = start + s.get("tOffsetMs", 0) / 1000
                we = start + segs[j + 1].get("tOffsetMs", 0) / 1000 if j + 1 < len(segs) else min(start + dur, nxt if nxt > ws else start + dur)
                words.append((ws, max(we, ws + 0.2), s["utf8"].strip()))
        else:
            text = "".join(s.get("utf8") or "" for s in ev["segs"]).strip()
            words.append((start, start + max(dur, 0.3), text.replace("\n", " ")))
    if not auto:  # subtítulos hechos por alguien: ya vienen en bloques
        return [_two_lines({"start": round(a, 3), "end": round(b, 3), "text": t}) for a, b, t in words if t]
    return _group(sorted(words))


def parse_vtt(text: str) -> list[dict]:
    """VTT de YouTube: en los automáticos cada línea se repite al ir «subiendo»; nos quedamos con lo nuevo."""
    cues = parse_srt(text)
    words: list[tuple[float, float, str]] = []
    seen = ""
    for c in cues:
        line = c["text"].split("\n")[-1].strip()
        if not line or line == seen:
            continue
        seen = line
        words.append((c["start"], c["end"], line))
    return _group(words)


# ---------- .ass (para pegarlos en el video) ----------
def _ass_color(hex_color: str, alpha: float = 0.0) -> str:
    rgb = hex_color.lstrip("#")
    a = max(0, min(255, round(alpha * 255)))
    return f"&H{a:02X}{rgb[4:6]}{rgb[2:4]}{rgb[0:2]}".upper()


def _ass_ts(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def build_ass(blocks: list[dict], style: dict, width: int, height: int) -> str:
    s = clean_style(style)
    ref = min(width, height) if width < height else height  # en vertical se mide con el ancho
    size = max(8, round(ref * s["size"] / 100))
    outline = round(s["outline_w"] * size / 40, 2)
    shadow = round(s["shadow"] * size / 40, 2)
    margin_v = round(height * s["margin"] / 100)
    margin_lr = round(width * 0.05)
    if s["box"]:  # caja detrás del texto: en libass la caja usa el color de la orilla
        border_style, out_col, back = 3, _ass_color(s["box_color"], 1 - s["box_alpha"]), _ass_color(s["box_color"], 1 - s["box_alpha"])
        outline = max(outline, round(size * 0.18, 2))
        shadow = 0
    else:
        border_style, out_col, back = 1, _ass_color(s["outline"]), _ass_color("#000000", 0.45)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: S,{s['font']},{size},{_ass_color(s['fill'])},{_ass_color(s['fill'])},{out_col},{back},{-1 if s['bold'] else 0},0,0,0,"
        f"100,100,0,0,{border_style},{outline},{shadow},{POSITIONS[s['pos']]},{margin_lr},{margin_lr},{margin_v},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for b in timed(blocks):
        text = b["text"].strip()
        text = text.upper() if s["upper"] else text
        text = text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{_ass_ts(b['start'])},{_ass_ts(b['end'])},S,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"
