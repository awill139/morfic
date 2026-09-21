from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from .config import settings
from .db import add_log, add_tombstone, add_version, create_app, delete_app_record, get_app, list_apps, update_app
from .deployer import deploy_github, run_repo, stop_app
from .generator import generate_app, modify_generated, repair_generated_validation, validate_static_app
from .localization import detect_localization_request, propose_localization
from .modifier import propose_repo_modification
from .models import AppManifest, PatchAction, Resolution
from .repair import apply_patch
from .resolver import resolve
from .hosted import emit_event


async def request_software(intent: str) -> tuple[Resolution, object]:
    resolution = await resolve(intent)
    asyncio.create_task(emit_event("resolution_selected", strategy=resolution.strategy, success=True, metadata={"catalog_id": resolution.catalog_entry.id if resolution.catalog_entry else None}))
    if resolution.strategy == "installed":
        app = get_app(resolution.app_id)
        return resolution, app

    if resolution.strategy == "catalog" and resolution.catalog_entry:
        entry = resolution.catalog_entry
        temp_workspace = settings.apps_dir / "pending"
        app = create_app(name=entry.name, description=entry.description, intent=intent, capabilities=entry.capabilities,
            source_type="github", source_url=entry.repo_url, workspace=str(temp_workspace))
        workspace = settings.apps_dir / str(app.id)
        app = update_app(app.id, workspace=str(workspace), status="queued")
        asyncio.create_task(_deploy_catalog(app.id, entry.repo_url, intent, entry.deployment_plan, entry.ref))
        return resolution, app

    name = resolution.generated_name or "Local App"
    temp_workspace = settings.apps_dir / "pending"
    app = create_app(name=name, description=intent, intent=intent, capabilities=resolution.capabilities,
        source_type="generated", source_url=None, workspace=str(temp_workspace))
    workspace = settings.apps_dir / str(app.id)
    app = update_app(app.id, workspace=str(workspace), status="materializing")
    asyncio.create_task(_generate(app.id, intent))
    return resolution, app


async def request_catalog_software(catalog_id: str) -> tuple[Resolution, object]:
    """Materialize one explicitly selected catalog entry.

    Marketplace selection intentionally bypasses intent resolution: the user has already
    selected the implementation. Repo planning, UI adaptation, repair, and generation
    fallback still happen through the normal deployment pipeline.
    """
    from .catalog import load_catalog

    entry = next((x for x in load_catalog() if x.id == catalog_id), None)
    if not entry:
        raise RuntimeError("Catalog item not found")

    existing = next(
        (a for a in list_apps() if a.source_url == entry.repo_url and a.status not in {"failed", "deleted"}),
        None,
    )
    if existing:
        return Resolution(
            strategy="installed",
            reason="This catalog app is already installed locally.",
            app_id=existing.id,
            capabilities=existing.capabilities,
        ), existing

    intent = f"Install {entry.name} from the curated marketplace. {entry.description}"
    temp_workspace = settings.apps_dir / "pending"
    app = create_app(
        name=entry.name,
        description=entry.description,
        intent=intent,
        capabilities=entry.capabilities,
        source_type="github",
        source_url=entry.repo_url,
        workspace=str(temp_workspace),
    )
    workspace = settings.apps_dir / str(app.id)
    app = update_app(app.id, workspace=str(workspace), status="queued")
    asyncio.create_task(_deploy_catalog(app.id, entry.repo_url, intent, entry.deployment_plan, entry.ref))
    resolution = Resolution(
        strategy="catalog",
        reason="Selected directly from the curated marketplace.",
        catalog_entry=entry,
        capabilities=entry.capabilities,
    )
    return resolution, app


async def _deploy_catalog(app_id: int, repo_url: str, intent: str, deployment_plan=None, ref: str | None = None) -> None:
    try:
        asyncio.create_task(emit_event("materialization_started", app_ref=str(app_id), source_type="github", strategy="catalog", stage="deploy"))
        await deploy_github(app_id, repo_url, intent, deployment_plan, ref)
        asyncio.create_task(emit_event("materialization_succeeded", app_ref=str(app_id), source_type="github", strategy="catalog", success=True))
    except Exception as e:
        asyncio.create_task(emit_event("materialization_failed", app_ref=str(app_id), source_type="github", strategy="catalog", success=False, error_class=type(e).__name__, error_message=str(e)))
        # Never silently replace a curated implementation with a generated imitation.
        # If Jellyfin (or any selected catalog app) fails, preserve the real deployment
        # error so the user and telemetry can diagnose the actual missing dependency.
        add_log(app_id, "error", f"Curated implementation failed; no automatic generated fallback: {e}")
        stop_app(app_id)
        update_app(app_id, status="failed", last_error=str(e), pid=None)


