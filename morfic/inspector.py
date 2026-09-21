from __future__ import annotations

import json
from pathlib import Path

IMPORTANT_FILES = [
    "README.md", "readme.md", "pyproject.toml", "requirements.txt", "setup.py", "Pipfile",
    "package.json", "Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", ".env.example",
    "main.py", "app.py", "server.py", "index.html", "global.json",
]


def inspect_repo(repo: Path) -> dict:
    files: list[str] = []
    for p in repo.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            try:
                rel = p.relative_to(repo).as_posix()
            except ValueError:
                continue
            if len(files) < 500:
                files.append(rel)
    important: dict[str, str] = {}
    for name in IMPORTANT_FILES:
        p = repo / name
        if p.exists() and p.is_file():
            try:
                important[name] = p.read_text(encoding="utf-8", errors="replace")[:30000]
            except Exception:
                pass
    package = None
    if "package.json" in important:
        try:
            package = json.loads(important["package.json"])
        except Exception:
            pass
    return {"files": files, "important": important, "package_json": package}


def inspect_editable_files(repo: Path, max_files: int = 24, max_chars: int = 90000) -> dict[str, str]:
    """Return a conservative source snapshot for modification prompts."""
    preferred_ext = {".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json", ".toml", ".yaml", ".yml", ".md"}
    skipped_parts = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next", "coverage"}
    out: dict[str, str] = {}
    total = 0
    candidates = []
    for p in repo.rglob("*"):
        if not p.is_file() or any(x in p.parts for x in skipped_parts) or p.suffix.lower() not in preferred_ext:
            continue
        try:
            rel = p.relative_to(repo).as_posix()
        except ValueError:
            continue
        candidates.append((0 if Path(rel).name in {"README.md", "package.json", "pyproject.toml", "main.py", "app.py", "index.html"} else 1, rel, p))
    for _, rel, p in sorted(candidates)[:max_files * 3]:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if total + len(text) > max_chars:
            text = text[: max(0, max_chars - total)]
        if not text:
            continue
        out[rel] = text
        total += len(text)
        if len(out) >= max_files or total >= max_chars:
            break
    return out
