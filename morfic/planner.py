from __future__ import annotations

import json
import re
from pathlib import Path
from .inspector import inspect_repo
from .llm import llm
from .models import DeploymentPlan, FrontendSpec, UIField
from .prompts import PLAN_REPO_SYSTEM


async def make_plan(repo: Path, intent: str = "") -> DeploymentPlan:
    info = inspect_repo(repo)
    payload = {"user_intent": intent, "repo": info}
    raw = await llm.chat(PLAN_REPO_SYSTEM, json.dumps(payload, indent=2)[:120000], json_mode=True)
    try:
        return DeploymentPlan.model_validate(json.loads(_extract_json(raw)))
    except Exception as e:
        raise RuntimeError(f"Model returned an invalid deployment plan: {e}\n{raw[:1000]}") from e


def heuristic_plan(repo: Path, info: dict | None = None) -> DeploymentPlan:
    info = info or inspect_repo(repo)
    files = set(info["files"])
    readme = (info["important"].get("README.md") or info["important"].get("readme.md") or "").lower()
    compose_file = next((x for x in ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"] if x in files), None)
    if compose_file:
        compose_text = info["important"].get(compose_file, "")
        port = _detect_compose_port(compose_text) or _detect_port(readme)
        return DeploymentPlan(name=repo.name, summary="Containerized multi-service repository", project_type="docker", port=port,
            frontend=FrontendSpec(kind="existing", title=repo.name), detected_files=sorted(files)[:100], compose_file=compose_file)
    if "Dockerfile" in files:
        docker_text = info["important"].get("Dockerfile", "")
        port = _detect_docker_port(docker_text) or _detect_port(readme) or 8000
        return DeploymentPlan(name=repo.name, summary="Dockerized repository", project_type="docker", port=port,
            frontend=FrontendSpec(kind="existing", title=repo.name), detected_files=sorted(files)[:100])
    dotnet_projects = sorted(x for x in files if x.endswith((".csproj", ".fsproj", ".vbproj")))
    solutions = sorted(x for x in files if x.endswith(".sln"))
    if dotnet_projects or solutions:
        target = dotnet_projects[0] if dotnet_projects else solutions[0]
        port = _detect_port(readme) or 5000
        run = ["dotnet", "run", "--project", target, "--urls", f"http://0.0.0.0:{port}"] if dotnet_projects else ["dotnet", "run", "--project", target]
        webish = any(x in readme for x in ["asp.net", "web app", "webapi", "web api", "localhost"])
        return DeploymentPlan(name=repo.name, summary=".NET repository", project_type="dotnet", install_commands=[["dotnet", "restore", target]], run_command=run,
            port=port if webish else None, frontend=FrontendSpec(kind="existing" if webish else "generated_cli", title=repo.name,
                fields=[] if webish else [UIField(name="args", label="Input", kind="text")]), detected_files=sorted(files)[:100])
    if "package.json" in files:
        pkg = info.get("package_json") or {}
        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
        if "start" in scripts:
            run = ["npm", "start"]
        elif "dev" in scripts:
            run = ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
        else:
            run = []
        webish = any(x in readme for x in ["http://localhost", "web app", "next.js", "vite", "react", "express", "vue"]) or any(x in files for x in ["vite.config.js", "vite.config.ts", "next.config.js", "next.config.mjs", "vite.config.mjs"])
        default_port = 5173 if any(x in files for x in ["vite.config.js", "vite.config.ts", "vite.config.mjs"]) else 3000
        port = _detect_port(readme) or (default_port if webish else None)
        return DeploymentPlan(name=pkg.get("name") or repo.name, summary=(pkg.get("description") or "Node repository")[:240], project_type="node",
            install_commands=[["npm", "install"]], run_command=run, port=port,
            frontend=FrontendSpec(kind="existing" if webish else "generated_cli", title=pkg.get("name") or repo.name,
                fields=[] if webish else [UIField(name="args", label="Input", kind="text")]), detected_files=sorted(files)[:100])
    py = any(x in files for x in ["pyproject.toml", "requirements.txt", "setup.py", "main.py", "app.py", "server.py"])
    if py:
        install = []
        if "requirements.txt" in files:
            install.append(["python", "-m", "pip", "install", "-r", "requirements.txt"])
        elif "pyproject.toml" in files or "setup.py" in files:
            install.append(["python", "-m", "pip", "install", "."])
        run, port, webish = _python_entrypoint(repo, files)
        return DeploymentPlan(name=repo.name, summary="Python repository", project_type="python", install_commands=install, run_command=run,
            port=port, frontend=FrontendSpec(kind="existing" if webish else "generated_cli", title=repo.name,
                fields=[] if webish else [UIField(name="args", label="Input", kind="text")]), detected_files=sorted(files)[:100])
    if "index.html" in files:
        return DeploymentPlan(name=repo.name, summary="Static website", project_type="static", run_command=["python", "-m", "http.server", "8000", "--bind", "0.0.0.0"], port=8000,
            frontend=FrontendSpec(kind="existing", title=repo.name), detected_files=sorted(files)[:100])
    return DeploymentPlan(name=repo.name, summary="Repository type could not be inferred automatically", project_type="unknown", frontend=FrontendSpec(kind="none"), detected_files=sorted(files)[:100])


def _python_entrypoint(repo: Path, files: set[str]):
    for filename in ["app.py", "main.py", "server.py"]:
        p = repo / filename
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")[:30000]
        mod = Path(filename).stem
        if "FastAPI(" in text:
            return ["python", "-m", "uvicorn", f"{mod}:app", "--host", "0.0.0.0", "--port", "8000"], 8000, True
        if "Flask(" in text:
            return ["python", "-m", "flask", "--app", mod, "run", "--host", "0.0.0.0", "--port", "5000"], 5000, True
        if "streamlit" in text.lower():
            return ["python", "-m", "streamlit", "run", filename, "--server.address", "0.0.0.0"], 8501, True
        if "gradio" in text.lower():
            return ["python", filename], 7860, True
    for candidate in ["main.py", "app.py", "server.py"]:
        if candidate in files:
            return ["python", candidate], None, False
    return [], None, False


def _detect_docker_port(text: str) -> int | None:
    m = re.search(r"(?im)^\s*EXPOSE\s+(\d{2,5})", text)
    return int(m.group(1)) if m and 1 <= int(m.group(1)) <= 65535 else None


def _detect_port(text: str) -> int | None:
    for pattern in [r"localhost:(\d{2,5})", r"127\.0\.0\.1:(\d{2,5})", r"port\s*[=:]\s*(\d{2,5})"]:
        m = re.search(pattern, text, re.I)
        if m and 1 <= int(m.group(1)) <= 65535:
            return int(m.group(1))
    return None


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    s, e = text.find("{"), text.rfind("}")
    return text[s:e+1] if s >= 0 and e > s else text


def _detect_compose_port(text: str) -> int | None:
    # Covers common short-form mappings such as 8096:8096 and "3000:3000".
    for m in re.finditer(r'(?m)^\s*-\s*["\']?(?:127\.0\.0\.1:)?(\d{2,5}):(\d{2,5})(?:/(?:tcp|udp))?["\']?\s*$', text):
        host = int(m.group(1))
        if 1 <= host <= 65535:
            return host
    return None
