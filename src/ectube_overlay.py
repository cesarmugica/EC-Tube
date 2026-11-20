"""EC-Tube: animaciones encima del video (el banco de EC-Tok, cintillos de texto y las animaciones de cada quien).

Cada animación se dibuja aquí cuadro por cuadro (con su texto en el letrero, que sigue el movimiento del personaje)
y se guarda como un video con transparencia; luego FFmpeg la pone encima del video final.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path

OUT_FPS = 30
IMG_EXTS = {".gif", ".webp", ".png", ".apng"}
VID_EXTS = {".webm", ".mp4"}
ANIM_EXTS = IMG_EXTS | VID_EXTS
IMPORT_EXTS = ANIM_EXTS | {".mov", ".mkv", ".avi", ".m4v", ".jpg", ".jpeg"}
SIGN_COLOR = (59, 35, 20, 255)  # el mismo café del letrero de EC-Tok


def anim_label(stem: str) -> str:
    """«Girl-Dey-Sign-Up» → «Girl Dey Sign Up»; «fuegos-artificiales» → «Fuegos artificiales»."""
    text = re.sub(r"[-_]+", " ", stem).strip()
    return text[:1].upper() + text[1:] if text else stem


def load_scenes(*folders: Path) -> dict:
    scenes: dict = {}
    for folder in folders:
        try:
            data = json.loads((folder / "escenas.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            scenes.update(data)
    return scenes


def _font(size: int):
    from PIL import ImageFont

    windir = os.environ.get("WINDIR", r"C:\Windows")
    for name in (Path(windir) / "Fonts" / "seguibl.ttf", Path(windir) / "Fonts" / "segoeuib.ttf",
                 Path(windir) / "Fonts" / "arialbd.ttf", Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")):
        if name.is_file():
            return ImageFont.truetype(str(name), max(6, int(size)))
    return ImageFont.load_default()


def _is_emoji(ch: str) -> bool:
    o = ord(ch)
    return o >= 0x1F000 or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF or o in (0x200D, 0xFE0F, 0x20E3)


def _runs(text: str) -> list[tuple[str, bool]]:
    """Partir el texto en pedazos de letras y pedazos de emojis (los emojis se dibujan con su propia fuente, a color)."""
    runs: list[tuple[str, bool]] = []
    for ch in text:
        emo = _is_emoji(ch)
        if runs and runs[-1][1] == emo:
            runs[-1] = (runs[-1][0] + ch, emo)
        else:
            runs.append((ch, emo))
    return runs


EMOJI_CACHE: dict = {}


def _emoji(cluster: str, size: int):
    """Un emoji a color de size × size (Segoe UI Emoji en Windows); None si no hay con qué dibujarlo."""
    from PIL import Image, ImageDraw, ImageFont

    key = (cluster, size)
    if key in EMOJI_CACHE:
        return EMOJI_CACHE[key]
    img = None
    windir = os.environ.get("WINDIR", r"C:\Windows")
    for path, fixed in ((Path(windir) / "Fonts" / "seguiemj.ttf", 0), (Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"), 109)):
        if not path.is_file():
            continue
        try:
            fs = fixed or max(8, size)
            font = ImageFont.truetype(str(path), fs)
            box = font.getbbox(cluster)
            w, h = max(1, box[2]), max(1, box[3])
            tmp = Image.new("RGBA", (w + 4, h + 4), (0, 0, 0, 0))
            ImageDraw.Draw(tmp).text((0, 0), cluster, font=font, embedded_color=True)
            bb = tmp.getbbox()
            if bb:
                tmp = tmp.crop(bb)
                img = tmp.resize((max(1, round(size * tmp.width / max(tmp.height, 1))), size), Image.LANCZOS)
                break
        except Exception:  # noqa: BLE001
            continue
    EMOJI_CACHE[key] = img
    return img


def _clusters(text: str) -> list[str]:
    """Emojis completos (con sus uniones ZWJ y selectores), uno por uno."""
    out: list[str] = []
    for ch in text:
        if out and (ch in "\u200d\ufe0f\u20e3" or out[-1].endswith("\u200d")):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _measure(draw, text: str, font, size: float) -> float:
    width = 0.0
    for chunk, emo in _runs(text):
        if emo:
            for c in _clusters(chunk):
                img = _emoji(c, round(size * 0.92))
                width += (img.width if img else 0) + size * 0.06
        else:
            width += draw.textlength(chunk, font=font)
    return width


def _wrap(draw, text: str, font, width: float, size: float) -> list[str] | None:
    lines: list[str] = []
    for para in text.split("\n"):
        words, line = para.split(), ""
        for word in words:
            if _measure(draw, word, font, size) > width:
                return None  # una palabra no cabe: hay que bajar la letra
            test = (line + " " + word).strip()
            if _measure(draw, test, font, size) <= width:
                line = test
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def text_block(text: str, width: int, height: int, color=SIGN_COLOR, start: float = 0.5, line: float = 1.08):
    """El texto lo más grande que quepa en width × height (centrado, en varios renglones si hace falta)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
    if not text.strip():
        return img
    draw = ImageDraw.Draw(img)
    size = max(8.0, height * start)
    while True:
        font = _font(size)
        lines = _wrap(draw, text, font, width, size)
        if lines is not None and len(lines) * size * line <= height or size <= 7:
            break
        size *= 0.93
    lines = lines or [text]
    total = len(lines) * size * line
    y = (height - total) / 2
    for row in lines:
        x = (width - _measure(draw, row, font, size)) / 2
        top = y + (size * line - size) / 2
        for chunk, emo in _runs(row):
            if emo:
                for c in _clusters(chunk):
                    pic = _emoji(c, round(size * 0.92))
                    if pic:
                        img.alpha_composite(pic, (max(0, round(x)), max(0, round(top + size * 0.12))))
                        x += pic.width + size * 0.06
            else:
                draw.text((x, top), chunk, font=font, fill=color)
                x += draw.textlength(chunk, font=font)
        y += size * line
    return img


