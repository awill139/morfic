from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / "build-assets"
out.mkdir(parents=True, exist_ok=True)

size = 1024
img = Image.new("RGBA", (size, size), (245, 245, 242, 255))
d = ImageDraw.Draw(img)
# Minimal app glyph: a rounded dark tile with a white command sparkle.
margin = 104
d.rounded_rectangle((margin, margin, size-margin, size-margin), radius=190, fill=(22, 22, 22, 255))
# Bracket/command motif.
w = 56
x1, x2 = 315, 709
y1, y2 = 315, 709
d.line((x1+95, y1, x1, 512, x1+95, y2), fill="white", width=w, joint="curve")
d.line((x2-95, y1, x2, 512, x2-95, y2), fill="white", width=w, joint="curve")
d.ellipse((472, 472, 552, 552), fill=(255, 255, 255, 255))
img.save(out / "app.png")
img.save(out / "app.ico", sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
try:
    img.save(out / "app.icns")
except Exception:
    pass
print(out)
