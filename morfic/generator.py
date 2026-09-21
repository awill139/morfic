from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .inspector import inspect_editable_files
from .llm import llm
from .models import AppManifest, PatchAction
from .targeted_modifier import propose_targeted_generated_modification
from .prompts import (
    GENERATE_FILE_SYSTEM,
    GENERATE_SYSTEM,
    MODIFY_GENERATED_FILE_SYSTEM,
    MODIFY_GENERATED_SYSTEM,
    REPAIR_GENERATED_FILE_SYSTEM,
    REPAIR_GENERATION_JSON_SYSTEM,
)

MAX_BLUEPRINT_REPAIRS = 2
MAX_FILE_REPAIRS = 2
MAX_FINAL_REPAIRS = 2


async def generate_app(intent: str, app_dir: Path) -> AppManifest:
    """Materialize a generated app with staged generation and autonomous repair."""
    app_dir.parent.mkdir(parents=True, exist_ok=True)
    blueprint = await _generate_blueprint(intent)
    file_defs = _normalize_file_defs(blueprint)
    legacy_contents = {
        str(x.get("path")): str(x.get("content", ""))
        for x in (blueprint.get("files") or [])
        if isinstance(x, dict) and x.get("path") and "content" in x
    }

    with tempfile.TemporaryDirectory(prefix="morfic-build-", dir=str(app_dir.parent)) as td:
        build_dir = Path(td)
        generated: dict[str, str] = {}
        for file_def in file_defs:
            path = file_def["path"]
            content = legacy_contents.get(path, "") or await _generate_one_file(intent, blueprint, file_def, generated)
            content = await _repair_file_until_valid(intent, blueprint, file_def, content, generated)
            generated[path] = content
            _safe_write_files(build_dir, [{"path": path, "content": content}])

        entry_file = str(blueprint.get("entry_file") or "index.html")
        await _repair_app_until_valid(intent, blueprint, build_dir, generated, entry_file)
        if app_dir.exists():
            shutil.rmtree(app_dir)
        shutil.copytree(build_dir, app_dir)

    return AppManifest(
        name=str(blueprint.get("name") or "Local App")[:100],
        description=str(blueprint.get("description") or intent)[:500],
        requested_intent=intent,
        capabilities=[str(x)[:80] for x in (blueprint.get("capabilities") or [])][:20],
        source_type="generated",
        entry_file=str(blueprint.get("entry_file") or "index.html"),
    )


async def _generate_blueprint(intent: str) -> dict:
    raw = await llm.chat(GENERATE_SYSTEM, intent, json_mode=True, max_output_tokens=5000)
    return await _parse_json_with_repair(raw, intent, "generated application blueprint", MAX_BLUEPRINT_REPAIRS)


async def _parse_json_with_repair(raw: str, original_request: str, label: str, repairs: int) -> dict:
    last_error: Exception | None = None
    current = raw
    for attempt in range(repairs + 1):
        try:
            data = json.loads(_extract_json(current))
            if not isinstance(data, dict):
                raise ValueError("top-level value is not an object")
            return data
        except Exception as e:
            last_error = e
            if attempt >= repairs:
                break
            payload = {
                "artifact": label,
                "original_request": original_request[-12000:],
                "parse_error": str(e),
                "partial_response": current[-30000:],
                "instruction": "Reconstruct the intended complete valid JSON. Do not include prose.",
            }
            current = await llm.chat(
                REPAIR_GENERATION_JSON_SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                json_mode=True,
                max_output_tokens=6000,
            )
    raise RuntimeError(f"Model returned invalid {label} after automatic repair attempts: {last_error}")


def _normalize_file_defs(blueprint: dict) -> list[dict]:
    raw_files = blueprint.get("files") or []
    file_defs: list[dict] = []
    seen: set[str] = set()
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip().replace("\\", "/")
        if not path or path in seen or ".." in Path(path).parts:
            continue
        if path not in {"index.html", "styles.css", "app.js"}:
            continue
        file_defs.append({"path": path, "purpose": str(item.get("purpose") or "")[:500]})
        seen.add(path)
    if "index.html" not in seen:
        file_defs.insert(0, {"path": "index.html", "purpose": "document structure and accessible UI shell"})
    order = {"index.html": 0, "styles.css": 1, "app.js": 2}
    file_defs.sort(key=lambda x: order.get(x["path"], 99))
    return file_defs[:3]


