from __future__ import annotations
import json, os
from dataclasses import dataclass
from pathlib import Path

from .envvars import getenv

@dataclass(frozen=True)
class Distribution:
    mode:str='community'
    official_base_url:str='http://127.0.0.1:8770'

def load_distribution()->Distribution:
    p=Path(__file__).with_name('distribution.json')
    data={}
    try:data=json.loads(p.read_text(encoding='utf-8'))
    except Exception:pass
    mode=getenv('DISTRIBUTION',str(data.get('mode') or 'community')).strip().lower()
    url=getenv('OFFICIAL_URL',str(data.get('official_base_url') or 'http://127.0.0.1:8770')).rstrip('/')
    return Distribution(mode=mode,official_base_url=url)

distribution=load_distribution()
