"""Regression tests for the local-only request guard (DNS rebinding, cross-origin writes, content origin)."""
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import json
import os
import tempfile
from pathlib import Path

home = tempfile.mkdtemp(prefix="morfic-test-security-")
os.environ["MORFIC_HOME"] = home

from fastapi.testclient import TestClient
from morfic.app import app

CONTROL = "http://127.0.0.1:8765"
provider_json = Path(home) / "provider.json"
payload = {"provider": "official", "official_base_url": "https://evil.example"}


def config_url():
    return json.loads(provider_json.read_text()).get("official_base_url") if provider_json.exists() else None


with TestClient(app, base_url=CONTROL) as c:
    # Normal same-origin use keeps working.
    assert c.get("/api/status").status_code == 200
    assert c.get("/").status_code == 200

    # DNS rebinding: an attacker-controlled name pointing at 127.0.0.1 is refused everywhere.
    for path in ("/", "/api/status", "/api/provider-settings", "/api/apps"):
        r = c.get(path, headers={"Host": "evil.example:8765"})
        assert r.status_code == 403, (path, r.status_code)
    r = c.post("/api/provider-settings", json=payload, headers={"Host": "evil.example:8765"})
    assert r.status_code == 403 and config_url() != "https://evil.example"

    # IPv6 loopback is a legitimate control host.
    assert c.get("/api/status", headers={"Host": "[::1]:8765"}).status_code == 200

    # Cross-origin writes are refused, including from the generated-content origin and opaque origins.
    for origin in ("https://evil.example", "http://localhost:8765", "null", "http://127.0.0.1:9999"):
        r = c.post("/api/provider-settings", json=payload, headers={"Origin": origin})
        assert r.status_code == 403, (origin, r.status_code)
        r = c.delete("/api/apps/1", headers={"Origin": origin})
        assert r.status_code == 403, (origin, r.status_code)
    assert config_url() != "https://evil.example"

    # Fetch-metadata fallback for clients that omit Origin.
    r = c.post("/api/provider-settings", json=payload, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403

    # Same-origin browser writes (Origin equals Host) and non-browser clients (no Origin) are allowed.
    r = c.post("/api/provider-settings", json={"provider": "openai"}, headers={"Origin": CONTROL})
    assert r.status_code == 200, r.text
    r = c.post("/api/provider-settings", json={"provider": "openai"})
    assert r.status_code == 200, r.text

    # Generated content is served from the localhost origin, never the control origin.
    apps = c.get("/api/apps").json()
    generated = next(a for a in apps if a.get("local_url", "").startswith("/content/"))
    url = generated["local_url"]
    r = c.get(url, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"].startswith("http://localhost:8765/content/"), (r.status_code, r.headers)
    r = c.get(url, headers={"Host": "localhost:8765"}, follow_redirects=False)
    assert r.status_code == 200, r.status_code

    # ...and from that origin the control plane is unreachable, so generated code cannot drive it.
    for path in ("/", "/api/status", "/api/provider-settings", "/api/apps", f"/apps/{generated['id']}"):
        r = c.get(path, headers={"Host": "localhost:8765"})
        assert r.status_code == 403, (path, r.status_code)
    r = c.post("/api/provider-settings", json=payload, headers={"Host": "localhost:8765", "Origin": "http://localhost:8765"})
    assert r.status_code == 403 and config_url() != "https://evil.example"

print("SECURITY GUARD PASS: host allow-list, same-origin writes, content-origin isolation")
