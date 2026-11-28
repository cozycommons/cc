"""The player origin: a credential-free host that serves only the movie frame.

With ``ARCADE_PLAYER_ORIGIN`` unset, the frame stays on the API origin as before.
With it set, player routes answer only on that host, every other route is absent
there, and requests on it carry no cookies or bearer tokens in either direction.
A movie running in the frame therefore acts with no Commons standing.
"""
import os
import re
from urllib.parse import urlsplit

# Everything the frame document loads, plus the trusted compatibility API that
# its movie calls with a per-launch game capability (never a Commons session).
PLAYER_PATH = re.compile(r"^/arcade/(frame|frame\.js|frame\.css|compat/api|player/[^/]+|assets/.+)$")


def player_origin(value: str | None = None) -> str | None:
    """The configured player origin, or None. Invalid configuration fails loudly."""
    value = (os.environ.get("ARCADE_PLAYER_ORIGIN", "") if value is None else value).strip()
    if not value:
        return None
    parts = urlsplit(value)
    if (parts.scheme not in {"https", "http"} or (parts.scheme == "http" and parts.hostname not in {"localhost", "127.0.0.1", "::1"})
            or not parts.hostname or parts.username or parts.password or parts.path.strip("/") or parts.query or parts.fragment):
        raise RuntimeError("ARCADE_PLAYER_ORIGIN must be an HTTPS origin (HTTP only on loopback) with no path")
    return f"{parts.scheme}://{parts.netloc.lower()}"


class PlayerOriginGuard:
    """ASGI middleware separating the player host from the Commons API host."""

    def __init__(self, app, origin: str | None):
        self.app = app
        self.host = urlsplit(origin).netloc if origin else None

    async def __call__(self, scope, receive, send):
        if self.host is None or scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        host = next((value.decode("latin-1").lower() for name, value in headers if name == b"host"), "")
        on_player = host == self.host
        if on_player != bool(PLAYER_PATH.match(scope.get("path", ""))):
            # Commons routes do not exist on the player host, and player routes do
            # not exist on the API host, so a movie never runs with API-origin standing.
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            await send({"type": "http.response.start", "status": 404,
                        "headers": [(b"content-type", b"text/plain"), (b"cache-control", b"no-store")]})
            return await send({"type": "http.response.body", "body": b"Not found"})
        if not on_player:
            return await self.app(scope, receive, send)
        scope = {**scope, "headers": [(name, value) for name, value in headers if name not in {b"cookie", b"authorization"}]}

        async def without_cookies(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [(name, value) for name, value in message.get("headers", [])
                                                  if name.lower() != b"set-cookie"]}
            await send(message)
        return await self.app(scope, receive, without_cookies)
