from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from .envvars import getenv


def _truthy(name: str, default: str = "0") -> bool:
    return getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    home: Path
    apps_dir: Path
    db_path: Path
    catalog_path: Path
    max_repair_attempts: int
    allow_host_execution: bool
    llm_call_timeout_seconds: int
    modification_timeout_seconds: int


def load_settings() -> Settings:
    explicit = getenv("HOME")
    if explicit:
        home = Path(explicit).expanduser().resolve()
    else:
        home = (Path.home() / ".morfic").resolve()
        legacy = (Path.home() / ".personal-software").resolve()
        if not home.exists() and legacy.exists():
            try:
                shutil.move(str(legacy), str(home))
            except Exception:
                # Preserve existing installs rather than losing access to their apps/data.
                home = legacy
    apps_dir = home / "apps"
    home.mkdir(parents=True, exist_ok=True)
    apps_dir.mkdir(parents=True, exist_ok=True)
    default_catalog = Path(__file__).parent / "catalog" / "catalog.json"
    return Settings(
        home=home,
        apps_dir=apps_dir,
        db_path=home / "runtime.db",
        catalog_path=Path(getenv("CATALOG", default_catalog)).expanduser().resolve(),
        max_repair_attempts=int(getenv("MAX_REPAIRS", "3")),
        allow_host_execution=_truthy("ALLOW_HOST_EXECUTION"),
        llm_call_timeout_seconds=int(getenv("LLM_TIMEOUT", "180")),
        modification_timeout_seconds=int(getenv("MODIFY_TIMEOUT", "360")),
    )


settings = load_settings()
