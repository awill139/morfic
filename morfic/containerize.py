from __future__ import annotations

import json
from pathlib import Path
from .models import DeploymentPlan


def ensure_container_recipe(repo: Path, plan: DeploymentPlan) -> Path:
    existing = repo / "Dockerfile"
    if existing.exists():
        return existing
    internal = repo / ".personal-software"
    internal.mkdir(exist_ok=True)
    target = internal / "Dockerfile.generated"
    target.write_text(_dockerfile(plan), encoding="utf-8")
    return target


def _dockerfile(plan: DeploymentPlan) -> str:
    expose = f"EXPOSE {plan.port}\n" if plan.port else ""
    cmd = _cmd(plan.run_command)
    if plan.project_type == "python":
        install = """RUN if [ -f requirements.txt ]; then python -m pip install --no-cache-dir -r requirements.txt; \\
    elif [ -f pyproject.toml ] || [ -f setup.py ]; then python -m pip install --no-cache-dir .; fi
"""
        return f"FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\n{install}{expose}{cmd}"
    if plan.project_type == "node":
        return f"FROM node:22-bookworm-slim\nWORKDIR /app\nCOPY package*.json ./\nRUN npm install\nCOPY . .\n{expose}{cmd}"
    if plan.project_type == "dotnet":
        install = "RUN dotnet restore\n"
        return f"FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build\nWORKDIR /app\nCOPY . .\n{install}{expose}{cmd}"
    if plan.project_type == "static":
        run = plan.run_command or ["python", "-m", "http.server", "8000", "--bind", "0.0.0.0"]
        return f"FROM python:3.12-slim\nWORKDIR /app\nCOPY . .\n{expose}{_cmd(run)}"
    raise RuntimeError(f"Cannot generate a container recipe for project type {plan.project_type}")


def _cmd(argv: list[str]) -> str:
    if not argv:
        return ""
    fixed = ["0.0.0.0" if x in {"127.0.0.1", "localhost"} else x for x in argv]
    return "CMD " + json.dumps(fixed) + "\n"
