from __future__ import annotations
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain

import asyncio
import json
import os
import tempfile
from pathlib import Path

# Must be set before morfic.config is imported.
TEST_HOME = Path(tempfile.mkdtemp(prefix="morfic-test-v06-four-"))
os.environ["PERSONAL_SOFTWARE_HOME"] = str(TEST_HOME)
os.environ["PERSONAL_SOFTWARE_ALLOW_HOST_EXECUTION"] = "1"

from morfic.builtins import ensure_builtin_apps
from morfic.db import get_app, init_db, list_apps
from morfic.deployer import invoke_cli, stop_app
from morfic.llm import llm
from morfic.orchestrator import modify_app, request_software
from morfic.prompts import (
    GENERATE_SYSTEM,
    MODIFY_IMPACT_SYSTEM,
    MODIFY_PATCH_SYSTEM,
    PLAN_REPO_SYSTEM,
    RESOLVE_SYSTEM,
)


def j(data) -> str:
    return json.dumps(data)


async def scripted_llm(system: str, user: str, json_mode: bool) -> str:
    """Scripted model outputs authored for the exact production prompts.

    This is not production demo logic. It is injected only in this test so the
    orchestrator can be verified without external API credentials/network.
    """
    if system == RESOLVE_SYSTEM:
        payload = json.loads(user)
        req = payload["request"].lower()
        installed = payload["options"]["installed"]
        if "scientific calculator" in req:
            calc = next(x for x in installed if x["name"] == "Scientific Calculator")
            return j({"strategy":"installed","reason":"The bundled scientific calculator already satisfies the request.","app_id":calc["id"],"catalog_id":None,"generated_name":None,"capabilities":["scientific calculator","math"]})
        if "unit converter" in req or "convert units" in req:
            return j({"strategy":"catalog","reason":"The curated Unit Converter repo directly matches.","app_id":None,"catalog_id":"demo-unit-converter","generated_name":None,"capabilities":["unit conversion"]})
        if "text statistics" in req or "count words" in req:
            return j({"strategy":"catalog","reason":"The curated CLI text statistics repo matches.","app_id":None,"catalog_id":"demo-text-statistics","generated_name":None,"capabilities":["text statistics","word count"]})
        if "caffeine" in req:
            return j({"strategy":"generate","reason":"No curated app is a strong enough fit for this bespoke tracker.","app_id":None,"catalog_id":None,"generated_name":"Caffeine Tracker","capabilities":["caffeine tracking","half-life estimate"]})
        raise AssertionError(f"Unexpected resolver request: {req}")

    if system == PLAN_REPO_SYSTEM:
        payload = json.loads(user)
        files = set(payload["repo"].get("files", []))
        if "index.html" in files:
            return j({
                "name":"Unit Converter","summary":"Static local unit converter with an existing web UI.","project_type":"static",
                "install_commands":[],"run_command":["python","-m","http.server","8811","--bind","127.0.0.1"],"port":8811,"healthcheck_path":"/","env":{},
                "frontend":{"kind":"existing","title":"Unit Converter","description":"Convert units locally.","fields":[]},"detected_files":sorted(files),
            })
        if "main.py" in files:
            return j({
                "name":"Text Statistics","summary":"CLI-only text analyzer; generate a friendly text input UI.","project_type":"python",
                "install_commands":[],"run_command":["python","main.py"],"port":None,"healthcheck_path":"/","env":{},
                "frontend":{"kind":"generated_cli","title":"Text Statistics","description":"Paste text to see word, character, sentence, and reading-time statistics.","fields":[{"name":"text","label":"Text to analyze","kind":"textarea","required":True,"help":"Paste or type text here.","options":[]}]},"detected_files":sorted(files),
            })
        raise AssertionError(f"Unexpected repo files: {files}")

    if system == GENERATE_SYSTEM:
        assert "caffeine" in user.lower()
        html = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Caffeine Tracker</title><style>body{font:16px system-ui;max-width:760px;margin:40px auto;padding:20px;background:#f7f4ef}main{background:white;padding:24px;border-radius:20px}input,button{padding:10px;margin:5px}#remaining{font-size:30px;font-weight:700}</style></head><body><main><h1>Caffeine Tracker</h1><p>Add caffeine and estimate remaining caffeine using a 5-hour half-life.</p><input id="mg" type="number" value="100" min="0"><button id="add">Add now</button><p>Estimated now</p><div id="remaining">0 mg</div><ul id="log"></ul></main><script>let doses=JSON.parse(localStorage.getItem('caffeineDoses')||'[]');function render(){const now=Date.now();let total=doses.reduce((s,d)=>s+d.mg*Math.pow(.5,(now-d.t)/18000000),0);document.getElementById('remaining').textContent=total.toFixed(1)+' mg';document.getElementById('log').innerHTML=doses.map(d=>'<li>'+d.mg+' mg · '+new Date(d.t).toLocaleTimeString()+'</li>').join('');localStorage.setItem('caffeineDoses',JSON.stringify(doses))}document.getElementById('add').onclick=()=>{doses.push({mg:Number(document.getElementById('mg').value)||0,t:Date.now()});render()};render();setInterval(render,60000)</script></body></html>'''
        return j({"name":"Caffeine Tracker","description":"Track caffeine doses and estimate caffeine remaining over time.","capabilities":["caffeine tracking","half-life estimate","local persistence"],"entry_file":"index.html","files":[{"path":"index.html","content":html}]})

    if system == MODIFY_IMPACT_SYSTEM:
        payload = json.loads(user)
        assert "graph" in payload["request"].lower()
        return j({"summary":"Added graphing mode to the existing calculator.","existing_file_changes":[{"path":"index.html","instruction":"Insert a visible graphing mode and canvas before the end of the body.","hints":["</body>"]}],"new_files":[],"file_deletes":[]})

    if system == MODIFY_PATCH_SYSTEM:
        payload = json.loads(user)
        assert payload["target_file"] == "index.html"
        return j({"operations":[{"op":"insert_before","anchor":"</body>","content":"<p id=\"graph\">Graphing mode enabled</p><canvas id=\"plot\"></canvas><script>const c=document.getElementById(\"plot\"),x=c.getContext(\"2d\");x.beginPath();x.moveTo(0,50);x.lineTo(300,50);x.stroke()</script>","occurrence":1}]})

    raise AssertionError("Unexpected prompt used by orchestration")


async def wait_app(app_id: int, timeout: float = 20):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        app = get_app(app_id)
        if app and app.status in {"running", "failed"}:
            return app
        await asyncio.sleep(.1)
    raise TimeoutError(f"app {app_id} did not finish")


async def main():
    init_db()
    ensure_builtin_apps()
    llm.set_test_handler(scripted_llm)

    # 1. Preloaded/bundled app: LLM chooses it; no repo clone/generation occurs.
    resolution, calc = await request_software("I need a scientific calculator")
    assert resolution.strategy == "installed"
    assert calc.name == "Scientific Calculator" and calc.source_type == "builtin"
    print("DEMO 1 PASS: bundled Scientific Calculator selected")

    # Also prove the contextual AI can evolve that same app.
    before_id = calc.id
    result = await modify_app(calc.id, "Add graphing mode")
    calc2 = get_app(calc.id)
    assert result["version"] == 2 and calc2.id == before_id and calc2.version == 2
    assert "Graphing mode enabled" in (Path(calc2.workspace) / "generated" / "index.html").read_text()
    print("EXTENSION PASS: AI modified the existing calculator in place")

    # 2. Git repo WITH frontend: LLM recognizes existing UI and deploys it.
    resolution, app = await request_software("I need a unit converter")
    assert resolution.strategy == "catalog"
    app = await wait_app(app.id)
    assert app.status == "running", app.last_error
    assert app.manifest.deployment_plan.frontend.kind == "existing"
    assert app.local_url and app.local_url.startswith("http://127.0.0.1:")
    print("DEMO 2 PASS: Git repo existing frontend detected + deployed", app.local_url)

    # 3. Git repo WITHOUT frontend: LLM marks generated_cli; runtime builds local UI.
    resolution, cli_app = await request_software("I need text statistics and word count")
    assert resolution.strategy == "catalog"
    cli_app = await wait_app(cli_app.id)
    assert cli_app.status == "running", cli_app.last_error
    assert cli_app.manifest.deployment_plan.frontend.kind == "generated_cli"
    assert cli_app.local_url.endswith("/cli")
    invoked = await invoke_cli(cli_app.id, {"text":"One two three. Four!"}, "")
    assert invoked["returncode"] == 0 and '"words": 4' in invoked["output"]
    print("DEMO 3 PASS: CLI-only Git repo got generated frontend + callable adapter")

    # 4. No suitable app/repo: LLM generates the app itself.
    resolution, caffeine = await request_software("Build me a caffeine tracker that estimates how much caffeine is still in my body")
    assert resolution.strategy == "generate"
    caffeine = await wait_app(caffeine.id)
    assert caffeine.status == "running", caffeine.last_error
    page = Path(caffeine.workspace) / "generated" / "index.html"
    assert page.exists() and "Caffeine Tracker" in page.read_text()
    print("DEMO 4 PASS: purpose-built Caffeine Tracker generated and served locally")

    for a in list_apps():
        stop_app(a.id)
    llm.set_test_handler(None)
    print("ALL FOUR DEMO PATHS PASS")


if __name__ == "__main__":
    asyncio.run(main())
