from __future__ import annotations

import json

from .catalog import load_catalog, tokenize
from .db import list_apps
from .llm import llm
from .models import Resolution
from .prompts import RESOLVE_SYSTEM


async def resolve(intent: str) -> Resolution:
    apps = [a for a in list_apps() if a.status in {"running", "ready"}]
    catalog = load_catalog()

    # Explicit multi-word catalog phrases are strong enough to resolve without an LLM.
    # This keeps known requests such as "personal netflix" on the deterministic path.
    low = intent.lower()
    for entry in catalog:
        for keyword in entry.keywords:
            phrase = keyword.strip().lower()
            if len(phrase.split()) >= 2 and phrase in low:
                return Resolution(
                    strategy="catalog",
                    reason=f"Matched curated capability: {keyword}",
                    catalog_entry=entry,
                    capabilities=entry.capabilities,
                )

    options = {
        "installed": [
            {"id": a.id, "name": a.name, "description": a.description, "capabilities": a.capabilities, "source_type": a.source_type}
            for a in apps
        ],
        "catalog": [
            {"id": e.id, "name": e.name, "description": e.description, "capabilities": e.capabilities, "keywords": e.keywords, "project_hint": e.project_hint, "notes": e.notes}
            for e in catalog
        ],
    }
    raw = await llm.chat(RESOLVE_SYSTEM, json.dumps({"request": intent, "options": options}, indent=2), json_mode=True)
    try:
        data = json.loads(_extract_json(raw))
    except Exception as e:
        raise RuntimeError(f"The model returned an invalid capability resolution: {e}\n{raw[:1000]}") from e

    strategy = data.get("strategy")
    if strategy == "installed" and data.get("app_id") is not None:
        match = next((a for a in apps if a.id == int(data["app_id"])), None)
        if match:
            return Resolution(strategy="installed", reason=data.get("reason", "Already available locally."), app_id=match.id, capabilities=match.capabilities)
    if strategy == "catalog" and data.get("catalog_id"):
        match = next((e for e in catalog if e.id == data["catalog_id"]), None)
        if match:
            return Resolution(strategy="catalog", reason=data.get("reason", "A curated repository matches."), catalog_entry=match, capabilities=match.capabilities)
    if strategy not in {"installed", "catalog", "generate"}:
        raise RuntimeError(f"Model selected an unknown resolution strategy: {strategy}")
    return Resolution(
        strategy="generate",
        reason=data.get("reason", "No suitable existing implementation."),
        generated_name=data.get("generated_name") or _name_for(intent),
        capabilities=data.get("capabilities") or list(tokenize(intent))[:8],
    )


def _name_for(intent: str) -> str:
    text = intent.strip().rstrip(".!?")
    for prefix in ["i need ", "i want ", "give me ", "make me ", "build me ", "create "]:
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    return (text[:1].upper() + text[1:])[:70] or "Local App"


def _extract_json(text: str) -> str:
    s, e = text.find("{"), text.rfind("}")
    return text[s:e+1] if s >= 0 and e > s else text