async def _generate_one_file(intent: str, blueprint: dict, file_def: dict, generated: dict[str, str]) -> str:
    payload = {
        "user_request": intent,
        "blueprint": blueprint,
        "target_file": file_def,
        "already_generated_files": _bounded_sibling_context(generated),
    }
    raw = await llm.chat(
        GENERATE_FILE_SYSTEM,
        json.dumps(payload, ensure_ascii=False, indent=2),
        json_mode=False,
        max_output_tokens=18000,
    )
    return _strip_code_fence(raw)


async def _repair_file_until_valid(intent: str, blueprint: dict, file_def: dict, content: str, siblings: dict[str, str]) -> str:
    current = _strip_code_fence(content)
    last_error: Exception | None = None
    for attempt in range(MAX_FILE_REPAIRS + 1):
        try:
            _validate_generated_file(file_def["path"], current)
            return current
        except Exception as e:
            last_error = e
            if attempt >= MAX_FILE_REPAIRS:
                break
            payload = {
                "user_request": intent,
                "blueprint": blueprint,
                "target_file": file_def,
                "validation_error": str(e),
                "current_file": current[-50000:],
                "sibling_files": _bounded_sibling_context(siblings),
            }
            current = _strip_code_fence(await llm.chat(
                REPAIR_GENERATED_FILE_SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                json_mode=False,
                max_output_tokens=18000,
            ))
    raise RuntimeError(f"Generated {file_def['path']} remained invalid after automatic repair: {last_error}")


async def _repair_app_until_valid(intent: str, blueprint: dict, build_dir: Path, generated: dict[str, str], entry_file: str) -> None:
    last_error: Exception | None = None
    for attempt in range(MAX_FINAL_REPAIRS + 1):
        try:
            validate_static_app(build_dir, entry_file)
            return
        except Exception as e:
            last_error = e
            if attempt >= MAX_FINAL_REPAIRS:
                break
            target = _guess_repair_target(str(e), generated)
            file_def = next((x for x in _normalize_file_defs(blueprint) if x["path"] == target), {"path": target, "purpose": "repair validation failure"})
            payload = {
                "user_request": intent,
                "blueprint": blueprint,
                "target_file": file_def,
                "validation_error": str(e),
                "current_file": generated.get(target, "")[-50000:],
                "sibling_files": _bounded_sibling_context({k: v for k, v in generated.items() if k != target}),
            }
            fixed = _strip_code_fence(await llm.chat(
                REPAIR_GENERATED_FILE_SYSTEM,
                json.dumps(payload, ensure_ascii=False),
                json_mode=False,
                max_output_tokens=18000,
            ))
            fixed = await _repair_file_until_valid(intent, blueprint, file_def, fixed, {k: v for k, v in generated.items() if k != target})
            generated[target] = fixed
            _safe_write_files(build_dir, [{"path": target, "content": fixed}])
    raise RuntimeError(f"Generated app remained invalid after automatic repair: {last_error}")


def _guess_repair_target(error: str, generated: dict[str, str]) -> str:
    low = error.lower()
    for name in generated:
        if name.lower() in low:
            return name
    if "javascript" in low and "app.js" in generated:
        return "app.js"
    return "index.html" if "index.html" in generated else next(iter(generated), "index.html")


