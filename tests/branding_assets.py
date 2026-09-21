"""One brand: the same mark and palette in the app icon, the favicon and the in-app logo."""
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain

import os
import struct
import tempfile
from pathlib import Path

os.environ["MORFIC_HOME"] = tempfile.mkdtemp(prefix="morfic-test-brand-")
ROOT = Path(__file__).resolve().parent.parent

# ---- raster app icons exist, are RGBA, and have the right sizes
png = (ROOT / "build-assets" / "app.png").read_bytes()
assert png[:8] == b"\x89PNG\r\n\x1a\n"
width, height, depth, color_type = struct.unpack(">IIBB", png[16:26])
assert (width, height) == (1024, 1024) and color_type == 6, "app.png must be a 1024px RGBA image (transparent margin)"
assert (ROOT / "build-assets" / "app.ico").read_bytes()[:4] == b"\x00\x00\x01\x00"
assert (ROOT / "build-assets" / "app.icns").read_bytes()[:4] == b"icns"
for name, size in (("favicon-32.png", 32), ("apple-touch-icon.png", 180)):
    data = (ROOT / "build-assets" / "brand" / name).read_bytes()
    assert struct.unpack(">II", data[16:24]) == (size, size), name

# ---- favicon and in-app logo use the same mark and palette
svg = (ROOT / "morfic" / "static" / "favicon.svg").read_text()
assert "M5 31V11l16 10L37 11v20L21 21 5 31Z" in svg and "#17261e" in svg and "#bce68c" in svg
html = (ROOT / "morfic" / "static" / "index.html").read_text()
assert "M5 31V11l16 10L37 11v20L21 21 5 31Z" in html, "in-app logo must be the brand mark"
assert '<div class="mark">M</div>' not in html and 'href="/favicon.svg"' in html
assert "static/*.svg" in (ROOT / "pyproject.toml").read_text(), "favicon must ship in the package"

# ---- the favicon is served
from fastapi.testclient import TestClient
from morfic.app import app
with TestClient(app, base_url="http://127.0.0.1:8765") as c:
    r = c.get("/favicon.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml") and "<svg" in r.text

print("BRANDING PASS: one mark across app icon, favicon and in-app logo")
