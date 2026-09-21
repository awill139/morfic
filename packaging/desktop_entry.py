from __future__ import annotations

import os
import platform
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


def _log_path() -> Path:
    home = Path.home() / ".morfic"
    home.mkdir(parents=True, exist_ok=True)
    return home / "launcher.log"


def _record_failure(exc: BaseException) -> Path:
    path = _log_path()
    text = (
        f"\n[{datetime.now(timezone.utc).isoformat()}] Morfic failed to launch\n"
        f"platform={platform.platform()}\n"
        f"python={sys.version}\n"
        + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(text)
    return path


def _show_native_error(message: str) -> None:
    try:
        if sys.platform == "darwin":
            safe = message.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e", f'display alert "Morfic could not start" message "{safe}" as critical'],
                check=False,
                timeout=10,
            )
            return
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, "Morfic could not start", 0x10)
            return
    except Exception:
        pass
    print(message, file=sys.stderr)


def run() -> int:
    try:
        # Import inside the guarded block so missing packaged dependencies are visible
        # instead of producing a silent double-click failure.
        from morfic.desktop import main
        return int(main())
    except BaseException as exc:
        log = _record_failure(exc)
        _show_native_error(f"The app could not start.\n\n{exc}\n\nDiagnostic log: {log}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
