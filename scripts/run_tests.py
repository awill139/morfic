#!/usr/bin/env python3
"""Run every script in tests/ in its own process with a throwaway data directory.

The tests are standalone scripts (each prints a PASS line and exits non-zero on failure), so
they are run one process each to keep module-level state and the SQLite database isolated.

    python scripts/run_tests.py [name ...]     # e.g. python scripts/run_tests.py security_guard
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 300


def main(argv: list[str]) -> int:
    wanted = {a.removesuffix(".py") for a in argv}
    tests = sorted(p for p in (ROOT / "tests").glob("*.py") if not wanted or p.stem in wanted)
    if not tests:
        print("no tests matched", file=sys.stderr)
        return 2
    failures = []
    for test in tests:
        env = dict(os.environ, PYTHONPATH=str(ROOT), MORFIC_HOME=tempfile.mkdtemp(prefix="morfic-test-home-"), MORFIC_SECRET_STORE="file")
        started = time.time()
        try:
            proc = subprocess.run([sys.executable, str(test)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=TIMEOUT)
            ok, output = proc.returncode == 0, proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as e:
            ok, output = False, f"timed out after {TIMEOUT}s\n{e.stdout or ''}{e.stderr or ''}"
        print(f"{'PASS' if ok else 'FAIL'}  {test.stem:<28} {time.time() - started:5.1f}s")
        if not ok:
            failures.append(test.stem)
            print(output[-4000:], file=sys.stderr)
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
