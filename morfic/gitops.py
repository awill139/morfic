from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def repo_name_from_url(url: str) -> str:
    path = urlparse(url).path if "://" in url else url
    name = Path(path.rstrip("/")).name or "repo"
    return re.sub(r"\.git$", "", name) or "repo"


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _git(args: list[str], cwd: Path | None = None) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=240)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip() or f"git {args[0]} failed")
    return p.stdout + p.stderr


def clone_repo(url: str, destination: Path, ref: str | None = None) -> str:
    """Shallow-clone `url`. With `ref` (a full commit SHA, tag or branch) the working tree is that
    exact revision, so a curated install does not follow the upstream default branch."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not ref:
        return _git(["clone", "--depth", "1", url, str(destination)])
    destination.mkdir(parents=True)
    try:
        log = _git(["init", "--quiet"], destination)
        _git(["remote", "add", "origin", url], destination)
        log += _git(["fetch", "--depth", "1", "origin", ref], destination)
        log += _git(["checkout", "--quiet", "FETCH_HEAD"], destination)
        if _SHA_RE.match(ref):
            head = _git(["rev-parse", "HEAD"], destination).strip()
            if head != ref:
                raise RuntimeError(f"Checked out {head}, expected pinned commit {ref}")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return log
