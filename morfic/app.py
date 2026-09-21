from __future__ import annotations

import html
import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from .config import settings
from .builtins import ensure_builtin_apps
from .llm import llm
from .provider_config import ProviderSettings, has_secret, load_provider_settings, save_provider_settings, set_secret
from .hosted import connect_invite
from .db import get_app, init_db, list_apps, list_logs, list_versions, recover_stale_modifications
from .deployer import container_runtime, invoke_cli
from .orchestrator import archive_app, delete_app, request_catalog_software, request_software, restore_app
from .operations import cancel_modification, get_latest_operation, start_modification
from .catalog import load_catalog
from . import __version__
from .security import CONTENT_HOST, LocalOnlyGuard, host_name, is_control_host

app = FastAPI(title="Morfic Runtime", version=__version__)
app.add_middleware(LocalOnlyGuard)


@app.on_event("startup")
def startup():
    init_db()
    recover_stale_modifications()
    ensure_builtin_apps()


class IntentRequest(BaseModel):
    text: str


class ModifyRequest(BaseModel):
    text: str


class InvokeRequest(BaseModel):
    values: dict[str, str] = {}
    args: str = ""


class ProviderConfigRequest(BaseModel):
    provider: str = ""
    official_base_url: str = "http://127.0.0.1:8770"
    # None keeps the value already saved, so API clients that omit a field never change consent by accident.
    share_usage_data: bool | None = None
    diagnostic_consent: bool | None = None
    official_ai_mode: str = "managed"
    official_byok_provider: str = "anthropic"
    openai_model: str = "gpt-5"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    anthropic_api_key: str = ""


class ProviderTestRequest(BaseModel):
    provider: str


class OrchestratorConnectRequest(BaseModel):
    invite_code: str
    device_label: str = ""


@app.get("/")
def root():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


def _provider_ready(cfg: ProviderSettings) -> bool:
    if cfg.provider == "official":
        if not has_secret("official_token"):
            return False
        if cfg.official_ai_mode == "byok":
            if cfg.official_byok_provider not in {"openai", "anthropic"}:
                return False
            return has_secret(f"{cfg.official_byok_provider}_api_key")
        return True
    if cfg.provider in {"openai", "anthropic"}:
        return has_secret(f"{cfg.provider}_api_key")
    return False


@app.get("/api/status")
def status():
    cfg = load_provider_settings()
    return {
        "version": __version__,
        "home": str(settings.home),
        "provider": cfg.provider or None,
        "provider_configured": _provider_ready(cfg),
        "container_runtime": container_runtime(),
    }


@app.get("/api/provider-settings")
def provider_settings():
    cfg = load_provider_settings()
    return {
        "provider": cfg.provider,
        "official_base_url": cfg.official_base_url,
        "official_has_token": has_secret("official_token"),
        "share_usage_data": cfg.share_usage_data,
        "diagnostic_consent": cfg.diagnostic_consent,
        "official_ai_mode": cfg.official_ai_mode,
        "official_byok_provider": cfg.official_byok_provider,
        "openai_model": cfg.openai_model,
        "openai_base_url": cfg.openai_base_url,
        "openai_has_key": has_secret("openai_api_key"),
        "anthropic_model": cfg.anthropic_model,
        "anthropic_base_url": cfg.anthropic_base_url,
        "anthropic_has_key": has_secret("anthropic_api_key"),
    }


@app.post("/api/provider-settings")
def update_provider_settings(req: ProviderConfigRequest):
    provider = req.provider.strip().lower()
    if provider not in {"", "official", "openai", "anthropic"}:
        raise HTTPException(400, "Provider must be Official, OpenAI, or Anthropic.")
    official_ai_mode = req.official_ai_mode.strip().lower()
    if official_ai_mode not in {"managed", "byok"}:
        raise HTTPException(400, "Official AI usage must be Managed or BYOK.")
    official_byok_provider = req.official_byok_provider.strip().lower()
    if official_byok_provider not in {"openai", "anthropic"}:
        raise HTTPException(400, "Official BYOK provider must be OpenAI or Anthropic.")
    current = load_provider_settings()
    cfg = ProviderSettings(
        provider=provider,
        official_base_url=req.official_base_url.strip().rstrip("/") or "http://127.0.0.1:8770",
        share_usage_data=current.share_usage_data if req.share_usage_data is None else bool(req.share_usage_data),
        diagnostic_consent=current.diagnostic_consent if req.diagnostic_consent is None else bool(req.diagnostic_consent),
        official_ai_mode=official_ai_mode,
        official_byok_provider=official_byok_provider,
        openai_model=req.openai_model.strip() or "gpt-5",
        openai_base_url=req.openai_base_url.strip().rstrip("/") or "https://api.openai.com/v1",
        anthropic_model=req.anthropic_model.strip() or "claude-sonnet-4-6",
        anthropic_base_url=req.anthropic_base_url.strip().rstrip("/") or "https://api.anthropic.com/v1",
    )
    save_provider_settings(cfg)
    if req.openai_api_key.strip():
        set_secret("openai_api_key", req.openai_api_key)
    if req.anthropic_api_key.strip():
        set_secret("anthropic_api_key", req.anthropic_api_key)
    return provider_settings()


