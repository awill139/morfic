import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import asyncio
import os
import tempfile
from pathlib import Path

home = tempfile.mkdtemp(prefix="morfic-lifecycle-")
os.environ["PERSONAL_SOFTWARE_HOME"] = home

from fastapi.testclient import TestClient
from morfic.app import app
from morfic.builtins import ensure_builtin_apps
from morfic.db import list_apps

from morfic import __version__

with TestClient(app, base_url='http://127.0.0.1:8765') as c:
    assert c.get('/api/status').json()['version'] == __version__
    root = c.get('/').text
    assert '<title>Morfic</title>' in root
    apps = c.get('/api/apps').json()
    assert apps
    app_id = apps[0]['id']
    shell = c.get(f'/apps/{app_id}').text
    assert 'Archive' in shell and 'Delete' in shell
    r = c.post(f'/api/apps/{app_id}/archive')
    assert r.status_code == 200 and r.json()['status'] == 'archived'
    r = c.post(f'/api/apps/{app_id}/restore')
    assert r.status_code == 200 and r.json()['status'] == 'running'
    r = c.delete(f'/api/apps/{app_id}')
    assert r.status_code == 200
    ensure_builtin_apps()
    assert not any(x.source_type == 'builtin' and x.name == 'Scientific Calculator' for x in list_apps())
print('LIFECYCLE PASS: Morfic branding + archive/restore/delete + builtin tombstone')
