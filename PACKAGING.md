# Packaging

## Community build

The repository defaults to community mode and exposes Official + BYOK choices in AI Settings.

macOS:
```bash
./scripts/build_mac.sh
```

Windows:
```powershell
.\scripts\build_windows.ps1
```

## Official website build

Official artifacts contain only the public orchestrator URL. They do **not** contain OpenAI/Anthropic credentials or a reusable backend secret.

macOS:
```bash
MORFIC_DISTRIBUTION=official \
MORFIC_OFFICIAL_URL=https://api.morfic.io \
./scripts/build_mac.sh
```

Windows PowerShell:
```powershell
$env:MORFIC_DISTRIBUTION="official"
$env:MORFIC_OFFICIAL_URL="https://api.morfic.io"
.\scripts\build_windows.ps1
```

The build scripts temporarily write the public distribution config for PyInstaller and restore the source-tree community config afterward.

End users download the `.dmg`/`.exe`, open the app, enter a tester invite code once, and use the product without seeing a terminal or provider API key.

The legacy `PERSONAL_SOFTWARE_DISTRIBUTION` / `PERSONAL_SOFTWARE_OFFICIAL_URL` names are still accepted by the build scripts.

## Signing and notarization (macOS)

By default `build_mac.sh` produces an **ad-hoc signed** app. It runs on the machine that built it, but on
other Macs Gatekeeper will warn (users must right-click → Open). For a distributable build you need an
Apple Developer ID:

```bash
export MORFIC_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
# one-time: xcrun notarytool store-credentials morfic-notary --apple-id ... --team-id ... --password ...
export MORFIC_NOTARY_PROFILE=morfic-notary
./scripts/build_mac.sh
```

With `MORFIC_CODESIGN_IDENTITY` the app is signed with the hardened runtime and
`packaging/entitlements.plist`, and the DMG is signed too. With `MORFIC_NOTARY_PROFILE` the DMG is
submitted to Apple's notary service and the ticket is stapled. Without a profile the DMG is signed but
not notarized (the script says so).

## Windows

`build_windows.ps1` produces an **unsigned** `Morfic.exe`. Windows SmartScreen will warn ("Windows
protected your PC → More info → Run anyway") until the executable is Authenticode-signed with your
certificate (e.g. `signtool sign /fd SHA256 /tr <timestamp-url> /td SHA256 /a dist\Morfic.exe`).

## CI

`.github/workflows/tests.yml` runs the test suite on every push and pull request.
`.github/workflows/build-desktop.yml` builds unsigned community installers on `v*` tags.
