"""Request guard for the local control API.

The runtime listens on loopback, but a web page open in the user's browser can still reach
loopback ports (DNS rebinding, cross-site requests), and generated apps run in the browser too.
Two defences are applied to every request:

* **Host allow-list** – only loopback host names are served, which defeats DNS rebinding.
* **Origin check** – state-changing requests that carry an ``Origin`` must be same-origin.

Generated app content is served from the ``localhost`` origin while the control UI and ``/api``
live on ``127.0.0.1``. Browsers treat these as different origins, so generated code cannot call
the control API or read its responses.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from .envvars import getenv

CONTROL_HOSTS = frozenset({"127.0.0.1", "::1"})
CONTENT_HOST = "localhost"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Paths that may be served on the content origin. Everything else is control-plane only.
CONTENT_PREFIX = "/content/"


def host_name(host_header: str) -> str:
    """Return the lower-cased host name of a Host header value, without port or brackets."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    if host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host


def _extra_hosts() -> frozenset[str]:
    return frozenset(h.strip().lower() for h in (getenv("ALLOWED_HOSTS", "") or "").split(",") if h.strip())


def is_control_host(name: str) -> bool:
    return name in CONTROL_HOSTS or name in _extra_hosts()


class LocalOnlyGuard:
    """Pure ASGI middleware enforcing the Host allow-list and same-origin writes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host_header = headers.get("host", "")
        name = host_name(host_header)
        path = scope.get("path", "")

        if is_control_host(name):
            pass
        elif name == CONTENT_HOST:
            if not path.startswith(CONTENT_PREFIX):
                return await self._deny(scope, send, "The control API is not available on this origin.")
        else:
            return await self._deny(scope, send, "Unrecognised Host header.")

        origin = headers.get("origin")
        unsafe = scope["type"] == "websocket" or scope.get("method", "GET") not in SAFE_METHODS
        if unsafe:
            if origin is not None:
                if origin == "null" or urlsplit(origin).netloc.lower() != host_header.strip().lower():
                    return await self._deny(scope, send, "Cross-origin requests are not allowed.")
            elif headers.get("sec-fetch-site", "same-origin") in ("cross-site", "same-site"):
                return await self._deny(scope, send, "Cross-origin requests are not allowed.")
        return await self.app(scope, receive, send)

    async def _deny(self, scope, send, message: str):
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        body = ('{"detail":"%s"}' % message).encode()
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
