"""Generate every raster brand asset from the one Morfic mark.

The mark is the bow-tie / infinity glyph used in the website header: two triangles meeting at a dot. It is
drawn here with the same geometry as `morfic/static/favicon.svg` (a 42-unit box, centre (21, 21)).

Outputs (build-assets/):
  app.png, app.ico, app.icns   application icon; transparent margin and rounded tile as macOS expects
  brand/favicon-32.png, brand/apple-touch-icon.png   full-bleed tiles used by the website

`scripts/build_mac.sh` runs this before every build, so change the brand here, not in build-assets/.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build-assets"

TILE = (23, 38, 30, 255)     # #17261e
MARK = (188, 230, 140, 255)  # #bce68c
# Closed outline of the mark; the two extra points at the end make the join at (5, 31) round like the others.
POINTS = [(5, 31), (5, 11), (21, 21), (37, 11), (37, 31), (21, 21), (5, 31), (5, 11)]
STROKE, DOT = 3.4, 4.0   # in mark units, heavier than the header mark so it holds up at 16 px
SPAN = 64 / 1.15         # the mark occupies 1 / 1.15 of a 64-unit tile, as in favicon.svg


def render(size: int, margin: float = 0.0, radius: float = 0.234, supersample: int = 4) -> Image.Image:
    """A square icon of `size` px. `margin` is the transparent border as a fraction of the canvas."""
    s = size * supersample
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tile = s * (1 - 2 * margin)
    left = s * margin
    d.rounded_rectangle((left, left, left + tile, left + tile), radius=tile * radius, fill=TILE)
    unit = tile / SPAN
    cx = cy = s / 2
    pts = [(cx + (x - 21) * unit, cy + (y - 21) * unit) for x, y in POINTS]
    w = STROKE * unit
    d.line(pts, fill=MARK, width=round(w), joint="curve")
    for x, y in pts[:-1]:
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=MARK)
    r = DOT * unit
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=MARK)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "brand").mkdir(exist_ok=True)
    app = render(1024, margin=0.0977, radius=0.2237)  # macOS grid: 824 px tile inside a 1024 canvas
    app.save(OUT / "app.png")
    app.save(OUT / "app.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    app.save(OUT / "app.icns")
    render(32).save(OUT / "brand" / "favicon-32.png")
    render(180, radius=0.2).save(OUT / "brand" / "apple-touch-icon.png")
    print(OUT)


if __name__ == "__main__":
    main()