async def _generate(app_id: int, intent: str) -> None:
    app = get_app(app_id)
    if not app: return
    content = Path(app.workspace) / "generated"
    try:
        asyncio.create_task(emit_event("materialization_started", app_ref=str(app_id), source_type="generated", strategy="generate", stage="generate"))
        manifest = await generate_app(intent, content)
        local_url = f"/content/{app_id}/"
        update_app(app_id, name=manifest.name, description=manifest.description, capabilities_json=manifest.capabilities,
                   status="running", local_url=local_url, manifest_json=manifest, last_error=None)
        add_log(app_id, "materialize", f"Generated {manifest.name}")
        add_version(app_id, 1, intent, "Initial materialization")
        asyncio.create_task(emit_event("materialization_succeeded", app_ref=str(app_id), source_type="generated", strategy="generate", success=True))
    except Exception as e:
        add_log(app_id, "error", str(e)); update_app(app_id, status="failed", last_error=str(e))
        asyncio.create_task(emit_event("materialization_failed", app_ref=str(app_id), source_type="generated", strategy="generate", success=False, error_class=type(e).__name__, error_message=str(e)))


async def modify_app(app_id: int, request: str) -> dict:
    """Modify an app transactionally.

    Every stage from LLM planning onward lives inside the rollback boundary. This is
    deliberate: provider failures during planning used to leave apps stuck forever in
    `modifying` because the old try/except began only after a patch had been returned.
    """
    app = get_app(app_id)
    if not app or not app.manifest:
        raise RuntimeError("App is not ready to modify")

    manifest = app.manifest
    new_version = app.version + 1
    generated = app.source_type in {"generated", "builtin"}
    root = Path(app.workspace) / ("generated" if generated else "repo")
    backup: Path | None = None
    old_plan = manifest.deployment_plan
    source_changed = False

    update_app(app_id, status="modifying", last_error=None)
    asyncio.create_task(emit_event("modification_started", app_ref=str(app_id), source_type=app.source_type, stage="planning"))
    add_log(app_id, "modify", f"Starting modification: {request[:500]}")

    try:
        if generated:
            target_language = detect_localization_request(request)
            if target_language:
                add_log(app_id, "modify", f"Detected localization request; translating visible strings to {target_language}")
                action = await propose_localization(root, manifest, request, target_language)
            else:
                add_log(app_id, "modify", "Planning the requested source changes")
                action = await modify_generated(root, manifest, request)
            add_log(app_id, "modify", f"Modification plan ready: {action.summary}")
            backup = _backup_targets(app, root, action, new_version)
            apply_patch(root, None, action)
            source_changed = True
            try:
                validate_static_app(root, manifest.entry_file or "index.html")
            except Exception as validation_error:
                add_log(app_id, "repair", f"Modification failed validation; attempting automatic repair: {validation_error}")
                repair_note = await repair_generated_validation(root, manifest, request, str(validation_error))
                add_log(app_id, "repair", repair_note)
            manifest.version_notes = action.summary
            update_app(app_id, status="running", version=new_version, manifest_json=manifest, last_error=None)
            add_version(app_id, new_version, request, action.summary)
            add_log(app_id, "modify", action.summary)
            asyncio.create_task(emit_event("modification_succeeded", app_ref=str(app_id), source_type=app.source_type, success=True, metadata={"version": new_version}))
            return {"ok": True, "summary": action.summary, "version": new_version}

        add_log(app_id, "modify", "Planning changes to the open-source app")
        action = await propose_repo_modification(root, manifest, request)
        add_log(app_id, "modify", f"Modification plan ready: {action.summary}")
        backup = _backup_targets(app, root, action, new_version)
        stop_app(app_id)
        new_plan = apply_patch(root, old_plan, action)
        source_changed = True
        manifest.deployment_plan = new_plan
        manifest.version_notes = action.summary
        update_app(app_id, manifest_json=manifest)
        await run_repo(app_id, root, new_plan, manifest)
        update_app(app_id, version=new_version, status="running", last_error=None)
        add_version(app_id, new_version, request, action.summary)
        add_log(app_id, "modify", action.summary)
        asyncio.create_task(emit_event("modification_succeeded", app_ref=str(app_id), source_type=app.source_type, success=True, metadata={"version": new_version}))
        return {"ok": True, "summary": action.summary, "version": new_version}

    except asyncio.CancelledError:
        if source_changed and backup is not None:
            _restore_backup(root, backup)
        if not generated:
            manifest.deployment_plan = old_plan
            update_app(app_id, manifest_json=manifest)
            # Best effort only; cancellation must never trap the app in an intermediate state.
            try:
                if old_plan:
                    await asyncio.wait_for(asyncio.shield(run_repo(app_id, root, old_plan, manifest)), timeout=45)
            except Exception as restart_error:
                add_log(app_id, "error", f"Could not restart previous version after cancellation: {restart_error}")
        update_app(app_id, status="running", last_error="Modification cancelled.")
        add_log(app_id, "modify", "Modification cancelled; previous version restored")
        asyncio.create_task(emit_event("modification_cancelled", app_ref=str(app_id), source_type=app.source_type, success=False, error_class="CancelledError"))
        raise

    except Exception as original:
        if source_changed and backup is not None:
            _restore_backup(root, backup)
        if not generated:
            manifest.deployment_plan = old_plan
            update_app(app_id, manifest_json=manifest)
            try:
                if old_plan:
                    await asyncio.wait_for(run_repo(app_id, root, old_plan, manifest), timeout=60)
            except Exception as restart_error:
                add_log(app_id, "error", f"Could not restart previous version after failed modification: {restart_error}")
        # A failed change does not make the last known-good application itself failed.
        update_app(app_id, status="running", last_error=str(original))
        add_log(app_id, "error", f"Modification failed and was rolled back: {original}")
        asyncio.create_task(emit_event("modification_failed", app_ref=str(app_id), source_type=app.source_type, success=False, error_class=type(original).__name__, error_message=str(original)))
        raise

