"""Usage-data sharing: default on, fully switchable off; token counts and redacted excerpts; community mode never phones home."""
from __future__ import annotations
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain

import asyncio
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

home = tempfile.mkdtemp(prefix="morfic-test-optout-")
os.environ["MORFIC_HOME"] = home
os.environ["OPENAI_API_KEY"] = "user-owned-openai-key"

SECRET_PROMPT = (
    'Build me a settings page.\nkey = sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789\n'
    'DB_PASSWORD="hunter2hunter2"\nAuthorization: Bearer abcdef0123456789abcdef0123456789\n'
    'postgres://admin:s3cretpw@db.internal:5432/app\n-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----'
)
SECRETS = ["sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789", "hunter2hunter2", "abcdef0123456789abcdef0123456789", "s3cretpw", "MIIabc"]
seen: list[tuple[str, dict]] = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", "0"))) or b"{}")
        seen.append((self.path, body))
        if self.path == "/v1/auth/invite": return self._send(200, {"device_id": "dev_t", "token": "device-token-not-real"})
        if self.path == "/v1/task": return self._send(200, {"text": '{"strategy":"generate","reason":"hosted","generated_name":"T","capabilities":[]}'})
        if self.path == "/openai/responses":
            return self._send(200, {"output_text": "<html>done password=hunter2hunter2</html>", "usage": {"input_tokens": 123, "output_tokens": 45}})
        if self.path in ("/v1/model-events", "/v1/events"): return self._send(200, {"ok": True})
        return self._send(404, {})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]

from fastapi.testclient import TestClient
from morfic.app import app
from morfic.hosted import connect_invite, emit_event
from morfic.llm import llm
from morfic.prompts import GENERATE_FILE_SYSTEM, RESOLVE_SYSTEM
from morfic.provider_config import ProviderSettings, load_provider_settings, save_provider_settings
from morfic.redact import MAX_EXCERPT_CHARS, excerpt, redact_secrets

# ---- redaction ------------------------------------------------------------------------------
cleaned = redact_secrets(SECRET_PROMPT)
for s in SECRETS:
    assert s not in cleaned, f"secret survived redaction: {s}"
assert "Build me a settings page." in cleaned and "[REDACTED" in cleaned
assert "sk-openai" not in redact_secrets("model name gpt-5 and a normal sentence") and redact_secrets("plain text") == "plain text"
long = "a" * (MAX_EXCERPT_CHARS - 5) + "sk-" + "b" * 40 + "tail" * 100
out = excerpt(long)
assert "b" * 40 not in out and len(out) <= MAX_EXCERPT_CHARS + 60 and "truncated" in out  # redact before truncating
assert excerpt(None) == "" and excerpt("") == ""

# Redaction must stay linear on hostile / minified input (it runs on prompts of up to hundreds of KB).
import time
for name, blob in {
    "alnum run": "a" * 300_000,
    "base64-ish": ("QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo" * 12_000),
    "many keywords": "password " * 50_000,
    "equals run": "=" * 300_000,
    "scheme-ish": ("abc" * 100_000) + "://",
    "dashes": "-" * 300_000,
    "keyword run": "auth" * 75_000,
    "keyword then spaces": "secret" + " " * 300_000 + "x",
}.items():
    started = time.perf_counter()
    redact_secrets(blob)
    took = time.perf_counter() - started
    assert took < 1.5, f"redaction of {name} took {took:.1f}s"

# ---- defaults -------------------------------------------------------------------------------
d = ProviderSettings()
assert d.share_usage_data is True and d.diagnostic_consent is True


def base(**kw):
    return ProviderSettings(provider="official", official_base_url=f"http://127.0.0.1:{port}", official_ai_mode="byok",
                            official_byok_provider="openai", openai_model="m", openai_base_url=f"http://127.0.0.1:{port}/openai", **kw)


def hits(path):
    return [b for p, b in seen if p == path]


async def run_generation():
    await llm.chat(GENERATE_FILE_SYSTEM, SECRET_PROMPT, json_mode=False, max_output_tokens=500)
    await emit_event("probe_event", stage="probe")
    await asyncio.sleep(0.3)


async def main():
    # 1. Default: everything on. Tokens and redacted excerpts reach the backend; secrets do not.
    save_provider_settings(base())
    await connect_invite("tester")
    await run_generation()
    ev = hits("/v1/model-events")
    assert len(ev) == 1 and hits("/v1/events"), (ev, hits("/v1/events"))
    e = ev[0]
    assert e["input_tokens"] == 123 and e["output_tokens"] == 45 and e["success"] is True
    assert "Build me a settings page." in e["request_excerpt"] and "done" in e["response_excerpt"]
    wire = json.dumps([b for p, b in seen if p.startswith("/v1/")])
    for s in SECRETS + ["user-owned-openai-key"]:
        assert s not in wire, f"{s} leaked to the backend"

    # 2. Content off, sharing on: counts and timings only.
    seen.clear()
    save_provider_settings(base(diagnostic_consent=False))
    await run_generation()
    e = hits("/v1/model-events")[0]
    assert e["input_tokens"] == 123 and "request_excerpt" not in e and "response_excerpt" not in e
    assert hits("/v1/events")

    # 3. Sharing off: no telemetry at all. The AI call itself still works; nothing may retain content.
    seen.clear()
    save_provider_settings(base(share_usage_data=False, diagnostic_consent=True))
    await run_generation()
    resolved = await llm.chat(RESOLVE_SYSTEM, '{"request":"hi","options":{"installed":[],"catalog":[]}}', json_mode=True)
    assert '"reason":"hosted"' in resolved
    assert hits("/v1/model-events") == [] and hits("/v1/events") == [], "telemetry sent while sharing is off"
    task_bodies = hits("/v1/task")
    assert task_bodies and all(b["diagnostic_consent"] is False for b in task_bodies)

    # 4. Community mode never contacts the backend, whatever the flags say.
    seen.clear()
    save_provider_settings(ProviderSettings(provider="openai", official_base_url=f"http://127.0.0.1:{port}", openai_model="m",
                                            openai_base_url=f"http://127.0.0.1:{port}/openai"))
    await llm.chat(GENERATE_FILE_SYSTEM, "hello", json_mode=False)
    await emit_event("probe_event")
    await asyncio.sleep(0.2)
    assert [p for p, _ in seen if p.startswith("/v1/")] == []

asyncio.run(main())

# ---- settings API ----------------------------------------------------------------------------
with TestClient(app, base_url="http://127.0.0.1:8765") as c:
    got = c.get("/api/provider-settings").json()
    assert "share_usage_data" in got and "diagnostic_consent" in got
    r = c.post("/api/provider-settings", json={"provider": "official", "share_usage_data": False, "diagnostic_consent": False})
    assert r.status_code == 200 and r.json()["share_usage_data"] is False and r.json()["diagnostic_consent"] is False
    assert load_provider_settings().share_usage_data is False
    # Omitting the fields must not silently re-enable sharing.
    r = c.post("/api/provider-settings", json={"provider": "official"})
    assert r.json()["share_usage_data"] is False and r.json()["diagnostic_consent"] is False
    r = c.post("/api/provider-settings", json={"provider": "official", "share_usage_data": True})
    assert r.json()["share_usage_data"] is True and r.json()["diagnostic_consent"] is False

# The mock server thread is a daemon; shutdown() can block on pooled keep-alive connections.
print("TELEMETRY OPT-OUT PASS: default on; off sends nothing; tokens + redacted excerpts; community mode silent; API keeps consent")
