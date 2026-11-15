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


def _fit(units: list[dict], width: int) -> float:
    chars = sum(len(u["text"]) + (1 if u["space"] else 0) for u in units) or 1
    return (width * 0.9) / (chars * 0.56)


def font_size(units: list[dict], width: int, height: int, all_lines: list[list[dict]] | None = None) -> int:
    """Tamaño de letra PAREJO en todo el karaoke: el que le queda a la línea más larga (sin bajar de 60 %
    del tamaño normal). Solo una línea que de plano no quepa a ese tamaño se achica ella sola."""
    base = round(min(width, height) * (0.085 if width > height else 0.075))
    common = base
    if all_lines:
        common = max(base * 0.6, min([base, *(_fit(line, width) for line in all_lines if line)]))
    return int(max(28, min(common, _fit(units, width))))


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
    lyric_video = project.get("video_type") == "lyrics"          # video con letra: sin cuenta regresiva
    plain = lyric_video and not project.get("lyrics_highlight")   # …y sin iluminar: solo aparece y se desvanece
    title = _clean(project.get("title") or "")
    if title and placed and placed[0]["appear"] > 1.5:
        out.append(f"Dialogue: 0,{_ts(0.4)},{_ts(placed[0]['appear'] - 0.2)},T,,0,0,0,,{{\\an5\\pos({width // 2},{height // 2})\\fad(400,300)}}{title}")
    for item in placed:
        units = lines[item["line"]]
        size = font_size(units, width, height, lines)
        y = slot_y(item["slot"], width, height)
        cursor = item["appear"]
        text = []
        if plain:
            words = "".join(f"{_clean(u['text'])}{' ' if u['space'] else ''}" for u in units)
            out.append(f"Dialogue: 1,{_ts(item['appear'])},{_ts(item['disappear'])},K,,0,0,0,,"
                       f"{{\\an5\\pos({width // 2},{y})\\fs{size}\\1c&H00FFFFFF\\fad(300,300)}}{words}")
            continue
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
        if item["countdown"] and not lyric_video:
            cy = y - round(size * 1.15)
            for n in range(3, 0, -1):
                start = item["start"] - n
                out.append(f"Dialogue: 2,{_ts(start)},{_ts(start + 1)},K,,0,0,0,,"
                           f"{{\\an5\\pos({width // 2},{cy})\\fs{round(size * 0.7)}\\1c{sung}}}" + " ".join(["●"] * n))
    return "\n".join(out) + "\n"


# ---------- ajustar a la voz ----------
# Con la voz sola de la canción (separada con el modelo), cada frase que marcaste con un toque largo se
# reparte según CUÁNDO suena la voz de verdad: si el cantante acelera, la iluminación acelera; si termina
# antes de que sueltes, la frase termina cuando termina su voz.

ENV_RATE = 100  # cuadros por segundo de la envolvente de la voz
VOWELS = set("aeiouáéíóúüAEIOUÁÉÍÓÚÜyY")


