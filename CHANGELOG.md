# Changelog

All notable changes to the Morfic runtime are recorded here. This project follows
[Semantic Versioning](https://semver.org/).

## Unreleased

### Security
- The local API now rejects requests whose `Host` is not a loopback name (DNS-rebinding defence) and
  state-changing requests that are not same-origin.
- Generated app content is served from the `localhost` origin while the control UI and `/api` stay on
  `127.0.0.1`, so generated code can no longer call or read the control API.
- .NET projects now respect the host-execution opt-in like every other runtime; without a container
  runtime and without `MORFIC_ALLOW_HOST_EXECUTION` they are refused instead of run on the host.

### Changed
- **Privacy switches for Official modes** (AI Settings → Privacy). *Share usage data* (default on) gates every
  event and per-call log sent to the backend; turning it off sends none of it. *Include prompt and response
  text* (default on) adds redacted, size-capped excerpts. Per-call logs now include provider-reported input and
  output token counts. Previously usage telemetry could not be turned off in Official mode; an existing saved
  "diagnostic context: off" choice is preserved.
- **Breaking:** the Python package is now `morfic` (was `personal_software`). Update imports
  (`from morfic.app import app`) and any `uvicorn personal_software.app:app` command lines. The `morfic`,
  `morfic-desktop` and legacy `personal-software*` commands are unchanged.
- Marketplace catalog entries are pinned to immutable commits (`ref`, `ref_label`) and cloned at exactly
  that revision. Refresh pins with `scripts/update_catalog_pins.py`.
- Settings are read from `MORFIC_*` environment variables. The legacy `PERSONAL_SOFTWARE_*` names still work.
- The version has a single source, `morfic/__version__`; `client_version` in hosted requests
  and `/api/status` now report it (they previously reported stale numbers).
- macOS builds support Developer ID signing and notarization (`MORFIC_CODESIGN_IDENTITY`, `MORFIC_NOTARY_PROFILE`).

### Added
- `morfic/redact.py`: pattern-based secret redaction and size-bounding for anything that may leave the machine as a log.
- `MORFIC_SECRET_STORE=file` to keep secrets out of the OS keychain. The test suite sets it, so running
  tests no longer writes fake tokens into a developer's real keychain.
- CI workflow running the test suite; `scripts/run_tests.py`.
- Tests for the request guard, catalog pinning, storage, repo inspection, patch confinement and the
  host-execution policy.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`.

## 0.7.4
See `BUILD_NOTES.md`.
