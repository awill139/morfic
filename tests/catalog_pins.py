"""Curated catalog entries are pinned to immutable commits and cloned at exactly that revision."""
import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import json
import re
import subprocess
import tempfile
from pathlib import Path

from morfic.catalog import load_catalog
from morfic.gitops import clone_repo

# 1. Every curated entry that installs from source is pinned to a full commit SHA.
curated = json.loads((Path(__file__).resolve().parent.parent / "morfic" / "catalog" / "catalog.json").read_text())
assert curated
for entry in curated:
    assert re.fullmatch(r"[0-9a-f]{40}", entry.get("ref") or ""), f"{entry['id']} is not pinned to a commit"
assert all(e.ref for e in load_catalog() if e.repo_url.startswith("https://"))

# 2. clone_repo(ref=...) checks out that commit, not the branch tip.
work = Path(tempfile.mkdtemp(prefix="morfic-test-pins-"))
src = work / "src"
src.mkdir()
def git(*a, cwd=src):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
git("init", "--quiet", "-b", "main")
(src / "version.txt").write_text("one\n"); git("add", "."); git("commit", "-qm", "one")
pinned = git("rev-parse", "HEAD")
git("tag", "v1")
(src / "version.txt").write_text("two\n"); git("commit", "-qam", "two")
url = src.as_uri()

dest = work / "at-sha"
clone_repo(url, dest, pinned)
assert (dest / "version.txt").read_text() == "one\n"
assert git("rev-parse", "HEAD", cwd=dest) == pinned

dest = work / "at-tag"
clone_repo(url, dest, "v1")
assert (dest / "version.txt").read_text() == "one\n"

dest = work / "unpinned"
clone_repo(url, dest)
assert (dest / "version.txt").read_text() == "two\n"

# 3. A missing revision fails loudly and leaves no half-cloned directory behind.
bad = work / "bad"
try:
    clone_repo(url, bad, "0" * 40)
except RuntimeError:
    assert not bad.exists()
else:
    raise AssertionError("cloning a nonexistent pinned commit must fail")

print("CATALOG PINS PASS: all entries pinned; clone honours sha/tag; unpinned clone unchanged; bad ref fails cleanly")
