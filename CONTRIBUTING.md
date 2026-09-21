# Contributing to Morfic

Thanks for helping. Morfic is a local runtime that acquires, generates, runs and evolves software on a
user's machine, so changes are reviewed with extra care for safety and privacy.

## Set up

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.11+
pip install -e '.[desktop]'
morfic                                                # http://127.0.0.1:8765
```

## Run the tests

```bash
python scripts/run_tests.py                 # everything
python scripts/run_tests.py security_guard  # one test
```

Each file in `tests/` is a standalone script that prints a `... PASS` line and exits non-zero on
failure. `run_tests.py` runs each in its own process with a throwaway `MORFIC_HOME`, so tests never
touch your real `~/.morfic`. (`tests/support/sitecustomize.py` is put on `PYTHONPATH` by the runner; it skips a reverse-DNS lookup that makes Python's built-in HTTP server take ~35 s to start on GitHub's macOS runners.) Tests use local mock servers; they need no API keys and no network
(the catalog pin *refresh* script is the only thing that talks to GitHub).

Please add or update a test with every behaviour change, and a regression test with every bug fix.

## Ground rules

- **Never weaken the guard rails.** The request guard (`morfic/security.py`), the
  host-execution opt-in, workspace path confinement in `repair.apply_patch` and the container flags
  in `deployer.py` exist to protect the user's machine. Changes there need a test and a note in the PR.
- **Keep the privacy boundary.** Nothing should send API keys, app data, local files or whole source
  trees to a Morfic service. See `OPEN_SOURCE_BOUNDARY.md`.
- **Catalog entries are pinned.** To add or update a marketplace app, edit
  `morfic/catalog/catalog.json`, then run `python scripts/update_catalog_pins.py` and commit
  the resulting `ref`/`ref_label`. CI fails on an unpinned entry. Only propose software you have
  reviewed; catalog apps run on users' machines.
- **Version:** bump `__version__` in `morfic/__init__.py` only; it is the single source.
- Settings are read through `morfic/envvars.py` (`MORFIC_*`, falling back to the legacy
  `PERSONAL_SOFTWARE_*`). Don't call `os.getenv` for new settings.
- Keep the diff focused, match the surrounding style, and describe what you tested.

## Reporting bugs and security issues

Bugs: open an issue with your OS, Morfic version (`/api/status`), and the app log.
Security problems: **do not open a public issue** — see `SECURITY.md`.

By contributing you agree that your contributions are licensed under the MIT License.
