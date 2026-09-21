import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import asyncio
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["PERSONAL_SOFTWARE_HOME"] = tempfile.mkdtemp(prefix="morfic-test-provider-timeout-")
os.environ["PERSONAL_SOFTWARE_LLM_TIMEOUT"] = "1"
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from morfic.llm import llm
from morfic.provider_config import ProviderSettings, save_provider_settings


class SlowHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        time.sleep(4)
        try:
            body = b'{"content":[{"type":"text","text":"too late"}]}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            pass


async def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    save_provider_settings(ProviderSettings(provider="anthropic", anthropic_model="test-model", anthropic_base_url=f"http://127.0.0.1:{port}"))
    started = time.monotonic()
    try:
        await llm.chat("system", "user")
        raise AssertionError("expected timeout")
    except RuntimeError as e:
        elapsed = time.monotonic() - started
        assert "did not finish within 1 seconds" in str(e), str(e)
        assert elapsed < 2.5, elapsed
        print(f"PROVIDER TIMEOUT PASS: hard wall-clock timeout fired in {elapsed:.2f}s")
    finally:
        server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
