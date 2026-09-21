# Morfic Runtime

Open-source local runtime for turning a request into running, editable personal software.

Describe what you want. Morfic resolves an existing local app, installs a curated open-source
implementation, or generates a small app; deploys it on your machine; repairs failures; and later
evolves it with surgical, reversible edits. Apps run locally, and the runtime owns validation,
rollback, lifecycle and permissions.

> **Status:** early (0.7). Expect rough edges. It executes software on your computer — please read
> [Security model](#security-model) before installing catalog apps.

## Quick start (community mode)

Requires Python 3.11+ and Git. Docker or Podman is needed to run marketplace apps (see
[Security model](#security-model)).

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e '.[desktop]'          # drop [desktop] to use the browser instead of a native window
morfic                               # or: morfic-desktop
```

`morfic-desktop` opens a native window; `morfic` serves `http://127.0.0.1:8765` for your browser. In **AI Settings** pick
**OpenAI** or **Anthropic** and paste your own API key. That's it — no Morfic account needed.

Desktop installers (macOS `.dmg`, Windows `.exe`) are produced by the *Build desktop installers*
workflow and `scripts/build_*`. Unsigned builds trigger an OS warning; see [PACKAGING.md](PACKAGING.md).

## AI modes

| Mode | Who runs the models | What you need |
|---|---|---|
| **Community BYOK** (default) | Your OpenAI/Anthropic key, called directly from your machine, using the open prompts in this repo | A provider API key |
| **Official · Managed** | Morfic's hosted service | An invite code |
| **Official · BYOK** | Hosted service plans; your key does generation and edits locally | An invite code + a provider key |

**Official modes are invite-only** while the hosted service is in private testing, so
`api.morfic.io` will reject you without a tester invite code. Everyone else should use Community BYOK.
The official build's only difference is that it defaults to the hosted service URL; no company
credential is embedded in it.

Details of what is open and what is hosted: [OPEN_SOURCE_BOUNDARY.md](OPEN_SOURCE_BOUNDARY.md).
Developing against a local orchestrator: [HOSTED_DEV.md](HOSTED_DEV.md).

## Privacy and telemetry

- **Community BYOK:** Morfic sends nothing to any Morfic server. Your requests and the code context
  needed for a task go straight to the provider you chose, under your key.
- **Official · Managed:** the text of your requests and the code context each task needs are sent to the
  hosted service and on to its model providers — that is how the service does the work. This cannot be
  switched off while you use Included AI.
- **Official · BYOK:** the hosted service sees planning requests. Your provider key and the
  source-heavy generation/edit calls stay on your machine.

**Sharing usage data (Official modes only, on by default).** *AI Settings → Privacy* has two switches:

1. **Share usage data with Morfic** — when on, each AI call and app event is logged to the backend with
   the task name, provider/model, request/response sizes, **input/output token counts**, latency,
   success or failure, a bounded error message (≤1200 characters, which can contain fragments of a local
   error or path), your OS/architecture, the client version and a random per-install ID. When you turn it
   **off**, none of this is sent — no events and no per-call logs. (Managed AI requests are the AI
   working, not logging, so they still go to the service.)
2. **Include prompt and response text** (on by default, only applies while sharing is on) — also sends
   the text of the prompts you sent to the AI and the responses you got back. Text is shortened to
   20,000 characters per side, and API keys, bearer tokens, passwords, credentials in URLs and private
   keys are stripped **on your machine** before anything is sent. That redaction is pattern-based and
   can't catch everything: your prompts contain your code and your requests, so turn this off if you
   don't want them shared. The operator of the backend must also enable content retention server-side.

Never sent: your provider API keys, app databases, your documents or other local files. Community BYOK
is unaffected by these switches because it never contacts a Morfic server. If you upgraded from a
version where *diagnostic context* was off, your saved choice is kept.

Provider keys are kept in your OS keychain, or in a `0600` file when no keychain is available.

## Security model

Morfic runs code that was written by a model or cloned from the internet. In short:

- The API listens on `127.0.0.1` only and rejects non-loopback `Host` headers and cross-origin writes,
  so websites you visit can't control it.
- Generated apps are served from a different browser origin (`localhost`) than the control UI
  (`127.0.0.1`), so they can't call the control API.
- Marketplace apps run in containers (single containers get dropped capabilities, `no-new-privileges` and
  resource limits; Compose stacks use their own file's settings). Without Docker/Podman Morfic refuses
  rather than running them on your host, unless you set `MORFIC_ALLOW_HOST_EXECUTION=1` (unsafe).
- Marketplace entries are pinned to reviewed commits. Model-proposed file edits can't escape the app's
  workspace.

Full threat model, known limitations and how to report a vulnerability: [SECURITY.md](SECURITY.md).

## Complex runtimes

- **Docker / Compose:** `docker-compose.yml`, `docker-compose.yaml`, `compose.yml` and `compose.yaml`
  are first-class deployment plans: Morfic validates the file, starts the stack as a unit, health-checks
  the published port and tears the stack down as a unit. Docker/Podman is intentionally not installed
  silently (privileged setup and licensing need your consent); without an engine Morfic shows a
  human-readable setup message.
- **.NET:** `.csproj`, `.fsproj`, `.vbproj` and `.sln` repositories are recognised. If no system `dotnet`
  exists, Morfic can bootstrap Microsoft's SDK into `~/.morfic/runtimes/dotnet` without touching your
  PATH or needing administrator rights. Like all host-side execution, it is refused unless you opt in
  or a container runtime is available.

## Marketplace

The catalog (`morfic/catalog/catalog.json`) lists curated open-source apps such as
CyberChef, Stirling-PDF, Mealie, Actual Budget, Immich and Jellyfin. Each entry is pinned to a commit
(`ref`) taken from an upstream release tag (`ref_label`). Maintainers refresh pins with
`python scripts/update_catalog_pins.py`; CI fails if an entry is unpinned. Heavyweight services such as
Immich or Jellyfin are deliberately not chosen for tiny one-off requests.

## Configuration

Settings come from `MORFIC_*` environment variables; the legacy `PERSONAL_SOFTWARE_*` names still work.
The saved AI Settings live in `~/.morfic/provider.json`.

| Variable | Purpose | Default |
|---|---|---|
| `MORFIC_HOME` | Data directory | `~/.morfic` |
| `MORFIC_PORT` | Desktop app port | `8765` |
| `MORFIC_PROVIDER` | `openai`, `anthropic` or `official` | from AI Settings |
| `MORFIC_OPENAI_MODEL` / `MORFIC_ANTHROPIC_MODEL` | Model names | see AI Settings |
| `MORFIC_OPENAI_BASE_URL` / `MORFIC_ANTHROPIC_BASE_URL` | Provider endpoints | vendor defaults |
| `MORFIC_OFFICIAL_URL` | Hosted service URL (Official modes) | `http://127.0.0.1:8770` |
| `MORFIC_OFFICIAL_AI_MODE` | `managed` or `byok` | `managed` |
| `MORFIC_ALLOW_HOST_EXECUTION` | Run third-party code on the host (**unsafe**) | off |
| `MORFIC_SECRET_STORE` | `file` keeps provider keys in a `0600` file in `MORFIC_HOME` instead of the OS keychain | keychain |
| `MORFIC_ALLOWED_HOSTS` | Extra `Host` names to accept, comma-separated (e.g. behind a trusted proxy) | none |
| `MORFIC_LLM_TIMEOUT`, `MORFIC_MODIFY_TIMEOUT`, `MORFIC_MAX_REPAIRS` | Timeouts / repair attempts | `180`, `360`, `3` |

## Development

```bash
python scripts/run_tests.py          # whole suite; see CONTRIBUTING.md
```

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## Building installers

See [PACKAGING.md](PACKAGING.md) for macOS/Windows builds, the official (hosted-default) build,
code signing and notarization.

## License

MIT — see [LICENSE](LICENSE).