def _backup_targets(app, root: Path, action: PatchAction, version: int) -> Path:
    backup = Path(app.workspace) / "versions" / f"before-v{version}"
    if backup.exists(): shutil.rmtree(backup)
    backup.mkdir(parents=True, exist_ok=True)
    meta = {"existing": [], "missing": []}
    for rel_str in {x["path"] for x in action.file_writes} | set(action.file_deletes):
        rel = Path(rel_str)
        src = root / rel
        if src.exists() and src.is_file():
            dst = backup / "files" / rel; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst); meta["existing"].append(rel.as_posix())
        else:
            meta["missing"].append(rel.as_posix())
    (backup / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return backup


def _restore_backup(root: Path, backup: Path) -> None:
    if not backup.exists(): return
    meta = json.loads((backup / "meta.json").read_text(encoding="utf-8"))
    for rel_str in meta.get("existing", []):
        src = backup / "files" / rel_str; dst = root / rel_str; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src, dst)
    for rel_str in meta.get("missing", []):
        p = root / rel_str
        if p.exists() and p.is_file(): p.unlink()


async def archive_app(app_id: int):
    app = get_app(app_id)
    if not app:
        raise RuntimeError("App not found")
    stop_app(app_id)
    add_log(app_id, "lifecycle", "Archived app")
    updated = update_app(app_id, status="archived", pid=None, last_error=None)
    await emit_event("app_archived", app_ref=str(app_id), source_type=app.source_type, success=True)
    return updated


async def restore_app(app_id: int):
    app = get_app(app_id)
    if not app:
        raise RuntimeError("App not found")
    if app.status != "archived":
        return app
    add_log(app_id, "lifecycle", "Restoring archived app")
    if app.source_type in {"generated", "builtin"}:
        updated = update_app(app_id, status="running", pid=None, last_error=None)
    elif app.source_type == "github" and app.manifest and app.manifest.deployment_plan:
        update_app(app_id, status="restoring", last_error=None)
        repo = Path(app.workspace) / "repo"
        await run_repo(app_id, repo, app.manifest.deployment_plan, app.manifest)
        updated = get_app(app_id)
    else:
        raise RuntimeError("This archived app does not have enough deployment information to restore.")
    asyncio.create_task(emit_event("app_restored", app_ref=str(app_id), source_type=app.source_type, success=True))
    return updated


async def delete_app(app_id: int) -> None:
    app = get_app(app_id)
    if not app:
        raise RuntimeError("App not found")
    stop_app(app_id)
    if app.source_type == "builtin":
        add_tombstone("builtin", app.name)
    workspace = Path(app.workspace)
    try:
        if workspace.exists():
            shutil.rmtree(workspace)
    except Exception as e:
        add_log(app_id, "lifecycle", f"Workspace cleanup warning: {e}")
    source_type = app.source_type
    delete_app_record(app_id)
    await emit_event("app_deleted", app_ref=str(app_id), source_type=source_type, success=True)
