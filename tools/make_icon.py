"""Draw brand/icon.png (256) and brand/icon@2x.png (512): speed gauge with a padlock."""
import math
import pathlib

from PIL import Image, ImageDraw

OUT = pathlib.Path(__file__).parents[1] / "custom_components" / "switchbot_lock_speed" / "brand"
S = 2048  # supersampled canvas, downscaled for anti-aliasing

RED = (226, 54, 46, 255)
RED_DARK = (176, 30, 26, 255)
WHITE = (255, 255, 255, 255)
SOFT = (255, 255, 255, 120)


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # rounded tile with a subtle vertical gradient
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = Image.new("RGBA", (1, S))
    for y in range(S):
        t = y / (S - 1)
        grad.putpixel((0, y), tuple(round(RED[i] + (RED_DARK[i] - RED[i]) * t) for i in range(4)))
    grad = grad.resize((S, S))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.22), fill=255)
    tile.paste(grad, (0, 0), mask)
    img.alpha_composite(tile)

    # gauge: 240 degree arc in three zones (Low / Standard / Max)
    cx, cy, r, w = S / 2, S * 0.50, S * 0.34, S * 0.075
    box = (cx - r, cy - r, cx + r, cy + r)
    start, end, gap = 150, 390, 6
    zone = (end - start) / 3
    for i, alpha in enumerate((110, 185, 255)):
        a0 = start + i * zone + (gap / 2 if i else 0)
        a1 = start + (i + 1) * zone - (gap / 2 if i < 2 else 0)
        d.arc(box, a0, a1, fill=(255, 255, 255, alpha), width=int(w))
    for a in (start, end):  # rounded arc ends
        x = cx + (r - w / 2) * math.cos(math.radians(a))
        y = cy + (r - w / 2) * math.sin(math.radians(a))
        alpha = 110 if a == start else 255
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=(255, 255, 255, alpha))

    # needle towards the "Standard"/"Max" boundary
    ang = math.radians(start + zone * 2 - 8)
    tip = (cx + (r - w * 1.6) * math.cos(ang), cy + (r - w * 1.6) * math.sin(ang))
    base = S * 0.032
    perp = ang + math.pi / 2
    d.polygon(
        [
            tip,
            (cx + base * math.cos(perp), cy + base * math.sin(perp)),
            (cx - base * math.cos(perp), cy - base * math.sin(perp)),
        ],
        fill=WHITE,
    )
    hub = S * 0.045
    d.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=WHITE)
    d.ellipse((cx - hub * 0.45, cy - hub * 0.45, cx + hub * 0.45, cy + hub * 0.45), fill=RED_DARK)

    # padlock below the hub
    bw, bh = S * 0.18, S * 0.135
    bx0, by0 = cx - bw / 2, S * 0.715
    sh_r, sh_w = bw * 0.30, S * 0.032
    d.arc((cx - sh_r, by0 - sh_r * 1.55, cx + sh_r, by0 + sh_r * 0.45), 180, 360, fill=WHITE, width=int(sh_w))
    d.line((cx - sh_r + sh_w / 2, by0 - sh_r * 0.55, cx - sh_r + sh_w / 2, by0 + 2), fill=WHITE, width=int(sh_w))
    d.line((cx + sh_r - sh_w / 2, by0 - sh_r * 0.55, cx + sh_r - sh_w / 2, by0 + 2), fill=WHITE, width=int(sh_w))
    d.rounded_rectangle((bx0, by0, bx0 + bw, by0 + bh), radius=int(S * 0.03), fill=WHITE)
    kh = S * 0.022
    d.ellipse((cx - kh, by0 + bh * 0.32, cx + kh, by0 + bh * 0.32 + 2 * kh), fill=RED_DARK)
    d.rectangle((cx - kh * 0.45, by0 + bh * 0.45, cx + kh * 0.45, by0 + bh * 0.75), fill=RED_DARK)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw()
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        big.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)
        print(OUT / name)


if __name__ == "__main__":
    main()