class Anim:
    """Una animación lista para dibujarse a un tamaño: cuadros, cuánto dura cada uno y dónde va el letrero."""

    def __init__(self, path: Path, scene: dict | None, ffmpeg: str, flags: int = 0) -> None:
        self.path, self.scene, self.ffmpeg, self.flags = path, scene or {}, ffmpeg, flags

    @property
    def has_text(self) -> bool:
        return bool(self.scene.get("track") or self.scene.get("sign"))

    def frames(self, width: int, height: int) -> tuple[list, list[float], list]:
        """(cuadros RGBA a width × height, segundos de cada cuadro, caja del letrero de cada cuadro)."""
        from PIL import Image, ImageSequence

        sc, size = self.scene, (max(2, width), max(2, height))
        frames, durs = [], []
        if sc.get("sprite"):  # tira de cuadros (las escenas que trae EC-Tok)
            sp = sc["sprite"]
            strip = Image.open(self.path.parent / sp["file"]).convert("RGBA")
            n = int(sp.get("n") or 1)
            fw = strip.width / n
            for i in range(n):
                frames.append(strip.crop((round(i * fw), 0, round((i + 1) * fw), strip.height)).resize(size, Image.LANCZOS))
                durs.append((sp.get("durs") or [120] * n)[i] / 1000)
        elif self.path.suffix.lower() in VID_EXTS or self.path.suffix.lower() == ".mov":
            fps = float((sc.get("video") or {}).get("fps") or 0) or self._fps()
            info = subprocess.run([self.ffmpeg, "-hide_banner", "-nostdin", "-i", str(self.path)], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", creationflags=self.flags).stderr
            decoder = ["-c:v", "libvpx-vp9"] if re.search(r"Video: vp9", info) else ["-c:v", "libvpx"] if re.search(r"Video: vp8", info) else []
            raw = subprocess.run([self.ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", *decoder, "-i", str(self.path),
                                  "-t", "60", "-vf", f"fps={fps},scale={size[0]}:{size[1]}:flags=lanczos", "-pix_fmt", "rgba",
                                  "-f", "rawvideo", "pipe:1"], capture_output=True, creationflags=self.flags).stdout
            step = size[0] * size[1] * 4
            for i in range(len(raw) // step):
                frames.append(Image.frombuffer("RGBA", size, raw[i * step:(i + 1) * step], "raw", "RGBA", 0, 1).copy())
                durs.append(1 / fps)
        else:  # GIF, WebP, APNG o PNG
            img = Image.open(self.path)
            for frame in ImageSequence.Iterator(img):
                frames.append(frame.convert("RGBA").resize(size, Image.LANCZOS))
                durs.append(max(0.02, (frame.info.get("duration") or 100) / 1000))
        if not frames:
            raise RuntimeError(f"No se pudo leer la animación «{self.path.name}».")
        if len(frames) == 1:
            durs = [1.0]
        for part in sc.get("parts") or []:  # partes encima del personaje (por ejemplo el corazón), quietas
            try:
                p = Image.open(self.path.parent / part["file"]).convert("RGBA")
                x, y, pw, ph = part["box"]
                p = p.resize((max(1, round(pw / 100 * size[0])), max(1, round(ph / 100 * size[1]))), Image.LANCZOS)
                for f in frames:
                    f.alpha_composite(p, (round(x / 100 * size[0]), round(y / 100 * size[1])))
            except (OSError, KeyError, ValueError):
                pass
        track = sc.get("track") or []
        if not track and sc.get("sign"):
            x, y, w, h = sc["sign"][:4]
            track = [[x + w / 2, y + h / 2, w, h, 0]]
        boxes = [track[min(i, len(track) - 1)] for i in range(len(frames))] if track else []
        return frames, durs, boxes

    def _fps(self) -> float:
        info = subprocess.run([self.ffmpeg, "-hide_banner", "-nostdin", "-i", str(self.path)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", creationflags=self.flags).stderr
        m = re.search(r"(\d+(?:\.\d+)?) fps", info)
        return min(30.0, float(m[1])) if m else 16.0


def _ease_back(t: float) -> float:
    c = 1.70158
    t -= 1
    return 1 + (c + 1) * t ** 3 + c * t ** 2


def banner(text: str, width: int, height: int, color: str = "#FE2C55"):
    """Cintillo tipo alerta: tarjeta oscura con borde de color y el texto en blanco."""
    from PIL import Image, ImageDraw

    rgb = tuple(int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) if re.fullmatch(r"#[0-9a-fA-F]{6}", color or "") else (254, 44, 85)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = min(height // 3, 40)
    border = max(2, round(height * 0.05))
    d.rounded_rectangle((0, 0, width - 1, height - 1), radius=r, fill=(*rgb, 255))
    d.rounded_rectangle((border, border, width - 1 - border, height - 1 - border), radius=max(2, r - border), fill=(22, 22, 28, 238))
    pad = border + max(4, round(height * 0.12))
    img.alpha_composite(text_block(text, width - 2 * pad - round(height * 0.1), height - 2 * pad, color=(255, 255, 255, 255),
                                   start=0.62, line=1.1), (pad + round(height * 0.05), pad))
    return img


def render(item: dict, width: int, height: int, out: Path, ffmpeg: str, flags: int = 0) -> Path:
    """Dibujar una animación (o un cintillo) de width × height que dura item['dur'] segundos, con transparencia."""
    from PIL import Image

    width, height = max(2, int(width) // 2 * 2), max(2, int(height) // 2 * 2)
    dur = max(0.2, float(item["dur"]))
    text = str(item.get("text") or "")
    pop = item.get("pop", True)
    if item.get("kind") == "banner":
        frames, durs, boxes, layer = [banner(text, width, height, item.get("color") or "#FE2C55")], [1.0], [], None
        scene_like = False
    else:
        anim = Anim(Path(item["path"]), item.get("scene"), ffmpeg, flags)
        frames, durs, boxes = anim.frames(width, height)
        scene_like = bool(item.get("scene"))
        layer = None
        if boxes and text.strip():
            # el texto se hace una vez, del tamaño del letrero más chico, y luego sigue al letrero cuadro por cuadro
            sw = min(b[2] for b in boxes) / 100 * width
            sh = min(b[3] for b in boxes) / 100 * height
            layer = text_block(text, round(sw * 0.9), round(sh * 0.96 * 0.88))
    starts, acc = [], 0.0
    for d in durs:
        starts.append(acc)
        acc += d
    loop = acc or 1.0
    rotated: dict = {}
    proc = subprocess.Popen([ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                             "-s", f"{width}x{height}", "-r", str(OUT_FPS), "-i", "pipe:0", "-c:v", "qtrle", str(out)],
                            stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
    try:
        total = max(1, round(dur * OUT_FPS))
        for k in range(total):
            t = k / OUT_FPS
            lt = t % loop
            i = max(0, min(len(frames) - 1, next((j for j in range(len(starts) - 1, -1, -1) if starts[j] <= lt), 0)))
            frame = frames[i]
            if layer is not None:
                frame = frame.copy()
                cx, cy, _, _, deg = (list(boxes[i]) + [0])[:5]
                key = round(float(deg), 1)
                if key not in rotated:
                    rotated[key] = layer.rotate(-key, resample=Image.BICUBIC, expand=True)
                lay = rotated[key]
                frame.alpha_composite(lay, (round(cx / 100 * width - lay.width / 2), round(cy / 100 * height - lay.height / 2)))
            if pop:  # entrada con rebote y salida suave
                inn, outt = min(0.5, dur / 3), min(0.35, dur / 4)
                scale, alpha = 1.0, 1.0
                if t < inn:
                    p = t / inn
                    scale, alpha = 0.35 + 0.65 * _ease_back(p), min(1.0, p * 2.5)
                elif t > dur - outt:
                    p = (dur - t) / outt
                    scale, alpha = 0.85 + 0.15 * p, max(0.0, p)
                if scale != 1.0 or alpha != 1.0:
                    sw, sh = max(1, round(width * scale)), max(1, round(height * scale))
                    small = frame.resize((sw, sh), Image.BILINEAR)
                    if alpha < 1:
                        a = small.getchannel("A").point(lambda v, f=alpha: round(v * f))
                        small.putalpha(a)
                    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                    x = (width - sw) // 2
                    y = height - sh if scene_like else (height - sh) // 2  # los personajes brincan desde abajo
                    canvas.alpha_composite(small, (x, y)) if sw <= width and sh <= height else canvas.paste(small, (x, y), small)
                    frame = canvas
            proc.stdin.write(frame.tobytes())  # type: ignore[union-attr]
        proc.stdin.close()  # type: ignore[union-attr]
        if proc.wait() != 0:
            raise RuntimeError("No se pudo preparar una animación: " + proc.stderr.read().decode("utf-8", "replace")[-300:])  # type: ignore[union-attr]
    except BaseException:
        proc.kill()
        out.unlink(missing_ok=True)
        raise
    return out


def cache_key(item: dict, width: int, height: int) -> str:
    path = Path(item["path"]) if item.get("path") else None
    stamp = f"{path}:{path.stat().st_mtime}" if path and path.exists() else ""
    data = json.dumps({k: item.get(k) for k in ("kind", "text", "dur", "color", "pop")}, sort_keys=True)
    return hashlib.sha1(f"{stamp}|{data}|{width}x{height}|v1".encode()).hexdigest()[:20]


def overlay_size(fw: float, fh: float, W: int, H: int) -> tuple[int, int]:
    return max(2, round(fw * W) // 2 * 2), max(2, round(fh * H) // 2 * 2)


__all__ = ["ANIM_EXTS", "IMPORT_EXTS", "Anim", "anim_label", "load_scenes", "render", "cache_key", "overlay_size"]
