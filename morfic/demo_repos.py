from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import settings
from .models import CatalogEntry


def ensure_demo_repos() -> list[CatalogEntry]:
    root = settings.home / "demo-repos"
    root.mkdir(parents=True, exist_ok=True)
    frontend = root / "unit-converter"
    cli = root / "text-statistics"
    _ensure_frontend_repo(frontend)
    _ensure_cli_repo(cli)
    return [
        CatalogEntry(
            id="demo-unit-converter",
            name="Unit Converter",
            description="Small local unit conversion web app from a curated Git repository.",
            capabilities=["unit conversion", "convert units", "length", "weight", "temperature"],
            keywords=["unit converter", "convert units", "convert miles", "temperature converter"],
            repo_url=frontend.as_uri(),
            project_hint="static",
            notes="Bundled demo Git repository with an existing frontend.",
        ),
        CatalogEntry(
            id="demo-text-statistics",
            name="Text Statistics",
            description="CLI-only text analyzer used to demonstrate automatic frontend generation.",
            capabilities=["text statistics", "word count", "character count", "reading time"],
            keywords=["word count", "text statistics", "count words", "analyze text", "reading time"],
            repo_url=cli.as_uri(),
            project_hint="python",
            notes="Bundled demo Git repository with no frontend.",
        ),
    ]


def _git_init(path: Path) -> None:
    if (path / ".git").exists():
        return
    subprocess.run(["git", "init"], cwd=path, capture_output=True, text=True, check=True)
    subprocess.run(["git", "config", "user.email", "demo@local"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Morfic Demo"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "demo app"], cwd=path, capture_output=True, text=True, check=True)


def _ensure_frontend_repo(path: Path) -> None:
    if path.exists() and not (path / ".git").exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    index = path / "index.html"
    if not index.exists():
        index.write_text(r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Unit Converter</title><style>*{box-sizing:border-box}body{margin:0;background:#f4f6f8;font:16px system-ui;color:#15171a}.wrap{max-width:720px;margin:8vh auto;padding:24px}.card{background:white;border:1px solid #e1e4e8;border-radius:24px;padding:28px;box-shadow:0 18px 50px #0000000c}h1{margin-top:0}.row{display:grid;grid-template-columns:1fr 150px;gap:10px;margin:12px 0}input,select{padding:14px;border:1px solid #d5d9df;border-radius:12px;font:inherit}.result{font-size:26px;font-weight:700;margin-top:22px}</style></head><body><main class="wrap"><section class="card"><h1>Unit Converter</h1><p>Convert common length units locally.</p><div class="row"><input id="value" type="number" value="1" step="any"><select id="from"><option value="m">meters</option><option value="km">kilometers</option><option value="mi">miles</option><option value="ft">feet</option></select></div><div class="row"><div></div><select id="to"><option value="mi">miles</option><option value="km">kilometers</option><option value="m">meters</option><option value="ft">feet</option></select></div><div class="result" id="result"></div></section></main><script>const factors={m:1,km:1000,mi:1609.344,ft:.3048};const els=['value','from','to'].map(id=>document.getElementById(id));function calc(){const v=Number(els[0].value)||0;document.getElementById('result').textContent=(v*factors[els[1].value]/factors[els[2].value]).toLocaleString(undefined,{maximumFractionDigits:6})+' '+els[2].value}els.forEach(e=>e.oninput=calc);calc()</script></body></html>''', encoding="utf-8")
        (path / "README.md").write_text("# Unit Converter\n\nA static browser-based unit converter. Open index.html or serve the directory with a static HTTP server.\n", encoding="utf-8")
    _git_init(path)


def _ensure_cli_repo(path: Path) -> None:
    if path.exists() and not (path / ".git").exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    main = path / "main.py"
    if not main.exists():
        main.write_text(r'''import json, re, sys

def stats(text):
    words=re.findall(r"\b[\w'-]+\b", text)
    sentences=[x for x in re.split(r"[.!?]+", text) if x.strip()]
    return {"words":len(words),"characters":len(text),"sentences":len(sentences),"estimated_reading_minutes":round(len(words)/220,2)}

if __name__ == "__main__":
    text=sys.argv[1] if len(sys.argv)>1 else sys.stdin.read()
    print(json.dumps(stats(text), indent=2))
''', encoding="utf-8")
        (path / "README.md").write_text("# Text Statistics\n\nCLI-only Python utility. Usage: `python main.py \"some text\"`. Prints JSON containing word, character, sentence, and estimated reading-time statistics. No web frontend is included.\n", encoding="utf-8")
    _git_init(path)
