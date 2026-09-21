from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from .config import settings
from .models import AppManifest, AppRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn():
    c = sqlite3.connect(settings.db_path)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS apps (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          description TEXT NOT NULL,
          requested_intent TEXT NOT NULL,
          capabilities_json TEXT NOT NULL,
          source_type TEXT NOT NULL,
          source_url TEXT,
          status TEXT NOT NULL,
          workspace TEXT NOT NULL,
          local_url TEXT,
          version INTEGER NOT NULL DEFAULT 1,
          manifest_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_error TEXT,
          repair_attempts INTEGER NOT NULL DEFAULT 0,
          pid INTEGER
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          app_id INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          stream TEXT NOT NULL,
          message TEXT NOT NULL
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS versions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          app_id INTEGER NOT NULL,
          version INTEGER NOT NULL,
          created_at TEXT NOT NULL,
          request TEXT NOT NULL,
          summary TEXT NOT NULL
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS tombstones (
          source_type TEXT NOT NULL,
          source_key TEXT NOT NULL,
          created_at TEXT NOT NULL,
          PRIMARY KEY(source_type, source_key)
        )""")


def create_app(*, name: str, description: str, intent: str, capabilities: list[str], source_type: str, source_url: str | None, workspace: str) -> AppRecord:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO apps(name,description,requested_intent,capabilities_json,source_type,source_url,status,workspace,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (name, description, intent, json.dumps(capabilities), source_type, source_url, "created", workspace, now, now),
        )
        app_id = cur.lastrowid
    return get_app(app_id)


def update_app(app_id: int, **fields) -> AppRecord:
    allowed = {"name", "description", "requested_intent", "capabilities_json", "status", "workspace", "local_url", "version", "manifest_json", "last_error", "repair_attempts", "pid", "source_url", "source_type"}
    updates, values = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "manifest_json" and isinstance(v, AppManifest):
            v = json.dumps(v.model_dump())
        if k == "capabilities_json" and isinstance(v, list):
            v = json.dumps(v)
        updates.append(f"{k}=?")
        values.append(v)
    if not updates:
        return get_app(app_id)
    updates.append("updated_at=?")
    values += [_now(), app_id]
    with _conn() as c:
        c.execute(f"UPDATE apps SET {', '.join(updates)} WHERE id=?", values)
    return get_app(app_id)


def _row_to_app(row) -> AppRecord | None:
    if not row:
        return None
    d = dict(row)
    manifest = AppManifest.model_validate(json.loads(d["manifest_json"])) if d.get("manifest_json") else None
    return AppRecord(
        id=d["id"], name=d["name"], description=d["description"], requested_intent=d["requested_intent"],
        capabilities=json.loads(d["capabilities_json"] or "[]"), source_type=d["source_type"], source_url=d["source_url"],
        status=d["status"], workspace=d["workspace"], local_url=d["local_url"], version=d["version"], manifest=manifest,
        created_at=d["created_at"], updated_at=d["updated_at"], last_error=d["last_error"], repair_attempts=d["repair_attempts"], pid=d["pid"],
    )


def get_app(app_id: int) -> AppRecord | None:
    with _conn() as c:
        return _row_to_app(c.execute("SELECT * FROM apps WHERE id=?", (app_id,)).fetchone())


def list_apps() -> list[AppRecord]:
    with _conn() as c:
        return [_row_to_app(r) for r in c.execute("SELECT * FROM apps ORDER BY updated_at DESC").fetchall()]


def add_log(app_id: int, stream: str, message: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO logs(app_id,created_at,stream,message) VALUES(?,?,?,?)", (app_id, _now(), stream, message[-50000:]))


def list_logs(app_id: int, limit: int = 250) -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT created_at,stream,message FROM logs WHERE app_id=? ORDER BY id DESC LIMIT ?", (app_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def add_version(app_id: int, version: int, request: str, summary: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO versions(app_id,version,created_at,request,summary) VALUES(?,?,?,?,?)", (app_id, version, _now(), request, summary))


def list_versions(app_id: int) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT version,created_at,request,summary FROM versions WHERE app_id=? ORDER BY version DESC", (app_id,)).fetchall()]



def delete_app_record(app_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM logs WHERE app_id=?", (app_id,))
        c.execute("DELETE FROM versions WHERE app_id=?", (app_id,))
        c.execute("DELETE FROM apps WHERE id=?", (app_id,))


def add_tombstone(source_type: str, source_key: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO tombstones(source_type,source_key,created_at) VALUES(?,?,?)",
            (source_type, source_key, _now()),
        )


def has_tombstone(source_type: str, source_key: str) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM tombstones WHERE source_type=? AND source_key=?",
            (source_type, source_key),
        ).fetchone() is not None


def recover_stale_modifications() -> list[int]:
    """Recover apps left in `modifying` by a crashed/killed server.

    The last published version remains the known-good version because source changes are
    applied transactionally. On restart there is no live operation to justify keeping
    an app in the transient state.
    """
    with _conn() as c:
        rows = c.execute("SELECT id FROM apps WHERE status='modifying'").fetchall()
        ids = [int(r["id"]) for r in rows]
        now = _now()
        for app_id in ids:
            c.execute(
                "UPDATE apps SET status='running', last_error=?, updated_at=? WHERE id=?",
                ("Previous modification was interrupted; restored the last published version.", now, app_id),
            )
            c.execute(
                "INSERT INTO logs(app_id,created_at,stream,message) VALUES(?,?,?,?)",
                (app_id, now, "recovery", "Recovered stale modifying state after server restart"),
            )
    return ids
