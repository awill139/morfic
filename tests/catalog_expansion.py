from __future__ import annotations
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain

from morfic.catalog import load_catalog, search_catalog


def main() -> None:
    entries = load_catalog()
    ids = [e.id for e in entries]
    assert len(ids) >= 19, f"expected expanded catalog, got {len(ids)} entries"
    assert len(ids) == len(set(ids)), "catalog ids must be unique"
    for entry in entries:
        assert entry.repo_url.startswith("https://github.com/") or entry.repo_url.startswith("file://"), entry.repo_url
        if entry.repo_url.startswith("https://github.com/"):
            assert entry.repo_url.endswith(".git"), entry.repo_url
        assert entry.capabilities, entry.id
        assert entry.keywords, entry.id
    cases = {
        "remove the background from these photos": "rembg",
        "make my scanned PDFs searchable with OCR": "ocrmypdf",
        "I need a private place for quick markdown notes": "memos",
        "track a website and tell me when the price changes": "changedetection",
        "organize my recipes and plan meals": "mealie",
    }
    for query, expected in cases.items():
        match, score = search_catalog(query, threshold=0.10)
        assert match is not None, (query, score)
        assert match.id == expected, (query, match.id, score)
    print(f"CATALOG PASS: {len(ids)} curated+demo entries")


if __name__ == "__main__":
    main()
