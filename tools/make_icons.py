"""Genera el ícono de EC-Tube: nota musical, video y flecha de descarga."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "src" / "web" / "img"


def draw(size: int = 512) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=(108, 76, 230, 255))
    white = (255, 255, 255, 255)
    # Nota musical (arriba a la izquierda) y cuadro de video (arriba a la derecha)
    d.ellipse([s * .16, s * .30, s * .30, s * .42], fill=white)
    d.rectangle([s * .265, s * .12, s * .30, s * .36], fill=white)
    d.polygon([(s * .30, s * .12), (s * .40, s * .16), (s * .40, s * .22), (s * .30, s * .19)], fill=white)
    d.rounded_rectangle([s * .52, s * .14, s * .84, s * .38], radius=int(s * .04), outline=white, width=int(s * .035))
    d.polygon([(s * .64, s * .20), (s * .64, s * .32), (s * .74, s * .26)], fill=white)
    # Flecha de descarga y bandeja
    w = s * .055
    d.rectangle([s * .5 - w, s * .44, s * .5 + w, s * .64], fill=white)
    d.polygon([(s * .32, s * .60), (s * .68, s * .60), (s * .5, s * .78)], fill=white)
    d.rounded_rectangle([s * .20, s * .82, s * .80, s * .88], radius=int(s * .03), fill=white)
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw(512)
    big.resize((192, 192), Image.LANCZOS).save(OUT / "ectube.png")
    big.save(OUT / "ectube.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("íconos en", OUT)
