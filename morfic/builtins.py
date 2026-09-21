from __future__ import annotations

from pathlib import Path

from .config import settings
from .db import add_version, create_app, has_tombstone, list_apps, update_app
from .generator import _calculator_html, _write_demo_config
from .models import AppManifest


def ensure_builtin_apps() -> None:
    if has_tombstone("builtin", "Scientific Calculator"):
        return
    if any(a.source_type == "builtin" and a.name == "Scientific Calculator" for a in list_apps()):
        return
    app = create_app(
        name="Scientific Calculator",
        description="A local scientific calculator with editable source.",
        intent="scientific calculator",
        capabilities=["calculator", "scientific calculator", "math", "trigonometry"],
        source_type="builtin",
        source_url=None,
        workspace=str(settings.apps_dir / "pending"),
    )
    workspace = settings.apps_dir / str(app.id)
    root = workspace / "generated"
    root.mkdir(parents=True, exist_ok=True)
    cfg = {"kind": "calculator", "graphing": False, "history": False, "angle_mode": "deg", "large_keys": False}
    _write_demo_config(root, cfg)
    (root / "index.html").write_text(_calculator_html(cfg), encoding="utf-8")
    manifest = AppManifest(
        name="Scientific Calculator",
        description="A local scientific calculator.",
        requested_intent="scientific calculator",
        capabilities=["calculator", "scientific calculator", "math", "trigonometry"],
        source_type="builtin",
        entry_file="index.html",
        version_notes="Bundled application",
    )
    update_app(app.id, workspace=str(workspace), status="running", local_url=f"/content/{app.id}/", manifest_json=manifest)
    add_version(app.id, 1, "Bundled application", "Preloaded scientific calculator")
