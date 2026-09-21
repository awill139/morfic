# Morfic Runtime v0.7.4 build notes

## Stabilization changes
- User-facing product and desktop artifacts renamed from Personal Software to Morfic. macOS builds now create `Morfic.app` / `Morfic.dmg`; Windows builds create `Morfic.exe`.
- Default local data directory is now `~/.morfic`. Existing `~/.personal-software` data is migrated automatically on first launch when possible.
- Added real Archive, Restore, and permanent Delete lifecycle endpoints and UI controls. Archived apps preserve source/data and appear in a separate Archived section.
- Deleted bundled apps receive a local tombstone so they do not reappear on restart.
- Curated catalog failures no longer silently fall back to generated imitations. The actual deployment error is preserved.
- Curated entries with deterministic deployment plans do not require an AI provider merely to install.
- Jellyfin's prebuilt-image recipe skips source cloning and LLM repo planning entirely.

## Official BYOK

Added a hybrid Official mode with two AI-usage choices:

- **Included AI**: existing fully managed hosted path.
- **Use my API key**: official planning/compatibility remains hosted; source-heavy generation/editing uses a locally stored OpenAI or Anthropic key.

Delegated local BYOK tasks currently include `generate_file`, `repair_generated_file`, `modify_repo`, `localize_strings`, `modify_patch`, and `modify_new_file`. Resolver, repo planning, blueprint planning, impact planning, JSON repair and repo repair remain hosted.

The user's provider secret never enters Morfic backend requests. Local BYOK model calls emit best-effort structured telemetry asynchronously to `/v1/model-events`; telemetry cannot block a successful generation.

## UI

AI Settings now exposes **Included AI / Use my API key** under Official mode plus a BYOK provider selector. Provider readiness requires both an official device token and the selected local provider key when Official BYOK is active.

## Regression results

- OpenAI and Anthropic direct-provider adapters PASS
- provider hard timeout PASS
- hosted invite/task/telemetry PASS
- Official BYOK hosted-planning/local-generation/key-isolation PASS
- catalog + Marketplace PASS
- four canonical materialization paths PASS
- generation recovery PASS
- localization fast path PASS
- targeted large-app patch PASS
- modification cancellation/watchdog/restart recovery PASS
- UI JavaScript parse PASS
- Python compile PASS

## Complex runtime support

- Added `dotnet` to the deployment-plan schema.
- Added deterministic `.csproj`/`.sln` heuristic detection.
- Added per-user managed .NET SDK bootstrap through Microsoft's documented `dotnet-install` endpoint.
- Added first-class Docker Compose detection and lifecycle: validate config, best-effort pull, `up -d`, health check, and `down`.
- Added compose-file metadata to app manifests so stop/restart knows the whole stack.
- Added Dockerfile generation support for .NET repositories when container execution is available.
- Missing container support now produces a consumer-facing setup message rather than shell instructions.

## Complex Marketplace additions

- Jellyfin — personal media/streaming server (.NET; official container builds also exist).
- WhoareYou — private family relationship/timeline app with Docker Compose.
- Cousins Matter — Docker-based private family social network.

## Validation

Runtime regression: PASS for Compose detection/port mapping, .NET project planning, managed-runtime precedence, all four canonical materialization paths, Marketplace/catalog, hosted/BYOK orchestration, generation recovery, localization, targeted modification, watchdog/cancel/restart recovery, provider clients, and provider timeout.

The current build sandbox has neither a container engine nor outbound Git/DNS access, so it cannot honestly perform a fresh end-to-end Docker build of upstream repositories. Upstream deployment contracts were independently checked against their current public repositories/documentation. A real release-machine Docker smoke test remains required before marking a specific complex repo as `verified-local` on macOS/Windows.


## v0.7.4
- Curated catalog entries may carry deterministic deployment plans.
- Jellyfin now bypasses LLM repo planning and uses the official `jellyfin/jellyfin:latest` image.
- Persists Jellyfin config/cache and read-only mounts common local media folders when present.
- AI 180-second timeout remains a per-call safety limit; heavyweight deployment steps retain longer execution timeouts.