#!/usr/bin/env python3
"""Pin every marketplace catalog entry to an immutable commit.

For each entry this picks the newest plain release tag (v1.2.3 / 2025.01.02 style; pre-releases and
moving tags such as `latest` are ignored), resolves it to a commit SHA and writes `ref` (the SHA)
and `ref_label` (the tag) into catalog.json. Repositories with no release tag are pinned to the
current default-branch HEAD.

    python scripts/update_catalog_pins.py            # refresh all pins
    python scripts/update_catalog_pins.py --check    # exit 1 if any entry is unpinned
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "morfic" / "catalog" / "catalog.json"
RELEASE_TAG = re.compile(r"^v?\d+(\.\d+){1,3}$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def ls_remote(url: str, *args: str, pattern: str | None = None) -> list[tuple[str, str]]:
    cmd = ["git", "ls-remote", *args, url] + ([pattern] if pattern else [])
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True).stdout
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]


def resolve_pin(url: str) -> tuple[str, str | None]:
    tags: dict[str, str] = {}
    order: list[str] = []
    for sha, ref in ls_remote(url, "--tags", "--sort=-v:refname"):
        name = ref.removeprefix("refs/tags/")
        peeled = name.endswith("^{}")
        name = name.removesuffix("^{}")
        if not RELEASE_TAG.match(name):
            continue
        if name not in tags:
            order.append(name)
        if peeled or name not in tags:
            tags[name] = sha  # the peeled line is the commit an annotated tag points at
    if order:
        return tags[order[0]], order[0]
    head = ls_remote(url, pattern="HEAD")
    if not head:
        raise RuntimeError(f"{url}: no HEAD")
    return head[0][0], None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only verify that every entry is pinned to a full SHA")
    args = ap.parse_args()
    entries = json.loads(CATALOG.read_text(encoding="utf-8"))
    if args.check:
        bad = [e["id"] for e in entries if not SHA.match(e.get("ref") or "")]
        for b in bad:
            print(f"unpinned: {b}", file=sys.stderr)
        return 1 if bad else 0
    for e in entries:
        sha, label = resolve_pin(e["repo_url"])
        changed = e.get("ref") != sha
        e["ref"], e["ref_label"] = sha, label
        print(f"{'updated' if changed else 'same   '} {e['id']:<18} {label or 'HEAD':<14} {sha[:12]}")
    CATALOG.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
