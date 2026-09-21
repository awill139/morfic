from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from uuid import uuid4

from .config import settings
from .db import add_log, get_app, update_app
from .orchestrator import modify_app


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Operation:
    id: str
    app_id: int
    kind: str
    status: str
    created_at: str
    updated_at: str
    request: str
    summary: str | None = None
    error: str | None = None


_tasks: dict[str, asyncio.Task] = {}
_ops: dict[str, Operation] = {}
_latest_by_app: dict[int, str] = {}


def start_modification(app_id: int, request: str) -> Operation:
    existing = get_active_operation(app_id)
    if existing:
        raise RuntimeError("This app is already being modified.")
    op_id = uuid4().hex
    now = _now()
    op = Operation(op_id, app_id, "modify", "queued", now, now, request)
    _ops[op_id] = op
    _latest_by_app[app_id] = op_id
    _tasks[op_id] = asyncio.create_task(_run_modification(op_id), name=f"modify-app-{app_id}-{op_id[:8]}")
    return op


async def _run_modification(op_id: str) -> None:
    op = _ops[op_id]
    op.status = "running"
    op.updated_at = _now()
    try:
        async with asyncio.timeout(settings.modification_timeout_seconds):
            result = await modify_app(op.app_id, op.request)
        op.status = "succeeded"
        op.summary = str(result.get("summary") or "Modification complete")
    except asyncio.CancelledError:
        op.status = "cancelled"
        op.error = "Modification cancelled."
        raise
    except TimeoutError:
        op.status = "failed"
        op.error = f"Modification exceeded the {settings.modification_timeout_seconds}-second safety limit and was rolled back."
        app = get_app(op.app_id)
        if app and app.status == "modifying":
            update_app(op.app_id, status="running", last_error=op.error)
        add_log(op.app_id, "error", op.error)
    except Exception as e:
        op.status = "failed"
        op.error = str(e)
        app = get_app(op.app_id)
        if app and app.status == "modifying":
            update_app(op.app_id, status="running", last_error=op.error)
    finally:
        op.updated_at = _now()
        _tasks.pop(op_id, None)


def get_operation(op_id: str) -> dict | None:
    op = _ops.get(op_id)
    return asdict(op) if op else None


def get_latest_operation(app_id: int) -> dict | None:
    op_id = _latest_by_app.get(app_id)
    return get_operation(op_id) if op_id else None


def get_active_operation(app_id: int) -> dict | None:
    data = get_latest_operation(app_id)
    if data and data["status"] in {"queued", "running"}:
        return data
    return None


async def cancel_modification(app_id: int) -> dict:
    active = get_active_operation(app_id)
    if not active:
        return {"ok": False, "message": "No active modification."}
    task = _tasks.get(active["id"])
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    app = get_app(app_id)
    if app and app.status == "modifying":
        update_app(app_id, status="running", last_error="Modification cancelled.")
    return {"ok": True, "message": "Modification cancelled."}
