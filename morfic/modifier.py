from __future__ import annotations

import json
from pathlib import Path

from .inspector import inspect_editable_files
from .llm import llm
from .models import AppManifest, PatchAction
from .prompts import MODIFY_REPO_SYSTEM


async def propose_repo_modification(repo: Path, manifest: AppManifest, request: str) -> PatchAction:
    files = inspect_editable_files(repo, max_files=28, max_chars=140000)
    payload = {"request": request, "manifest": manifest.model_dump(), "files": files}
    raw = await llm.chat(MODIFY_REPO_SYSTEM, json.dumps(payload, indent=2), json_mode=True)
    try:
        data = json.loads(_extract_json(raw))
        return PatchAction.model_validate(data)
    except Exception as e:
        raise RuntimeError(f"Model returned invalid repository modification JSON: {e}\n{raw[:1000]}") from e


def _extract_json(text: str) -> str:
    s, e = text.find("{"), text.rfind("}")
    return text[s:e+1] if s >= 0 and e > s else text
