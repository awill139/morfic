"""A device token the service no longer recognises is dropped with a clear message, and re-entering the invite code recovers."""
from __future__ import annotations
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain

import asyncio
import json
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["MORFIC_HOME"] = tempfile.mkdtemp(prefix="morfic-test-reconnect-")
valid_tokens: set[str] = set()
issued = 0


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        global issued
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))) or b"{}")
        if self.path == "/v1/auth/invite":
            if body.get("invite_code") not in ("tester1", "tester2"): return self._send(403, {"detail": "Invalid invite code"})
            issued += 1; tok = f"token-{issued}"; valid_tokens.add(tok)
            return self._send(200, {"device_id": f"dev_{issued}", "token": tok})
        if self.path == "/v1/task":
            if self.headers.get("Authorization", "")[7:] not in valid_tokens: return self._send(401, {"detail": "Invalid device token"})
            return self._send(200, {"text": '{"ok":true}'})
        return self._send(404, {})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]

from fastapi.testclient import TestClient
from morfic.app import app
from morfic.hosted import connect_invite, hosted_task
from morfic.provider_config import ProviderSettings, get_secret, has_secret, save_provider_settings

save_provider_settings(ProviderSettings(provider="official", official_base_url=f"http://127.0.0.1:{port}"))


async def main():
    await connect_invite("tester1")
    assert get_secret("official_token") == "token-1"
    assert await hosted_task("resolve", "{}", True) == '{"ok":true}'

    valid_tokens.clear()  # the service loses its database, as after a redeploy without a volume
    try:
        await hosted_task("resolve", "{}", True)
    except RuntimeError as e:
        assert "invite code" in str(e) and "AI Settings" in str(e), e
    else:
        raise AssertionError("a rejected token must raise")
    assert not has_secret("official_token"), "dead token must be forgotten so Settings shows 'Not connected'"

    # Other 4xx errors are reported as-is and never delete a token.
    await connect_invite("tester2")
    assert has_secret("official_token")
    try:
        await connect_invite("bogus")
    except RuntimeError as e:
        assert "Invalid invite code" in str(e)
    assert has_secret("official_token")

asyncio.run(main())

# The settings API reflects the state, and reconnecting replaces the token.
with TestClient(app, base_url="http://127.0.0.1:8765") as c:
    assert c.get("/api/provider-settings").json()["official_has_token"] is True
    old = get_secret("official_token")
    r = c.post("/api/orchestrator/connect", json={"invite_code": "tester1", "device_label": "x"})
    assert r.status_code == 200 and get_secret("official_token") != old
    r = c.post("/api/orchestrator/connect", json={"invite_code": "nope", "device_label": "x"})
    assert r.status_code == 400 and "Invalid invite code" in r.json()["detail"]

# Settings UI contract (static checks on the page's script; behaviour is exercised in a browser during release checks).
html = (Path(__file__).resolve().parent.parent / "morfic" / "static" / "index.html").read_text()
save = html[html.index("async function saveSettings("):html.index("async function testSelected(")]
test = html[html.index("async function testSelected("):html.index("function openSettings(")]
assert "closeAfter" in save and "if(closeAfter)setTimeout(closeSettings" in save, "Save must close the dialog only when asked to"
assert "saveSettings(false)" in test and "closeSettings" not in test, "Test connection must never close the dialog"
assert "code||!j.official_has_token" in save, "a typed invite code must be used even when a token is already saved"
assert html.count("setTimeout(closeSettings") == 1

print("RECONNECT PASS: dead token cleared with guidance; invite code replaces token; test never closes settings")
