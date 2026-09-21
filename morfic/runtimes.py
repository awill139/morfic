from __future__ import annotations

import os
import platform
import shutil
import subprocess
import urllib.request
from pathlib import Path

from .config import settings
from .envvars import getenv

DOTNET_CHANNEL = getenv("DOTNET_CHANNEL", "8.0")


def dotnet_executable() -> str | None:
    managed = settings.home / "runtimes" / "dotnet"
    candidates = [
        managed / ("dotnet.exe" if os.name == "nt" else "dotnet"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return shutil.which("dotnet")


def ensure_managed_dotnet(channel: str = DOTNET_CHANNEL) -> str:
    """Install Microsoft's SDK into Morfic's per-user runtime directory.

    This never requires administrator privileges and never modifies the user's
    global PATH. The installer is fetched from Microsoft's documented
    dotnet-install endpoints and executed non-interactively.
    """
    existing = dotnet_executable()
    if existing:
        return existing
    root = settings.home / "runtimes" / "dotnet"
    root.mkdir(parents=True, exist_ok=True)
    cache = settings.home / "runtime-cache"
    cache.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        script = cache / "dotnet-install.ps1"
        _download("https://dot.net/v1/dotnet-install.ps1", script)
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if not powershell:
            raise RuntimeError("Morfic could not bootstrap .NET because Windows PowerShell is unavailable.")
        cmd = [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Channel", channel, "-InstallDir", str(root), "-NoPath"]
    else:
        script = cache / "dotnet-install.sh"
        _download("https://dot.net/v1/dotnet-install.sh", script)
        cmd = ["sh", str(script), "--channel", channel, "--install-dir", str(root), "--no-path"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if p.returncode != 0:
        raise RuntimeError("Morfic could not install the managed .NET SDK. " + ((p.stderr or p.stdout or "")[-2500:]))
    exe = root / ("dotnet.exe" if os.name == "nt" else "dotnet")
    if not exe.exists():
        raise RuntimeError("The managed .NET installer completed but the dotnet executable was not found.")
    return str(exe)


def container_runtime() -> str | None:
    return shutil.which("podman") or shutil.which("docker")


def container_runtime_name() -> str | None:
    runtime = container_runtime()
    return Path(runtime).name if runtime else None


def container_setup_message() -> str:
    system = platform.system()
    if system == "Darwin":
        return "This app needs container support. Install Docker Desktop or Podman Desktop, then Morfic will continue without Terminal commands."
    if system == "Windows":
        return "This app needs container support. Install Docker Desktop or Podman Desktop, then Morfic will continue without Terminal commands."
    return "This app needs Docker or Podman. Install a container engine, then Morfic will continue automatically."


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "Morfic-Runtime/0.7"})
    with urllib.request.urlopen(req, timeout=60) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)