def _bounded_sibling_context(files: dict[str, str], max_total: int = 42000) -> dict[str, str]:
    out: dict[str, str] = {}
    remaining = max_total
    for name, content in files.items():
        if remaining <= 0:
            break
        if len(content) <= remaining:
            snippet = content
        else:
            half = max(1000, remaining // 2)
            snippet = content[:half] + "\n/* ... middle omitted from context ... */\n" + content[-half:]
        out[name] = snippet
        remaining -= len(snippet)
    return out


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:html|css|javascript|js)?\s*\n?(.*?)\n?```$", text, flags=re.I | re.S)
    return m.group(1).strip() if m else text


def _validate_generated_file(path: str, content: str) -> None:
    if len(content.strip()) < 20:
        raise RuntimeError("file is unexpectedly empty")
    low = content.lower()
    if any(token in low for token in ("<todo>", "/* todo */", "// todo: implement", "...insert code")):
        raise RuntimeError("file contains an unfinished placeholder")
    if path == "index.html":
        if "<html" in low and "</html>" not in low:
            raise RuntimeError("index.html appears truncated: missing </html>")
        if "<body" in low and "</body>" not in low:
            raise RuntimeError("index.html appears truncated: missing </body>")
    elif path.endswith(".css"):
        if content.count("{") != content.count("}"):
            raise RuntimeError("CSS appears truncated or malformed: unbalanced braces")
    elif path.endswith(".js"):
        _validate_javascript_text(content, path)


async def modify_generated(app_dir: Path, manifest: AppManifest, request: str) -> PatchAction:
    """Plan/apply only localized source patches for an existing generated app.

    The model first sees a compact structural map, then returns exact small patch
    operations for affected existing files and/or isolated new feature files. It
    never needs to regenerate a large unchanged source file merely to add a feature.
    """
    return await propose_targeted_generated_modification(
        app_dir,
        manifest,
        request,
        validate_file=_validate_generated_file,
    )


async def repair_generated_validation(app_dir: Path, manifest: AppManifest, request: str, error: str) -> str:
    """Try to repair a generated/builtin app after a modification fails validation."""
    snapshot = inspect_editable_files(app_dir, max_files=12, max_chars=80000)
    if not snapshot:
        raise RuntimeError("No editable generated files were available for automatic repair")
    target = _guess_repair_target(error, snapshot)
    current = snapshot.get(target, "")
    file_def = {"path": target, "purpose": "repair a modified application after validation failure"}
    blueprint = {
        "name": manifest.name,
        "description": manifest.description,
        "capabilities": manifest.capabilities,
        "entry_file": manifest.entry_file or "index.html",
        "files": [{"path": k, "purpose": "existing application file"} for k in snapshot],
    }
    payload = {
        "user_request": request,
        "blueprint": blueprint,
        "target_file": file_def,
        "validation_error": error,
        "current_file": current[-50000:],
        "sibling_files": _bounded_sibling_context({k: v for k, v in snapshot.items() if k != target}),
    }
    fixed = _strip_code_fence(await llm.chat(
        REPAIR_GENERATED_FILE_SYSTEM,
        json.dumps(payload, ensure_ascii=False),
        json_mode=False,
        max_output_tokens=18000,
    ))
    fixed = await _repair_file_until_valid(request, blueprint, file_def, fixed, {k: v for k, v in snapshot.items() if k != target})
    _safe_write_files(app_dir, [{"path": target, "content": fixed}])
    validate_static_app(app_dir, manifest.entry_file or "index.html")
    return f"Automatically repaired {target} after validation failure"


def validate_static_app(app_dir: Path, entry_file: str = "index.html") -> None:
    root = app_dir.resolve()
    entry = (root / entry_file).resolve()
    if root not in entry.parents or not entry.exists() or not entry.is_file():
        raise RuntimeError("Static app entry file is missing or invalid")
    if entry.stat().st_size < 20:
        raise RuntimeError("Static app entry file is unexpectedly empty")
    text = entry.read_text(encoding="utf-8", errors="replace")
    _validate_generated_file(entry.name, text)
    for attr in re.findall(r'''(?:src|href)=["']([^"']+)["']''', text, flags=re.I):
        if attr.startswith(("http://", "https://", "//")):
            raise RuntimeError(f"Generated app depends on a remote asset: {attr}")
        if attr.startswith(("#", "data:", "javascript:")):
            continue
        asset = (root / attr.split("?", 1)[0].split("#", 1)[0]).resolve()
        if root not in asset.parents and asset != root:
            raise RuntimeError(f"Generated app references an unsafe asset path: {attr}")
        if not asset.exists():
            raise RuntimeError(f"Generated app references a missing local asset: {attr}")
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", text, flags=re.I | re.S)
    for i, script in enumerate(scripts):
        if script.strip():
            _validate_javascript_text(script, f"inline script {i} in {entry.name}")
    for js in list(root.rglob("*.js"))[:30]:
        _validate_javascript_text(js.read_text(encoding="utf-8", errors="replace"), js.name)


def _validate_javascript_text(content: str, label: str) -> None:
    node = shutil.which("node")
    if node:
        with tempfile.TemporaryDirectory(prefix="morfic-js-") as td:
            temp = Path(td) / "check.js"
            temp.write_text(content, encoding="utf-8")
            proc = subprocess.run([node, "--check", str(temp)], capture_output=True, text=True, timeout=20)
            if proc.returncode != 0:
                raise RuntimeError(f"Generated JavaScript is invalid in {label}: " + (proc.stderr or proc.stdout)[-1200:])
        return
    for opening, closing in [("{", "}"), ("(", ")"), ("[", "]")]:
        if content.count(opening) != content.count(closing):
            raise RuntimeError(f"JavaScript in {label} appears truncated: unbalanced {opening}{closing}")


def _safe_write_files(root_dir: Path, files: list[dict]) -> None:
    root = root_dir.resolve()
    for item in files:
        rel = Path(str(item.get("path", "")))
        if not rel.as_posix() or ".." in rel.parts:
            raise RuntimeError(f"Invalid generated path: {rel}")
        target = (root / rel).resolve()
        if root not in target.parents:
            raise RuntimeError(f"Generated file escaped app directory: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item.get("content", "")), encoding="utf-8")


def _write_demo_config(app_dir: Path, config: dict) -> None:
    (app_dir / ".generated-config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def _read_demo_config(app_dir: Path) -> dict | None:
    p = app_dir / ".generated-config.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _calculator_html(cfg: dict) -> str:
    graphing = bool(cfg.get("graphing"))
    history = bool(cfg.get("history"))
    angle = "rad" if cfg.get("angle_mode") == "rad" else "deg"
    large = " large" if cfg.get("large_keys") else ""
    history_markup = "<aside class='history'><h2>History</h2><div id='history'></div></aside>" if history else ""
    graph_markup = """
    <section class="graph-panel">
      <div class="graph-head"><strong>Graph</strong><input id="fx" value="sin(x)" aria-label="Function of x"><button onclick="plot()">Plot</button></div>
      <canvas id="graph" width="760" height="280"></canvas>
    </section>""" if graphing else ""
    history_js = """
const hist = JSON.parse(localStorage.getItem('calc-history') || '[]');
function renderHistory(){const el=document.getElementById('history'); if(!el)return; el.innerHTML=hist.slice().reverse().map(x=>`<button class="hist" onclick="setExpr(${json.dumps('${x.e}').replace('"${x.e}"','JSON.stringify(x.e)')})"><span>${escapeHtml(x.e)}</span><b>${escapeHtml(String(x.r))}</b></button>`).join('');}
function remember(e,r){hist.push({e,r}); if(hist.length>20)hist.shift(); localStorage.setItem('calc-history',JSON.stringify(hist)); renderHistory();}
""" if history else "function remember(e,r){}\nfunction renderHistory(){}"
    graph_js = """
function plot(){
  const canvas=document.getElementById('graph'), ctx=canvas.getContext('2d'), expr=document.getElementById('fx').value;
  const w=canvas.width,h=canvas.height; ctx.clearRect(0,0,w,h); ctx.strokeStyle='#d7dbe2';ctx.lineWidth=1;
  ctx.beginPath();ctx.moveTo(0,h/2);ctx.lineTo(w,h/2);ctx.moveTo(w/2,0);ctx.lineTo(w/2,h);ctx.stroke();
  ctx.strokeStyle='#111827';ctx.lineWidth=2;ctx.beginPath(); let started=false;
  for(let px=0;px<w;px++){let x=(px-w/2)/35; try{let y=evaluate(expr,{x});let py=h/2-y*35;if(Number.isFinite(py)&&Math.abs(py)<h*4){if(!started){ctx.moveTo(px,py);started=true}else ctx.lineTo(px,py)}else started=false}catch(e){started=false}}
  ctx.stroke();
}
""" if graphing else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Scientific Calculator</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f5f6f8;color:#15171a;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}} .page{{max-width:1100px;margin:0 auto;padding:42px 24px 90px}}
.top{{display:flex;justify-content:space-between;align-items:end;margin-bottom:22px}} h1{{font-size:28px;margin:0}} .muted{{color:#6c727f;font-size:13px}}
.layout{{display:grid;grid-template-columns:minmax(0,1fr) {('280px' if history else '')};gap:18px}} .calc,.history,.graph-panel{{background:white;border:1px solid #e2e5ea;border-radius:22px;box-shadow:0 8px 35px rgba(20,25,35,.06)}}
.calc{{padding:18px}} .display{{width:100%;font-size:30px;text-align:right;padding:24px 18px;border:0;background:#f7f8fa;border-radius:16px;outline:none;margin-bottom:14px}} .result{{min-height:26px;text-align:right;color:#69707d;padding:0 8px 14px;font-size:17px}}
.mode{{display:flex;gap:8px;margin-bottom:12px}} .mode button{{padding:7px 11px}} button{{border:0;background:#f0f2f5;color:#17191d;border-radius:12px;padding:14px;font-size:15px;cursor:pointer}} button:hover{{background:#e5e8ed}} button.op{{background:#e8edf8}} button.eq{{background:#17191d;color:white}} .keys{{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}} .keys.large button{{padding:20px 12px;font-size:17px}}
.history{{padding:18px}} .history h2{{font-size:15px;margin:3px 0 12px}} .hist{{width:100%;display:flex;justify-content:space-between;gap:10px;background:transparent;border-radius:9px;padding:9px 6px;text-align:left}} .hist span{{overflow:hidden;text-overflow:ellipsis}} .hist b{{font-weight:600}}
.graph-panel{{padding:16px;margin-top:18px}} .graph-head{{display:flex;align-items:center;gap:10px;margin-bottom:12px}} .graph-head input{{flex:1;border:1px solid #dfe3e8;border-radius:10px;padding:10px}} canvas{{width:100%;height:280px;background:#fbfbfc;border-radius:14px}}
@media(max-width:760px){{.layout{{grid-template-columns:1fr}}.keys{{grid-template-columns:repeat(4,1fr)}}}}
</style></head><body><main class="page"><div class="top"><div><h1>Scientific Calculator</h1><div class="muted">Local · works offline</div></div></div>
<div class="layout"><section class="calc"><input id="expr" class="display" autocomplete="off" autofocus placeholder="0"><div class="result" id="result">&nbsp;</div>
<div class="mode"><button id="deg" onclick="setMode('deg')">Degrees</button><button id="rad" onclick="setMode('rad')">Radians</button></div>
<div class="keys{large}">
<button onclick="clearAll()">AC</button><button onclick="back()">⌫</button><button onclick="put('(')">(</button><button onclick="put(')')">)</button><button class="op" onclick="put('^')">xʸ</button><button class="op" onclick="put('/')">÷</button>
<button onclick="put('sin(')">sin</button><button onclick="put('cos(')">cos</button><button onclick="put('tan(')">tan</button><button onclick="put('log(')">log</button><button onclick="put('ln(')">ln</button><button class="op" onclick="put('*')">×</button>
<button onclick="put('7')">7</button><button onclick="put('8')">8</button><button onclick="put('9')">9</button><button onclick="put('sqrt(')">√</button><button onclick="put('pi')">π</button><button class="op" onclick="put('-')">−</button>
<button onclick="put('4')">4</button><button onclick="put('5')">5</button><button onclick="put('6')">6</button><button onclick="put('e')">e</button><button onclick="put('%')">%</button><button class="op" onclick="put('+')">+</button>
<button onclick="put('1')">1</button><button onclick="put('2')">2</button><button onclick="put('3')">3</button><button onclick="put('abs(')">abs</button><button onclick="put('!')">n!</button><button class="eq" onclick="calculate()">=</button>
<button onclick="put('0')">0</button><button onclick="put('.')">.</button><button onclick="put('ans')">Ans</button>
</div></section>{history_markup}</div>{graph_markup}</main>
<script>
let mode={json.dumps(angle)}, ans=0; const expr=document.getElementById('expr'), result=document.getElementById('result');
function escapeHtml(s){{return s.replace(/[&<>\"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}}[c]))}}
function put(x){{expr.value+=x;expr.focus();preview()}} function setExpr(x){{expr.value=x;preview()}} function clearAll(){{expr.value='';result.innerHTML='&nbsp;'}} function back(){{expr.value=expr.value.slice(0,-1);preview()}}
function setMode(m){{mode=m;document.getElementById('deg').style.background=m==='deg'?'#dce5f8':'';document.getElementById('rad').style.background=m==='rad'?'#dce5f8':'';preview()}}
function fact(n){{n=Math.floor(n);if(n<0||n>170)throw Error('factorial');let r=1;for(let i=2;i<=n;i++)r*=i;return r}}
function evaluate(raw,vars={{}}){{
 let s=raw.trim(); if(!s)return 0; if(!/^[0-9a-zA-Z_+\\-*/%^().,!\\s]+$/.test(s))throw Error('Unsupported expression');
 s=s.replace(/\\^/g,'**').replace(/(\\d+(?:\\.\\d+)?)!/g,'fact($1)').replace(/\\bpi\\b/gi,'Math.PI').replace(/\\be\\b/g,'Math.E').replace(/\\bans\\b/gi,'ans');
 s=s.replace(/\\bsqrt\\s*\\(/g,'Math.sqrt(').replace(/\\babs\\s*\\(/g,'Math.abs(').replace(/\\bln\\s*\\(/g,'Math.log(').replace(/\\blog\\s*\\(/g,'Math.log10(');
 for(const f of ['sin','cos','tan']){{const re=new RegExp('\\\\b'+f+'\\\\s*\\\\(','g'); s=s.replace(re, mode==='deg'?`Math.${{f}}((Math.PI/180)*`:`Math.${{f}}(`);}}
 if(mode==='deg'){{for(const f of ['sin','cos','tan']){{const needle=`Math.${{f}}((Math.PI/180)*`;let pos=0;while((pos=s.indexOf(needle,pos))>=0){{let start=pos+needle.length,depth=1,i=start;for(;i<s.length;i++){{if(s[i]==='(')depth++;if(s[i]===')'&&--depth===0)break}} if(i<s.length)s=s.slice(0,i)+')'+s.slice(i);pos=i+2;}}}}}}
 const names=Object.keys(vars); const vals=Object.values(vars); return Function('fact','ans',...names,'"use strict"; return ('+s+')')(fact,ans,...vals);
}}
function preview(){{try{{const r=evaluate(expr.value);result.textContent=Number.isFinite(r)?String(+r.toPrecision(12)):String(r)}}catch(e){{result.innerHTML='&nbsp;'}}}}
function calculate(){{try{{const e=expr.value,r=evaluate(e);ans=r;result.textContent=String(+r.toPrecision(12));remember(e,r)}}catch(e){{result.textContent='Check the expression'}}}}
expr.addEventListener('input',preview);expr.addEventListener('keydown',e=>{{if(e.key==='Enter')calculate()}});setMode(mode);
{history_js}
{graph_js}
renderHistory();
</script></body></html>"""


def _notes_html() -> str:
    return """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Notes</title><style>*{box-sizing:border-box}body{margin:0;background:#f6f5f2;font:16px system-ui;color:#222}.wrap{max-width:850px;margin:60px auto;padding:0 24px}h1{font-size:30px}textarea{width:100%;height:65vh;border:1px solid #ddd;border-radius:18px;padding:24px;font:17px/1.6 system-ui;box-shadow:0 12px 40px #0000000d;resize:vertical}.status{color:#777;font-size:13px;margin-top:10px}</style></head><body><main class='wrap'><h1>Notes</h1><textarea id='n' placeholder='Start writing…'></textarea><div class='status' id='s'>Saved locally</div></main><script>const n=document.getElementById('n'),s=document.getElementById('s');n.value=localStorage.getItem('notes')||'';let t;n.oninput=()=>{s.textContent='Saving…';clearTimeout(t);t=setTimeout(()=>{localStorage.setItem('notes',n.value);s.textContent='Saved locally'},250)}</script></body></html>"""


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip(); text = re.sub(r"```$", "", text).strip()
    s, e = text.find("{"), text.rfind("}")
    return text[s:e+1] if s >= 0 and e > s else text
