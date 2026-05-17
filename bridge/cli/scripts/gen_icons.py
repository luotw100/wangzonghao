"""Render the Studio 'L' mark into app icons (ico / icns / png).

Run locally when the mark changes; the generated assets in
laborster_bridge/gui/assets/ are committed so CI needs no SVG toolchain.

    python scripts/gen_icons.py

Source mark (services/studio/web/public/favicon.svg), 28x28 viewBox:
  rounded square, diagonal gradient cyan->blue->purple,
  white "L" stroke, cyan dot at the elbow's end.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "laborster_bridge" / "gui" / "assets"
SS = 8  # supersample factor
VB = 28  # source viewBox units


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _grad(x, y, n):
    # Diagonal gradient along (2,2)->(26,26): two stops at t=0.5.
    t = max(0.0, min(1.0, ((x + y) / n - 2 / VB) / (24 / VB)))
    c0, c1, c2 = (0, 229, 255), (59, 130, 246), (139, 92, 246)
    return _lerp(c0, c1, t / 0.5) if t < 0.5 else _lerp(c1, c2, (t - 0.5) / 0.5)


def render(size: int) -> Image.Image:
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = n / VB  # px per viewBox unit

    # rounded-rect mask, filled row-wise with the diagonal gradient
    radius = int(8 * u)
    rect = [int(2 * u), int(2 * u), int(26 * u), int(26 * u)]
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(rect, radius=radius, fill=255)
    grad = Image.new("RGBA", (n, n))
    gp = grad.load()
    step = max(1, n // 256)
    for y in range(0, n, step):
        for x in range(0, n, step):
            c = _grad(x, y, n) + (255,)
            for yy in range(y, min(y + step, n)):
                for xx in range(x, min(x + step, n)):
                    gp[xx, yy] = c
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    lw = int(round(2.4 * u))
    pts = [(9 * u, 8.5 * u), (9 * u, 19.5 * u), (19 * u, 19.5 * u)]
    d.line(pts, fill=(255, 255, 255, 255), width=lw, joint="curve")
    for px, py in pts:
        d.ellipse([px - lw / 2, py - lw / 2, px + lw / 2, py + lw / 2],
                  fill=(255, 255, 255, 255))
    r = int(2 * u)
    cx, cy = int(19 * u), int(19.5 * u)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 229, 255, 255))

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256, 512, 1024]
    imgs = {s: render(s) for s in sizes}

    imgs[512].save(OUT / "LaborsterBridge.png")
    imgs[256].save(
        OUT / "LaborsterBridge.ico",
        sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)],
    )
    icns_sizes = [16, 32, 64, 128, 256, 512, 1024]
    imgs[1024].save(
        OUT / "LaborsterBridge.icns",
        append_images=[imgs[s] for s in icns_sizes if s != 1024],
    )
    print("wrote:", *(p.name for p in sorted(OUT.iterdir())))


if __name__ == "__main__":
    main()
