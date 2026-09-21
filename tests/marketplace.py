from __future__ import annotations
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain

import asyncio

from morfic.catalog import load_catalog
from morfic.db import init_db
import morfic.orchestrator as orchestrator


def test_catalog_shape() -> None:
    entries = load_catalog()
    assert len(entries) >= 19
    assert any(x.id == "yt-dlp" for x in entries)
    assert any("CLI" in x.notes for x in entries if x.id == "yt-dlp")


async def test_direct_selection() -> None:
    init_db()
    original = orchestrator._deploy_catalog

    async def no_deploy(*_args, **_kwargs):
        return None

    orchestrator._deploy_catalog = no_deploy
    try:
        resolution, app = await orchestrator.request_catalog_software("cyberchef")
        assert resolution.strategy == "catalog"
        assert app.source_url == "https://github.com/gchq/CyberChef.git"
        await asyncio.sleep(0)
        resolution2, app2 = await orchestrator.request_catalog_software("cyberchef")
        assert resolution2.strategy == "installed"
        assert app2.id == app.id
    finally:
        orchestrator._deploy_catalog = original


if __name__ == "__main__":
    test_catalog_shape()
    asyncio.run(test_direct_selection())
    print("MARKETPLACE PASS: browse catalog + exact direct selection + installed reuse")
