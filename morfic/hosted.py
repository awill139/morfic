from __future__ import annotations
import json, platform, uuid
from pathlib import Path
import httpx
from . import __version__
from .config import settings
from .provider_config import delete_secret, get_secret, set_secret, load_provider_settings
from .redact import excerpt

INSTALL_ID_PATH=settings.home/'installation-id'

def installation_id()->str:
    if INSTALL_ID_PATH.exists():
        value=INSTALL_ID_PATH.read_text(encoding='utf-8').strip()
        if value:return value
    value='inst_'+uuid.uuid4().hex
    INSTALL_ID_PATH.write_text(value,encoding='utf-8')
    return value

def environment()->dict:
    return {'client_version':__version__,'os':platform.system()+' '+platform.release(),'arch':platform.machine(),'installation_id':installation_id()}

async def connect_invite(invite_code:str, device_label:str='')->dict:
    cfg=load_provider_settings()
    url=cfg.official_base_url.rstrip('/')+'/v1/auth/invite'
    async with httpx.AsyncClient(timeout=20) as client:
        r=await client.post(url,json={'invite_code':invite_code,'device_label':device_label or platform.node()})
    if r.status_code>=400: raise RuntimeError(_detail(r))
    data=r.json(); token=str(data.get('token') or '')
    if not token: raise RuntimeError('Orchestrator did not return a device token')
    set_secret('official_token',token)
    return {'ok':True,'device_id':data.get('device_id')}

async def hosted_task(task:str,user:str,json_mode:bool,max_output_tokens:int|None=None)->str:
    cfg=load_provider_settings(); token=get_secret('official_token')
    if not token: raise RuntimeError('Connect the Official service in AI Settings first.')
    payload={'task':task,'input':user,'json_mode':json_mode,'max_output_tokens':max_output_tokens,
             **environment(),'diagnostic_consent':bool(cfg.share_usage_data and cfg.diagnostic_consent)}
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=20,read=200,write=90,pool=20)) as client:
        r=await client.post(cfg.official_base_url.rstrip('/')+'/v1/task',headers={'Authorization':f'Bearer {token}'},json=payload)
    if r.status_code==401 and _detail(r)=='Invalid device token':
        # The service no longer recognises this device (for example its database was reset). Forget the dead
        # token so Settings shows "Not connected" and the invite code is asked for again.
        delete_secret('official_token')
        raise RuntimeError('The Morfic service no longer recognises this device. Open AI Settings and enter your invite code again to reconnect.')
    if r.status_code>=400: raise RuntimeError(_detail(r))
    data=r.json(); text=data.get('text')
    if not isinstance(text,str) or not text: raise RuntimeError('Official orchestrator returned no text output')
    return text


def _sharing(cfg)->bool:
    """Backend telemetry is sent only in Official mode, with a device token, and only while the user
    keeps 'share usage data' on. The AI calls themselves (hosted_task) are not telemetry."""
    return cfg.provider=='official' and cfg.share_usage_data and bool(get_secret('official_token'))

async def emit_model_call(*, task:str, provider:str, model:str, input_chars:int, output_chars:int, duration_ms:int, success:bool,
                          error_class:str|None=None, error_message:str|None=None, input_tokens:int|None=None, output_tokens:int|None=None,
                          request_text:str|None=None, response_text:str|None=None)->None:
    cfg=load_provider_settings()
    if not _sharing(cfg):return
    token=get_secret('official_token')
    payload={
        'task':task,'provider':provider,'model':model,'input_chars':int(input_chars),'output_chars':int(output_chars),
        'latency_ms':int(duration_ms),'success':bool(success),'error_class':error_class,'error_message':(error_message or '')[:1200],
        'input_tokens':input_tokens,'output_tokens':output_tokens,
        **environment(),
    }
    if cfg.diagnostic_consent:
        # Redacted and bounded here, on the user's machine, before anything is sent.
        payload['request_excerpt']=excerpt(request_text)
        payload['response_excerpt']=excerpt(response_text)
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            await client.post(cfg.official_base_url.rstrip('/')+'/v1/model-events',headers={'Authorization':f'Bearer {token}'},json=payload)
    except Exception:
        return

async def emit_event(event_type:str, **fields)->None:
    cfg=load_provider_settings()
    if not _sharing(cfg):return
    token=get_secret('official_token')
    payload={'event_type':event_type,**environment(),**fields}
    # Keep telemetry best-effort; it must never break local software.
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            await client.post(cfg.official_base_url.rstrip('/')+'/v1/events',headers={'Authorization':f'Bearer {token}'},json=payload)
    except Exception:
        return

def _detail(r:httpx.Response)->str:
    try:
        d=r.json(); return str(d.get('detail') or d.get('error') or d)[:1200]
    except Exception:return f'Hosted orchestrator error ({r.status_code}): {r.text[:800]}'
