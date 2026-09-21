from __future__ import annotations
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain

import asyncio
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

home = tempfile.mkdtemp(prefix='ps-official-byok-')
os.environ['PERSONAL_SOFTWARE_HOME'] = home
os.environ['OPENAI_API_KEY'] = 'user-owned-openai-key'

seen = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def _body(self):
        n = int(self.headers.get('content-length', '0'))
        return json.loads(self.rfile.read(n) or b'{}')
    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)
    def do_POST(self):
        body = self._body()
        headers = dict(self.headers)
        seen.append((self.path, body, headers))
        if self.path == '/v1/auth/invite':
            return self._send(200, {'device_id': 'dev_test', 'token': 'official-device-token'})
        if self.path == '/v1/task':
            assert self.headers.get('Authorization') == 'Bearer official-device-token'
            assert body['task'] == 'resolve'
            return self._send(200, {'text': '{"strategy":"generate","reason":"hosted","generated_name":"Test","capabilities":[]}'})
        if self.path == '/openai/responses':
            assert self.headers.get('Authorization') == 'Bearer user-owned-openai-key'
            return self._send(200, {'output_text': '<!doctype html><html><body>generated locally</body></html>'})
        if self.path == '/v1/model-events':
            assert self.headers.get('Authorization') == 'Bearer official-device-token'
            assert body['task'] == 'generate_file'
            assert body['provider'] == 'byok:openai'
            assert body['success'] is True
            return self._send(200, {'ok': True})
        return self._send(404, {'detail': 'not found'})

srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]

from morfic.provider_config import ProviderSettings, save_provider_settings
from morfic.hosted import connect_invite
from morfic.llm import llm
from morfic.prompts import RESOLVE_SYSTEM, GENERATE_FILE_SYSTEM

async def main():
    save_provider_settings(ProviderSettings(
        provider='official',
        official_base_url=f'http://127.0.0.1:{port}',
        official_ai_mode='byok',
        official_byok_provider='openai',
        openai_model='test-openai',
        openai_base_url=f'http://127.0.0.1:{port}/openai',
    ))
    await connect_invite('tester')

    # High-value resolver/planning stays hosted.
    resolved = await llm.chat(RESOLVE_SYSTEM, '{"request":"hello","options":{"installed":[],"catalog":[]}}', json_mode=True)
    assert '"reason":"hosted"' in resolved

    # Source-heavy file generation uses the user's local key.
    generated = await llm.chat(GENERATE_FILE_SYSTEM, '{"path":"index.html"}', json_mode=False, max_output_tokens=2000)
    assert 'generated locally' in generated
    await asyncio.sleep(0.15)

    paths = [p for p, _, _ in seen]
    assert '/v1/task' in paths
    assert '/openai/responses' in paths
    assert '/v1/model-events' in paths

    # The user's provider secret must never be sent to our hosted service.
    hosted = [(p, b, h) for p, b, h in seen if p.startswith('/v1/')]
    serialized = json.dumps(hosted)
    assert 'user-owned-openai-key' not in serialized
    print('OFFICIAL BYOK PASS: hosted planning + local provider execution + safe telemetry')

asyncio.run(main())
srv.shutdown()
