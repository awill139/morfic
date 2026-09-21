# Security

## Reporting a vulnerability

Please report security issues **privately** using this repository's *Security → Report a vulnerability*
(GitHub private vulnerability reporting). Do not open a public issue or pull request for a suspected
vulnerability. Include the Morfic version (`/api/status`), your OS, and steps to reproduce.

We aim to acknowledge reports within 3 business days and to ship a fix or mitigation for confirmed
issues as quickly as we can, crediting reporters who want credit.

Supported versions: the latest release only.

## Threat model

Morfic runs software on your computer, some of it written by an AI model or cloned from the internet.
These are the boundaries it tries to hold; a break of any of them is a vulnerability.

**1. The control API is only reachable by the Morfic UI.**
The server binds to `127.0.0.1`. Every request must carry a loopback `Host` header (defeats DNS
rebinding), and state-changing requests must be same-origin (defeats cross-site requests). Web pages you
visit cannot drive Morfic.

**2. Generated apps cannot drive Morfic.**
Generated app content is served from `http://localhost:<port>/content/...`; the control UI and `/api`
are served from `http://127.0.0.1:<port>`. Browsers treat these as different origins, so app code can't
call the control API or read its responses, and the server refuses `/api` on the content origin.
*Known limitation:* all generated apps share the `localhost` origin, so one generated app can read
another's `localStorage`/IndexedDB. Treat generated apps as one trust domain.

**3. Third-party code runs in a container, or not at all.**
Repositories from the marketplace run under Docker/Podman. Single containers are started with
`--cap-drop ALL`, `no-new-privileges` and PID/memory/CPU limits, and their port is published only on
`127.0.0.1`. Docker Compose stacks (Immich, WhoareYou, Cousins Matter, ...) run with the isolation and
port bindings *declared by their own compose file*; Morfic validates the file but does not rewrite it.
Without a container runtime, Morfic refuses to run third-party code on the host unless you set
`MORFIC_ALLOW_HOST_EXECUTION=1`, which is intended for development and is unsafe. Bundled demo repos are
the only exception.
*Known limitation:* containers share your kernel; a container escape is out of scope for Morfic itself.

**4. Marketplace installs are pinned.**
Each catalog entry is pinned to a specific commit, so a moved upstream branch cannot change what is
installed. Pins are reviewed when refreshed. Curated apps are still third-party software: Morfic does
not audit them.

**5. AI-proposed edits are confined to the app's workspace.**
Patches from a model are applied by `repair.apply_patch`, which rejects any path that resolves outside
the app workspace. Modifications are transactional with rollback.

**6. Secrets stay local.**
Provider API keys live in the OS keychain (or a `0600` file if none is available). They are sent only
to the provider you chose, never to a Morfic service.

## Out of scope

- Attacks requiring an already-compromised local account or malware running as the same user.
- Vulnerabilities in third-party catalog apps themselves (report them upstream).
- Behaviour with `MORFIC_ALLOW_HOST_EXECUTION=1`, which explicitly disables container isolation.
