import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import asyncio
import os
import tempfile

os.environ['PERSONAL_SOFTWARE_HOME'] = tempfile.mkdtemp(prefix='morfic-jellyfin-')

import morfic.orchestrator as orch
from morfic.db import init_db, update_app

captured = {}
async def fake_deploy(app_id, repo_url, intent, plan, ref=None):
    captured['repo_url'] = repo_url
    captured['plan'] = plan
    update_app(app_id, status='running', local_url='http://127.0.0.1:8096')

orch.deploy_github = fake_deploy

async def main():
    init_db()
    res, app = await orch.request_catalog_software('jellyfin')
    await asyncio.sleep(.05)
    assert res.strategy == 'catalog'
    assert captured['plan'].container_image == 'jellyfin/jellyfin:latest'
    assert captured['plan'].port == 8096
    assert captured['plan'].media_mounts is True
    print('JELLYFIN DIRECT PASS: marketplace uses deterministic recipe without LLM planning')

asyncio.run(main())
