from __future__ import annotations

import json
import re

from .config import settings
from .demo_repos import ensure_demo_repos
from .models import CatalogEntry


def load_catalog() -> list[CatalogEntry]:
    entries: list[CatalogEntry] = []
    if settings.catalog_path.exists():
        entries.extend(CatalogEntry.model_validate(x) for x in json.loads(settings.catalog_path.read_text(encoding="utf-8")))
    try:
        demo = ensure_demo_repos()
        known = {e.id for e in entries}
        entries.extend(e for e in demo if e.id not in known)
    except Exception:
        # Git may not be installed before first-run setup. The app can still configure the LLM and use generation/builtins.
        pass
    return entries


def tokenize(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", text.lower()) if len(x) > 1}


def search_catalog(intent: str, threshold: float = 0.24) -> tuple[CatalogEntry | None, float]:
    q = tokenize(intent)
    best, best_score = None, 0.0
    for entry in load_catalog():
        phrases = entry.keywords + entry.capabilities + [entry.name, entry.description]
        phrase_hits = sum(1 for p in phrases if p.lower() in intent.lower())
        words = tokenize(" ".join(phrases))
        overlap = len(q & words) / max(1, len(q))
        score = min(1.0, overlap + 0.22 * phrase_hits)
        if score > best_score:
            best, best_score = entry, score
    return (best, best_score) if best_score >= threshold else (None, best_score)
