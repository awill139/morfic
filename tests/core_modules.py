"""Unit tests for the storage, repo-inspection and patch-application modules."""
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import os
import tempfile
from pathlib import Path

os.environ["MORFIC_HOME"] = tempfile.mkdtemp(prefix="morfic-test-core-")

from morfic import db
from morfic.inspector import inspect_editable_files, inspect_repo
from morfic.models import DeploymentPlan, PatchAction
from morfic.repair import _extract_json, apply_patch, heuristic_repair

# ---- db ---------------------------------------------------------------------------------------
db.init_db()
a = db.create_app(name="Notes", description="d", intent="i", capabilities=["notes"], source_type="generated", source_url=None, workspace="/tmp/x")
assert db.get_app(a.id).name == "Notes" and any(x.id == a.id for x in db.list_apps())
db.update_app(a.id, status="running", local_url="/content/1/")
assert db.get_app(a.id).status == "running" and db.get_app(a.id).local_url == "/content/1/"
db.add_log(a.id, "stdout", "hello")
assert db.list_logs(a.id)[-1]["message"] == "hello"
db.add_version(a.id, 2, "add dark mode", "done")
assert db.list_versions(a.id)[0]["version"] == 2

assert not db.has_tombstone("builtin", "calc")
db.add_tombstone("builtin", "calc")
assert db.has_tombstone("builtin", "calc") and not db.has_tombstone("builtin", "other")

db.update_app(a.id, status="modifying")
assert db.recover_stale_modifications() == [a.id]
assert db.get_app(a.id).status == "running" and "interrupted" in db.get_app(a.id).last_error
assert db.recover_stale_modifications() == []  # idempotent

db.delete_app_record(a.id)
assert db.get_app(a.id) is None and db.list_logs(a.id) == [] and db.list_versions(a.id) == []

# ---- inspector --------------------------------------------------------------------------------
repo = Path(tempfile.mkdtemp(prefix="morfic-test-repo-"))
(repo / "package.json").write_text('{"name": "demo", "scripts": {"start": "node index.js"}}')
(repo / "README.md").write_text("# demo")
(repo / "src").mkdir(); (repo / "src" / "index.js").write_text("console.log(1)")
(repo / ".git").mkdir(); (repo / ".git" / "config").write_text("secret")
(repo / "node_modules" / "x").mkdir(parents=True); (repo / "node_modules" / "x" / "i.js").write_text("junk")
info = inspect_repo(repo)
assert info["package_json"]["name"] == "demo" and "README.md" in info["important"]
assert "src/index.js" in info["files"] and not any(f.startswith(".git/") for f in info["files"])
(repo / "package.json").write_text("{not json")
assert inspect_repo(repo)["package_json"] is None  # malformed manifests don't crash inspection
snap = inspect_editable_files(repo)
assert "src/index.js" in snap and not any("node_modules" in k or k.startswith(".git") for k in snap)
big = repo / "big.py"; big.write_text("x" * 5000)
assert sum(len(v) for v in inspect_editable_files(repo, max_chars=1000).values()) <= 1000

# ---- repair -----------------------------------------------------------------------------------
fix = Path(tempfile.mkdtemp(prefix="morfic-test-fix-"))
(fix / "helpers.py").write_text("def f(): pass")
(fix / "main.py").write_text("from helper import f\n")
patch = heuristic_repair(fix, "ModuleNotFoundError: No module named 'helper'")
assert patch and patch.file_writes[0]["path"] == "main.py" and "from helpers import" in patch.file_writes[0]["content"]
assert heuristic_repair(fix, "ModuleNotFoundError: No module named 'requests'") is None
assert heuristic_repair(fix, "some other error") is None
assert _extract_json('noise {"a": 1} tail') == '{"a": 1}' and _extract_json("no json") == "no json"

ws = Path(tempfile.mkdtemp(prefix="morfic-test-ws-"))
outside = ws.parent / "outside.txt"
plan = DeploymentPlan(name="n", summary="s", project_type="python", run_command=["python", "a.py"], port=8000)
new = apply_patch(ws, plan, PatchAction(summary="ok", file_writes=[{"path": "sub/a.py", "content": "print(1)"}], run_command=["python", "sub/a.py"], port=9000))
assert (ws / "sub" / "a.py").read_text() == "print(1)" and new.run_command == ["python", "sub/a.py"] and new.port == 9000
assert apply_patch(ws, None, PatchAction(summary="x")) is None

for bad in ("../outside.txt", "/etc/morfic-test-should-not-exist", "sub/../../outside.txt"):
    try:
        apply_patch(ws, plan, PatchAction(summary="evil", file_writes=[{"path": bad, "content": "pwned"}]))
    except RuntimeError:
        pass
    else:
        raise AssertionError(f"write outside workspace allowed: {bad}")
assert not outside.exists() and not Path("/etc/morfic-test-should-not-exist").exists()

outside.write_text("keep me")
try:
    apply_patch(ws, plan, PatchAction(summary="evil", file_deletes=["../outside.txt"]))
except RuntimeError:
    pass
else:
    raise AssertionError("delete outside workspace allowed")
assert outside.read_text() == "keep me"
outside.unlink()

print("CORE MODULES PASS: db lifecycle/recovery, repo inspection, repair heuristics, patch path confinement")
