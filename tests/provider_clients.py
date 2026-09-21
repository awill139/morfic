from __future__ import annotations
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain

import asyncio
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TEST_HOME = Path(tempfile.mkdtemp(prefix="morfic-test-v06-provider-"))
os.environ["PERSONAL_SOFTWARE_HOME"] = str(TEST_HOME)
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"

from morfic.llm import llm
from morfic.provider_config import ProviderSettings, save_provider_settings

seen = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        seen.append((self.path, dict(self.headers), body))
        if self.path == "/v1/responses":
            assert self.headers.get("Authorization") == "Bearer test-openai-key"
            assert body["model"] == "test-openai-model"
            assert body["instructions"] == "system"
            assert body.get("max_output_tokens") == 4321
            response = {"output_text": '{"provider":"openai"}'}
        elif self.path == "/v1/messages":
            assert self.headers.get("x-api-key") == "test-anthropic-key"
            assert self.headers.get("anthropic-version") == "2023-06-01"
            assert body["model"] == "test-anthropic-model"
            assert body["system"].startswith("system")
            assert body.get("max_tokens") == 4321
            response = {"content":[{"type":"text","text":'{"provider":"anthropic"}'}]}
        else:
            self.send_response(404); self.end_headers(); return
        data = json.dumps(response).encode()
        self.send_response(200); self.send_header("content-type","application/json"); self.send_header("content-length",str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, format, *args):
        pass


async def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/v1"
    try:
        save_provider_settings(ProviderSettings(provider="openai", openai_model="test-openai-model", openai_base_url=base, anthropic_model="test-anthropic-model", anthropic_base_url=base))
        r = await llm.chat("system", "user", json_mode=True, max_output_tokens=4321)
        assert json.loads(r)["provider"] == "openai"
        save_provider_settings(ProviderSettings(provider="anthropic", openai_model="test-openai-model", openai_base_url=base, anthropic_model="test-anthropic-model", anthropic_base_url=base))
        r = await llm.chat("system", "user", json_mode=True, max_output_tokens=4321)
        assert json.loads(r)["provider"] == "anthropic"
        assert len(seen) == 2
        print("PROVIDER PASS: OpenAI Responses API request shape works")
        print("PROVIDER PASS: Anthropic Messages API request shape works")
    finally:
        server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
