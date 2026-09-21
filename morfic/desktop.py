from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn

from .app import app
from .config import settings
from .envvars import getenv

HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _port() -> int:
    try:
        return int(getenv("PORT", str(DEFAULT_PORT)))
    except ValueError:
        return DEFAULT_PORT


def _is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def _looks_like_morfic(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/status", timeout=1.5) as response:
            body = response.read().decode("utf-8", errors="replace")
            return "\"version\"" in body and "\"home\"" in body
    except Exception:
        return False


def _wait_until_ready(port: int, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _looks_like_morfic(port):
            return True
        time.sleep(0.15)
    return False


def _show_error(message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Morfic", message)
        root.destroy()
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    port = _port()
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None

    if _is_port_free(port):
        config = uvicorn.Config(
            app,
            host=HOST,
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, name="morfic-server", daemon=True)
        thread.start()
        if not _wait_until_ready(port):
            _show_error("Morfic did not start successfully. Check ~/.morfic for app data and logs.")
            server.should_exit = True
            return 1
    elif not _looks_like_morfic(port):
        _show_error(
            f"Port {port} is already in use by another program. Close that program or set MORFIC_PORT to another port."
        )
        return 1

    url = f"http://{HOST}:{port}"
    try:
        import webview

        # Keep localStorage/cookies for generated apps between launches.
        storage = settings.home / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
        webview.create_window(
            "Morfic",
            url=url,
            width=1240,
            height=820,
            min_size=(880, 620),
            text_select=True,
        )
        webview.start(private_mode=False, storage_path=str(storage))
    except ImportError:
        # Useful when running from source without the desktop extra installed.
        import webbrowser

        webbrowser.open(url)
        if thread is not None:
            try:
                while thread.is_alive():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    except Exception as exc:
        _show_error(f"Could not open the desktop window: {exc}")
        return 1
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
