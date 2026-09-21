import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import asyncio
import json
import os
import tempfile
from pathlib import Path

home = tempfile.mkdtemp(prefix="morfic-test-mod-resilience-")
os.environ["PERSONAL_SOFTWARE_HOME"] = home
os.environ["PERSONAL_SOFTWARE_MODIFY_TIMEOUT"] = "2"
os.environ["PERSONAL_SOFTWARE_LLM_TIMEOUT"] = "2"

from morfic.builtins import ensure_builtin_apps
from morfic.db import get_app, init_db, list_apps, recover_stale_modifications, update_app
from morfic.llm import llm
from morfic.operations import cancel_modification, get_latest_operation, start_modification
from morfic.orchestrator import modify_app


def calc_app():
    return next(a for a in list_apps() if a.name == "Scientific Calculator")


async def test_staged_localization():
    async def handler(system: str, user: str, json_mode: bool):
        if "localization engine" in system:
            payload = json.loads(user)
            mapping = {
                "Scientific Calculator": "科学计算器",
                "History": "历史",
                "Graph": "函数图",
                "Degrees": "角度",
                "Radians": "弧度",
                "Clear": "清除",
            }
            return json.dumps({
                "translations": [
                    {"id": c["id"], "text": mapping[c["text"]]}
                    for c in payload["candidates"] if c["text"] in mapping
                ]
            }, ensure_ascii=False)
        raise AssertionError("Unexpected prompt in localization test: " + system[:80])

    llm.set_test_handler(handler)
    app = calc_app()
    result = await modify_app(app.id, "now make it all in chinese")
    assert result["ok"] is True
    app = get_app(app.id)
    assert app.status == "running"
    assert app.version == 2
    html = (Path(app.workspace) / "generated" / "index.html").read_text(encoding="utf-8")
    assert "科学计算器" in html
    print("MODIFY PASS: localization uses targeted string translation and returns running")


async def test_immediate_provider_failure_recovers_state():
    async def handler(system: str, user: str, json_mode: bool):
        raise RuntimeError("simulated provider failure")

    llm.set_test_handler(handler)
    app = calc_app()
    op = start_modification(app.id, "make everything purple")
    for _ in range(30):
        await asyncio.sleep(0.05)
        latest = get_latest_operation(app.id)
        if latest and latest["status"] in {"failed", "cancelled", "succeeded"}:
            break
    latest = get_latest_operation(app.id)
    assert latest["status"] == "failed", latest
    assert get_app(app.id).status == "running"
    print("STATE PASS: planning failure no longer strands app in modifying")


async def test_cancel_hung_model():
    gate = asyncio.Event()

    async def handler(system: str, user: str, json_mode: bool):
        await gate.wait()
        return "{}"

    llm.set_test_handler(handler)
    app = calc_app()
    start_modification(app.id, "translate to Klingon")
    for _ in range(30):
        await asyncio.sleep(0.05)
        if get_app(app.id).status == "modifying":
            break
    assert get_app(app.id).status == "modifying"
    result = await cancel_modification(app.id)
    assert result["ok"] is True
    assert get_app(app.id).status == "running"
    latest = get_latest_operation(app.id)
    assert latest["status"] == "cancelled", latest
    print("CANCEL PASS: hung model can be cancelled and previous app remains running")


async def test_watchdog_hung_model():
    gate = asyncio.Event()

    async def handler(system: str, user: str, json_mode: bool):
        await gate.wait()
        return "{}"

    llm.set_test_handler(handler)
    app = calc_app()
    start_modification(app.id, "another impossible long change")
    await asyncio.sleep(2.4)
    latest = get_latest_operation(app.id)
    assert latest["status"] == "failed", latest
    assert "safety limit" in (latest["error"] or "")
    assert get_app(app.id).status == "running"
    print("WATCHDOG PASS: hung modification is bounded and rolled back")


def test_startup_recovery():
    app = calc_app()
    update_app(app.id, status="modifying")
    ids = recover_stale_modifications()
    assert app.id in ids
    app = get_app(app.id)
    assert app.status == "running"
    print("STARTUP PASS: stale modifying state recovers automatically after restart")


async def main():
    init_db()
    ensure_builtin_apps()
    await test_staged_localization()
    await test_immediate_provider_failure_recovers_state()
    await test_cancel_hung_model()
    await test_watchdog_hung_model()
    test_startup_recovery()
    llm.set_test_handler(None)
    print("ALL MODIFICATION RESILIENCE TESTS PASS")


if __name__ == "__main__":
    asyncio.run(main())