@app.post("/api/orchestrator/connect")
async def connect_orchestrator(req: OrchestratorConnectRequest):
    try:
        return await connect_invite(req.invite_code.strip(), req.device_label.strip())
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/provider-settings/test")
async def test_provider(req: ProviderTestRequest):
    try:
        result = await llm.test_connection(req.provider.strip().lower())
        return {"ok": True, "response": result[:500]}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/intent")
async def intent(req: IntentRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Tell me what software you need.")
    try:
        resolution, local_app = await request_software(text)
        return {"resolution": resolution.model_dump(), "app": local_app.model_dump()}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/catalog")
def catalog():
    installed = {a.source_url: a for a in list_apps() if a.source_url and a.status not in {"failed", "deleted"}}
    out = []
    for entry in load_catalog():
        data = entry.model_dump()
        match = installed.get(entry.repo_url)
        data["installed_app_id"] = match.id if match else None
        data["installed_status"] = match.status if match else None
        data["interface"] = "CLI + AI interface" if "cli" in entry.notes.lower() else "Existing interface"
        data["is_demo"] = entry.id.startswith("demo-")
        out.append(data)
    return out


@app.post("/api/catalog/{catalog_id}/install")
async def install_catalog(catalog_id: str):
    entry = next((x for x in load_catalog() if x.id == catalog_id), None)
    if not entry:
        raise HTTPException(404, "Catalog item not found")
    # Known-good curated deployment plans do not require an AI provider simply to install.
    # AI is only required when Morfic must inspect/adapt an unplanned repository.
    if entry.deployment_plan is None:
        cfg = load_provider_settings()
        if not _provider_ready(cfg):
            raise HTTPException(400, "Connect the Official service or add an OpenAI/Anthropic key so Morfic can inspect and adapt this repository.")
    try:
        resolution, local_app = await request_catalog_software(catalog_id)
        return {"resolution": resolution.model_dump(), "app": local_app.model_dump()}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/apps")
def apps():
    return [x.model_dump() for x in list_apps()]


@app.get("/api/apps/{app_id}")
def one_app(app_id: int):
    local_app = get_app(app_id)
    if not local_app:
        raise HTTPException(404, "App not found")
    return local_app.model_dump()


@app.get("/api/apps/{app_id}/logs")
def logs(app_id: int):
    if not get_app(app_id):
        raise HTTPException(404, "App not found")
    return list_logs(app_id)


@app.get("/api/apps/{app_id}/versions")
def versions(app_id: int):
    if not get_app(app_id):
        raise HTTPException(404, "App not found")
    return list_versions(app_id)


@app.post("/api/apps/{app_id}/modify")
async def modify(app_id: int, req: ModifyRequest):
    if not get_app(app_id):
        raise HTTPException(404, "App not found")
    try:
        text = req.text.strip()
        if not text:
            raise RuntimeError("Describe the change you want.")
        op = start_modification(app_id, text)
        return {"ok": True, "operation_id": op.id, "status": op.status}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/apps/{app_id}/operation")
def app_operation(app_id: int):
    if not get_app(app_id):
        raise HTTPException(404, "App not found")
    return get_latest_operation(app_id) or {"status": "idle"}


@app.post("/api/apps/{app_id}/modify/cancel")
async def cancel_modify(app_id: int):
    if not get_app(app_id):
        raise HTTPException(404, "App not found")
    return await cancel_modification(app_id)


@app.post("/api/apps/{app_id}/archive")
async def archive(app_id: int):
    try:
        return (await archive_app(app_id)).model_dump()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/apps/{app_id}/restore")
async def restore(app_id: int):
    try:
        restored = await restore_app(app_id)
        return restored.model_dump()
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/apps/{app_id}")
async def remove_app(app_id: int):
    try:
        await delete_app(app_id)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/apps/{app_id}/invoke")
async def invoke(app_id: int, req: InvokeRequest):
    try:
        return await invoke_cli(app_id, req.values, req.args)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/apps/{app_id}", response_class=HTMLResponse)
def app_shell(app_id: int):
    local_app = get_app(app_id)
    if not local_app:
        raise HTTPException(404, "App not found")
    title = html.escape(local_app.name)
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title>
<style>
*{{box-sizing:border-box}}html,body{{margin:0;height:100%;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;background:#eef0f3;color:#17191c}}body{{overflow:hidden}}
.bar{{height:54px;display:flex;align-items:center;gap:12px;padding:0 15px;background:rgba(255,255,255,.92);border-bottom:1px solid #dfe2e6;backdrop-filter:blur(14px)}}.back{{width:34px;height:34px;border:0;background:#f0f2f5;border-radius:10px;cursor:pointer;font-size:18px}}.title{{font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.spacer{{flex:1}}.meta{{font-size:12px;color:#747a85}}.external{{border:0;background:#f0f2f5;border-radius:10px;padding:9px 12px;cursor:pointer}}.life{{border:0;background:#f0f2f5;border-radius:10px;padding:9px 11px;cursor:pointer;color:#555}}.danger{{color:#b42318;background:#fff0ee}}
.stage{{height:calc(100% - 54px);position:relative;background:white}}iframe{{border:0;width:100%;height:100%;background:white}}.state{{height:100%;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px;color:#666}}.spinner{{width:30px;height:30px;border:3px solid #ddd;border-top-color:#222;border-radius:50%;animation:spin .8s linear infinite}}@keyframes spin{{to{{transform:rotate(360deg)}}}}
.ai{{position:absolute;right:22px;bottom:22px;width:48px;height:48px;border-radius:50%;border:0;background:#111;color:white;box-shadow:0 10px 30px #0003;cursor:pointer;font-weight:800;z-index:10}}.panel{{display:none;position:absolute;right:22px;bottom:80px;width:min(430px,calc(100% - 32px));background:white;border:1px solid #dadde2;border-radius:18px;padding:15px;box-shadow:0 24px 70px #0003;z-index:11}}.panel.open{{display:block}}.panel strong{{font-size:14px}}.panel textarea{{width:100%;min-height:90px;resize:vertical;border:1px solid #d7dbe0;border-radius:12px;margin:10px 0;padding:12px;font:14px system-ui;outline:none}}.actions{{display:flex;justify-content:flex-end;gap:8px}}.actions button{{border:0;border-radius:10px;padding:9px 12px;cursor:pointer}}.go{{background:#111;color:white}}.msg{{font-size:12px;color:#6e7480;min-height:18px;margin-top:7px}}
</style></head><body><header class='bar'><button class='back' onclick="location.href='/'">‹</button><div class='title'>{title}</div><div class='spacer'></div><span class='meta' id='version'>v{local_app.version}</span><button class='life' id='archiveBtn' onclick='toggleArchive()'>Archive</button><button class='life danger' id='deleteBtn' onclick='deleteCurrent()'>Delete</button><button class='external' id='external' onclick='openExternal()'>Open ↗</button></header>
<main class='stage' id='stage'><div class='state'><div class='spinner'></div><div id='stateText'>Materializing software…</div></div><button class='ai' id='ai' onclick='toggleAI()' title='Change this app'>AI</button><section class='panel' id='panel'><strong>Change this app</strong><textarea id='change' placeholder='e.g. Add graphing, make the buttons larger, save my history…'></textarea><div class='actions'><button onclick='toggleAI()'>Cancel</button><button class='go' onclick='modify()'>Make change</button></div><div class='msg' id='msg'></div></section></main>
<script>
const appId={app_id}; let appData=null, frame=null;
async function refresh(){{const r=await fetch('/api/apps/'+appId);if(!r.ok){{location.href='/';return}}appData=await r.json();document.getElementById('version').textContent='v'+appData.version;const ab=document.getElementById('archiveBtn');if(ab)ab.textContent=appData.status==='archived'?'Restore':'Archive';render();}}
function resolveURL(u){{if(!u)return null;if(u.startsWith('/'))return u;return u}}
function render(){{const stage=document.getElementById('stage');const keepAI=`<button class="ai" id="ai" onclick="toggleAI()" title="Change this app">AI</button><section class="panel" id="panel"><strong>Change this app</strong><textarea id="change" placeholder="e.g. Add graphing, make the buttons larger, save my history…"></textarea><div class="actions"><button onclick="toggleAI()">Cancel</button><button class="go" onclick="modify()">Make change</button></div><div class="msg" id="msg"></div></section>`;
 if(appData.status==='running'&&appData.local_url){{const u=resolveURL(appData.local_url)+(appData.local_url.includes('?')?'&':'?')+'v='+appData.version;stage.innerHTML=`<iframe id="frame" src="${{u}}"></iframe>`+keepAI;frame=document.getElementById('frame');document.getElementById('external').style.display='block';}}
 else if(appData.status==='archived'){{document.getElementById('external').style.display='none';stage.innerHTML=`<div class="state"><b>Archived</b><div>This app and its data are preserved locally.</div><button onclick="toggleArchive()">Restore app</button></div>`;}}
 else if(appData.status==='failed'){{stage.innerHTML=`<div class="state"><b>Couldn't materialize this yet.</b><div style="max-width:650px;text-align:center">${{esc(appData.last_error||'Unknown error')}}</div><button onclick="location.href='/'">Back</button></div>`+keepAI;}}
 else if(appData.status==='modifying'){{stage.innerHTML=`<div class="state"><div class="spinner"></div><div>Making your change…</div><button id="cancelModify" onclick="cancelModify()">Cancel change</button></div>`;setTimeout(refresh,1200)}}
 else {{stage.innerHTML=`<div class="state"><div class="spinner"></div><div>${{esc(label(appData.status))}}</div></div>`+keepAI;setTimeout(refresh,1200)}}
}}
function label(s){{return ({{queued:'Finding the best implementation…',cloning:'Getting the open-source software…',planning:'Figuring out how it works…',installing:'Setting it up locally…',repairing:'Fixing an issue…',materializing:'Building your app…',modifying:'Making your change…'}})[s]||'Working…'}}
function esc(s){{return String(s).replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}}[c]))}}
function toggleAI(){{const p=document.getElementById('panel');if(p)p.classList.toggle('open')}}
async function modify(){{const t=document.getElementById('change').value.trim(),m=document.getElementById('msg');if(!t)return;m.textContent='Starting change…';const r=await fetch('/api/apps/'+appId+'/modify',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{text:t}})}});const j=await r.json();if(!r.ok){{m.textContent=j.detail||'Change failed';return}}document.getElementById('change').value='';m.textContent='Changing the app…';toggleAI();refresh();watchOperation(j.operation_id)}}
async function watchOperation(opId){{for(;;){{await new Promise(r=>setTimeout(r,1100));const r=await fetch('/api/apps/'+appId+'/operation');const op=await r.json();if(op.id&&op.id!==opId)continue;if(op.status==='succeeded'){{await refresh();return}}if(op.status==='failed'||op.status==='cancelled'){{await refresh();setTimeout(()=>alert(op.error||'The change did not complete.'),50);return}}}}}}
async function cancelModify(){{const b=document.getElementById('cancelModify');if(b)b.disabled=true;await fetch('/api/apps/'+appId+'/modify/cancel',{{method:'POST'}});await refresh()}}
async function toggleArchive(){{if(!appData)return;const restore=appData.status==='archived';const r=await fetch('/api/apps/'+appId+'/'+(restore?'restore':'archive'),{{method:'POST'}});const j=await r.json();if(!r.ok){{alert(j.detail||'Could not '+(restore?'restore':'archive')+' app');return}}await refresh();}}
async function deleteCurrent(){{if(!appData)return;if(!confirm('Permanently delete '+appData.name+' and its local app data? This cannot be undone.'))return;const r=await fetch('/api/apps/'+appId,{{method:'DELETE'}});const j=await r.json();if(!r.ok){{alert(j.detail||'Could not delete app');return}}location.href='/';}}
function openExternal(){{if(appData&&appData.local_url)window.open(resolveURL(appData.local_url),'_blank')}}
refresh();
</script></body></html>"""


def _to_content_origin(request: Request):
    """Generated code must not run on the control origin; send the browser to the content origin."""
    if is_control_host(host_name(request.headers.get("host", ""))):
        return RedirectResponse(str(request.url.replace(hostname=CONTENT_HOST)), status_code=307)
    return None


@app.get("/content/{app_id}/", response_class=HTMLResponse)
def content_root(app_id: int, request: Request):
    local_app = get_app(app_id)
    if not local_app:
        raise HTTPException(404, "App not found")
    if local_app.source_type in {"generated", "builtin"}:
        if (redirect := _to_content_origin(request)):
            return redirect
        return _serve_generated(local_app, local_app.manifest.entry_file if local_app.manifest else "index.html")
    if local_app.manifest and local_app.manifest.deployment_plan and local_app.manifest.deployment_plan.frontend.kind == "generated_cli":
        return HTMLResponse(_cli_frontend(local_app))
    raise HTTPException(404, "No internal content route")


@app.get("/content/{app_id}/cli", response_class=HTMLResponse)
def cli_root(app_id: int):
    local_app = get_app(app_id)
    if not local_app:
        raise HTTPException(404, "App not found")
    return HTMLResponse(_cli_frontend(local_app))


@app.get("/content/{app_id}/{path:path}")
def content_file(app_id: int, path: str, request: Request):
    local_app = get_app(app_id)
    if not local_app or local_app.source_type not in {"generated", "builtin"}:
        raise HTTPException(404, "Content not found")
    if (redirect := _to_content_origin(request)):
        return redirect
    return _serve_generated(local_app, path)


def _serve_generated(local_app, path: str):
    root = (Path(local_app.workspace) / "generated").resolve()
    target = (root / (path or "index.html")).resolve()
    if root not in target.parents and target != root:
        raise HTTPException(403, "Invalid path")
    if target.is_dir():
        target = target / "index.html"
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "File not found")
    media = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return FileResponse(target, media_type=media)


def _cli_frontend(local_app) -> str:
    plan = local_app.manifest.deployment_plan if local_app.manifest else None
    if not plan:
        return "<h1>App not ready</h1>"
    fields = plan.frontend.fields
    controls = []
    for f in fields:
        name, label = html.escape(f.name), html.escape(f.label)
        help_text = f"<small>{html.escape(f.help)}</small>" if f.help else ""
        if f.kind == "textarea":
            control = f"<textarea id='{name}'></textarea>"
        elif f.kind == "select":
            opts = "".join(f"<option>{html.escape(x)}</option>" for x in f.options)
            control = f"<select id='{name}'>{opts}</select>"
        else:
            typ = "number" if f.kind == "number" else "text"
            control = f"<input type='{typ}' id='{name}'>"
        controls.append(f"<label>{label}{control}{help_text}</label>")
    if not controls:
        controls.append("<label>Input<input id='args'></label>")
    names = [f.name for f in fields]
    values_js = "{" + ",".join(json_pair(n) for n in names) + "}" if names else "{}"
    args_js = "document.getElementById('args')?.value||''"
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>{html.escape(plan.frontend.title)}</title><style>body{{font:15px system-ui;max-width:760px;margin:50px auto;padding:0 22px}}label{{display:block;margin:14px 0;font-weight:600}}input,textarea,select{{display:block;width:100%;padding:12px;margin-top:6px;border:1px solid #ccd1d8;border-radius:10px;font:inherit}}small{{display:block;color:#777;margin-top:4px}}button{{border:0;border-radius:12px;padding:11px 16px;background:#111;color:white;cursor:pointer}}pre{{background:#111;color:#eee;padding:16px;border-radius:14px;white-space:pre-wrap;min-height:120px}}</style></head><body><h1>{html.escape(plan.frontend.title)}</h1><p>{html.escape(plan.frontend.description or plan.summary)}</p>{''.join(controls)}<button onclick='run()'>Run</button><pre id='out'>Ready.</pre><script>async function run(){{let o=document.getElementById('out');o.textContent='Running…';let r=await fetch('/api/apps/{local_app.id}/invoke',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{values:{values_js},args:{args_js}}})}});let j=await r.json();o.textContent=j.output||j.detail||JSON.stringify(j,null,2)}}</script></body></html>"""


def json_pair(name: str) -> str:
    safe = name.replace("'", "")
    return f"'{safe}':document.getElementById('{safe}')?.value||''"


def run():
    import uvicorn
    uvicorn.run("morfic.app:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    run()
