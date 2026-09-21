from __future__ import annotations
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import json, os, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

home=tempfile.mkdtemp(prefix='ps-hosted-test-')
os.environ['PERSONAL_SOFTWARE_HOME']=home

seen=[]
class H(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def _body(self):
        n=int(self.headers.get('content-length','0')); return json.loads(self.rfile.read(n) or b'{}')
    def _send(self,code,obj):
        b=json.dumps(obj).encode(); self.send_response(code); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_POST(self):
        body=self._body(); seen.append((self.path,body,dict(self.headers)))
        if self.path=='/v1/auth/invite': return self._send(200,{'device_id':'dev_test','token':'token-test'})
        if self.path=='/v1/task':
            assert self.headers.get('Authorization')=='Bearer token-test'
            assert body['task']=='resolve'
            return self._send(200,{'text':'{"strategy":"generate","reason":"test","generated_name":"Test","capabilities":[]}','provider':'fake','model':'fake'})
        if self.path=='/v1/events': return self._send(200,{'ok':True})
        return self._send(404,{'detail':'not found'})

srv=ThreadingHTTPServer(('127.0.0.1',0),H); threading.Thread(target=srv.serve_forever,daemon=True).start(); port=srv.server_address[1]

from morfic.provider_config import ProviderSettings, save_provider_settings
from morfic.hosted import connect_invite, emit_event
from morfic.llm import llm
from morfic.prompts import RESOLVE_SYSTEM
import asyncio

async def main():
    save_provider_settings(ProviderSettings(provider='official',official_base_url=f'http://127.0.0.1:{port}'))
    await connect_invite('tester')
    text=await llm.chat(RESOLVE_SYSTEM,'{"request":"hello","options":{"installed":[],"catalog":[]}}',json_mode=True,max_output_tokens=500)
    assert '"strategy":"generate"' in text
    await emit_event('unit_test',strategy='generate',success=True)
    assert any(p=='/v1/task' for p,_,_ in seen)
    assert any(p=='/v1/events' for p,_,_ in seen)
    print('HOSTED CLIENT PASS: invite + task routing + telemetry')

asyncio.run(main()); srv.shutdown()
