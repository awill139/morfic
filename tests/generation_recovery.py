from __future__ import annotations
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain

import asyncio
import json
import os
import tempfile
from pathlib import Path

TEST_HOME = Path(tempfile.mkdtemp(prefix="morfic-test-v061-recovery-"))
os.environ["PERSONAL_SOFTWARE_HOME"] = str(TEST_HOME)

from morfic.generator import generate_app, validate_static_app
from morfic.llm import llm
from morfic.prompts import (
    GENERATE_FILE_SYSTEM,
    GENERATE_SYSTEM,
    REPAIR_GENERATED_FILE_SYSTEM,
    REPAIR_GENERATION_JSON_SYSTEM,
)

calls: list[str] = []
index_generation_count = 0


async def scripted_llm(system: str, user: str, json_mode: bool) -> str:
    global index_generation_count
    if system == GENERATE_SYSTEM:
        calls.append("truncated-blueprint")
        # Recreate the v0.6 failure shape: a model starts embedding a large HTML
        # string in JSON and gets cut off before closing the string/object.
        return '{"name":"LifePulse","description":"Habit tracker","files":[{"path":"index.html","content":"<!doctype html><html><body><div class=\\"logo\\">'

    if system == REPAIR_GENERATION_JSON_SYSTEM:
        calls.append("repair-blueprint")
        return json.dumps({
            "name": "LifePulse",
            "description": "Track sleep, hydration, exercise and mood with local trends.",
            "capabilities": ["habit tracking", "trend visualization", "local persistence"],
            "entry_file": "index.html",
            "files": [
                {"path": "index.html", "purpose": "accessible dashboard shell"},
                {"path": "styles.css", "purpose": "responsive dashboard styles"},
                {"path": "app.js", "purpose": "tracking, localStorage, trend summary"},
            ],
            "product_spec": {
                "primary_jobs": ["log daily behaviors", "review trends"],
                "data_model": ["daily sleep hours", "water glasses", "mood"],
                "interactions": ["save today's log", "render recent averages"],
                "persistence": "localStorage key lifepulse.entries",
                "design_direction": "calm personal dashboard",
                "dom_contract": ["form#daily-log", "#sleep", "#water", "#mood", "#summary", "#history"],
                "acceptance_tests": ["saved entries survive reload", "summary updates after save"],
            },
        })

    if system == GENERATE_FILE_SYSTEM:
        payload = json.loads(user)
        path = payload["target_file"]["path"]
        calls.append(f"generate:{path}")
        if path == "index.html":
            index_generation_count += 1
            # Deliberately truncate the file too. The file validator must detect
            # the missing closing tags and invoke targeted file repair.
            return '''<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="styles.css"></head><body><main><h1>LifePulse</h1><form id="daily-log"><input id="sleep" type="number"><input id="water" type="number"><select id="mood"><option>Good</option></select><button>Save</button></form><div id="summary"></div><div id="history"></div><script src="app.js"></script>'''
        if path == "styles.css":
            return 'body{font-family:system-ui;margin:0;background:#f4f6f5;color:#18201d}main{max-width:760px;margin:40px auto;padding:24px}input,select,button{padding:10px;margin:6px}'
        if path == "app.js":
            return '''const form=document.getElementById('daily-log');const key='lifepulse.entries';const entries=JSON.parse(localStorage.getItem(key)||'[]');function render(){const s=document.getElementById('summary');const h=document.getElementById('history');const avg=entries.length?entries.reduce((a,e)=>a+e.water,0)/entries.length:0;s.textContent=`Average water: ${avg.toFixed(1)} glasses`;h.textContent=entries.map(e=>`${e.sleep}h sleep · ${e.water} glasses · ${e.mood}`).join(' | ')}form.addEventListener('submit',e=>{e.preventDefault();entries.push({sleep:Number(document.getElementById('sleep').value)||0,water:Number(document.getElementById('water').value)||0,mood:document.getElementById('mood').value});localStorage.setItem(key,JSON.stringify(entries));render()});render();'''
        raise AssertionError(path)

    if system == REPAIR_GENERATED_FILE_SYSTEM:
        payload = json.loads(user)
        path = payload["target_file"]["path"]
        calls.append(f"repair-file:{path}")
        assert path == "index.html"
        assert "missing </html>" in payload["validation_error"]
        return '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="styles.css"><title>LifePulse</title></head><body><main><h1>LifePulse</h1><form id="daily-log"><label>Sleep <input id="sleep" type="number" min="0" max="24" step="0.25"></label><label>Water <input id="water" type="number" min="0"></label><label>Mood <select id="mood"><option>Good</option><option>Okay</option><option>Low</option></select></label><button type="submit">Save today</button></form><section id="summary"></section><section id="history"></section></main><script src="app.js"></script></body></html>'''

    raise AssertionError("unexpected system prompt")


async def main() -> None:
    llm.set_test_handler(scripted_llm)
    try:
        target = TEST_HOME / "lifepulse"
        manifest = await generate_app(
            "i want a life simulator, basically document all my behaviours like whether i sleep early, how many water i drink, and show the trend. use your mind to design the best version",
            target,
        )
        validate_static_app(target, manifest.entry_file or "index.html")
        assert manifest.name == "LifePulse"
        assert (target / "index.html").exists()
        assert (target / "styles.css").exists()
        assert (target / "app.js").exists()
        assert "repair-blueprint" in calls
        assert "repair-file:index.html" in calls
        assert "</html>" in (target / "index.html").read_text(encoding="utf-8")
        print("RECOVERY PASS: truncated JSON blueprint repaired automatically")
        print("RECOVERY PASS: truncated generated file detected and repaired automatically")
        print("RECOVERY PASS: validated app published only after repair")
    finally:
        llm.set_test_handler(None)


if __name__ == "__main__":
    asyncio.run(main())