def voice_envelope(vocals_mono, rate: int = 44100):
    """Voz (mono) → volumen en dB, 100 veces por segundo."""
    import numpy as np

    hop = rate // ENV_RATE
    usable = vocals_mono[: len(vocals_mono) // hop * hop].reshape(-1, hop)
    rms = np.sqrt(np.mean(usable.astype(np.float64) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    kernel = np.ones(3) / 3
    return np.convolve(db, kernel, mode="same").astype(np.float32)


def clean_voice(env, mix, margin_db: float = 12.0):
    """Quitar lo que NO es voz de la voz separada: el separador deja «fantasmas» de la música (intro,
    instrumentos fuertes). Si la «voz» está muy por debajo de la canción completa en ese momento
    (más de 12 dB), es eco de la música, no alguien cantando."""
    import numpy as np

    if mix is None or len(mix) != len(env):
        return env
    return np.where(env - mix >= -margin_db, env, np.float32(-90)).astype(np.float32)


def _weight(text: str) -> float:
    """Cuánto «dura» al cantarse: sílabas (grupos de vocales) y un poco por letra."""
    groups, prev = 0, False
    for ch in text:
        is_vowel = ch in VOWELS
        if is_vowel and not prev:
            groups += 1
        prev = is_vowel
    return max(1, groups) + 0.08 * len(text)


def _clean_mask(mask):
    """Rellenar huecos de menos de 70 ms y quitar ruiditos de menos de 50 ms."""
    import numpy as np

    mask = mask.copy()
    n = len(mask)

    def runs(value):
        i = 0
        while i < n:
            if mask[i] == value:
                j = i
                while j < n and mask[j] == value:
                    j += 1
                yield i, j
                i = j
            else:
                i += 1

    for i, j in list(runs(False)):
        if 0 < i and j < n and j - i < 7:
            mask[i:j] = True
    for i, j in list(runs(True)):
        if j - i < 5:
            mask[i:j] = False
    return np.asarray(mask)


def align_line(env, units: list[dict], start: float, end: float, pad: tuple[float, float] = (0.30, 0.45)) -> list[tuple[float, float]] | None:
    """Tiempos (inicio, fin) de cada palabra de una frase, siguiendo la voz. None si no se oye voz ahí."""
    import numpy as np

    if env is None or not units or end <= start:
        return None
    a = max(0, int((start - pad[0]) * ENV_RATE))
    b = min(len(env), int((end + pad[1]) * ENV_RATE))
    if b - a < 10:
        return None
    window = env[a:b]
    top = float(np.percentile(window, 97))
    if top < -50:  # casi silencio: no hay voz que seguir
        return None
    mask = _clean_mask(window > max(top - 22, -55))
    voiced = np.flatnonzero(mask)
    if voiced.size < 8:
        return None
    # La frase empieza y termina donde suena voz (cerca de tu toque, no en otra frase).
    s_idx = int(np.round((start - a / ENV_RATE) * ENV_RATE))
    first = int(voiced[voiced >= max(0, s_idx - 30)][0]) if np.any(voiced >= max(0, s_idx - 30)) else int(voiced[0])
    last = int(voiced[-1])
    if last <= first:
        return None
    mask[:first] = False
    cum = np.cumsum(mask[: last + 1])
    total = float(cum[-1])
    weights = [_weight(u["text"]) for u in units]
    whole = sum(weights)
    out, acc = [], 0.0
    for w in weights:
        f0, f1 = acc / whole, (acc + w) / whole
        acc += w
        i0 = int(np.searchsorted(cum, f0 * total + 0.5))  # primer cuadro con voz de esta palabra
        i1 = int(np.searchsorted(cum, f1 * total - 0.5))  # último cuadro con voz de esta palabra
        i0, i1 = min(i0, last), min(max(i1, i0), last)
        out.append(((a + i0) / ENV_RATE, (a + i1 + 1) / ENV_RATE))
    return [(round(s, 3), round(max(e, s + 0.06), 3)) for s, e in out]


def estimate_offset(guide_env, source_env, max_lag_s: float = 90.0) -> float:
    """Cuántos segundos está corrida la canción con voz respecto a la pista del karaoke (por si una está recortada).
    Regresa d tal que tiempo_en_pista = tiempo_en_guía + d."""
    import numpy as np

    def onset(env):
        env = np.maximum(env, -60)
        x = np.maximum(0, np.diff(env, prepend=env[:1]))  # subidas de volumen (golpes, notas)
        return (x - x.mean()) / (x.std() + 1e-9)

    g, s = onset(guide_env), onset(source_env)
    n = 1 << int(np.ceil(np.log2(len(g) + len(s))))
    corr = np.fft.irfft(np.fft.rfft(s, n) * np.conj(np.fft.rfft(g, n)), n)
    lag_max = int(max_lag_s * ENV_RATE)
    candidates = np.concatenate([corr[: lag_max + 1], corr[-lag_max:]])
    lags = np.concatenate([np.arange(lag_max + 1), np.arange(-lag_max, 0)])
    best = int(np.argmax(candidates))
    strength = candidates[best] / (np.sqrt((g ** 2).sum() * (s ** 2).sum()) + 1e-9)
    return round(lags[best] / ENV_RATE, 2) if strength > 0.15 else 0.0


def auto_align(env, lines: list[list[str]]) -> list[list[tuple[float, float]] | None]:
    """Borrador automático de TODA la canción, sin marcar nada.

    1) Se buscan los «tramos de voz» (voz seguida, separada por silencios de ≥ 0.3 s).
    2) Se emparejan renglones con tramos en orden (programación dinámica): un renglón puede ocupar varios
       tramos, o varios renglones cortos un tramo; se pueden saltar tramos sueltos (coros, «uuh», adlibs).
       Gana el emparejamiento donde lo que dura cada tramo se parece más a lo largo de su letra.
    3) Cada renglón se afina palabra por palabra con align_line."""
    import math

    import numpy as np

    out: list = [None] * len(lines)
    real = [i for i, line in enumerate(lines) if line]
    if env is None or not real:
        return out
    loud = env[env > -60]
    if loud.size < 50:
        return out
    top = float(np.percentile(loud, 97))
    mask = _clean_mask(env > max(top - 24, -55))
    voiced = np.flatnonzero(mask)
    if voiced.size < 20:
        return out
    phrases, first = [], int(voiced[0])
    for k in range(1, voiced.size + 1):
        if k == voiced.size or voiced[k] - voiced[k - 1] >= 30:
            last = int(voiced[k - 1])
            if last - first >= 8:  # tramos de menos de 0.08 s: ruido
                phrases.append((first / ENV_RATE, (last + 1) / ENV_RATE))
            if k < voiced.size:
                first = int(voiced[k])
    if not phrases:
        return out
    weights = [sum(_weight(x) for x in lines[i]) for i in real]
    L, P = len(real), len(phrases)
    rate = sum(e - s for s, e in phrases) / sum(weights)
    INF = float("inf")
    MAXRUN = 4
    cost = [[INF] * (P + 1) for _ in range(L + 1)]
    back: list[list[tuple | None]] = [[None] * (P + 1) for _ in range(L + 1)]
    cost[0][0] = 0.0
    for i in range(L + 1):
        for j in range(P + 1):
            c0 = cost[i][j]
            if c0 == INF:
                continue
            skip = 0.5 if i == 0 else 1.2  # antes del primer renglón (intro, «yeah», hablado) saltar es barato
            if j < P and c0 + skip < cost[i][j + 1]:  # saltar un tramo (voz sin letra)
                cost[i][j + 1], back[i][j + 1] = c0 + skip, ("skip",)
            if i == L:
                continue
            for nl in range(1, MAXRUN + 1):
                for np_ in range(1, MAXRUN + 1):
                    if (nl > 1 and np_ > 1) or i + nl > L or j + np_ > P:
                        continue
                    span = phrases[j + np_ - 1][1] - phrases[j][0]
                    w = sum(weights[i:i + nl])
                    c = math.log(max(span, 0.05) / (w * rate)) ** 2 + 0.6 * (nl - 1) + 0.3 * (np_ - 1)
                    if c0 + c < cost[i + nl][j + np_]:
                        cost[i + nl][j + np_], back[i + nl][j + np_] = c0 + c, ("pair", nl, np_)
    j_end = min(range(P + 1), key=lambda j: cost[L][j] + 1.2 * (P - j))
    i, j, groups = L, j_end, []
    while i > 0 or j > 0:
        step = back[i][j]
        if step is None:
            break
        if step[0] == "skip":
            j -= 1
            continue
        _, nl, np_ = step
        groups.append((i - nl, nl, j - np_, np_))
        i, j = i - nl, j - np_
    for gi, nl, gj, np_ in reversed(groups):
        start, end = phrases[gj][0], phrases[gj + np_ - 1][1]
        idxs = real[gi:gi + nl]
        units = [{"text": x} for k in idxs for x in lines[k]]
        times = align_line(env, units, start, end, pad=(0.05, 0.05))
        if not times:
            ws = [_weight(u["text"]) for u in units]
            tot, a, times = sum(ws), start, []
            for w in ws:
                b = a + (end - start) * w / tot
                times.append((round(a, 3), round(b, 3)))
                a = b
        pos = 0
        for k in idxs:
            out[k] = times[pos:pos + len(lines[k])]
            pos += len(lines[k])
    return out
