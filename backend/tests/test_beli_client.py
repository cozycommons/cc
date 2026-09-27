"""BeliClient auth/pacing behavior against a local mock Beli server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt as pyjwt
import pytest

from beli import beli_client
from beli.beli_client import BeliClient, BeliError, BeliUnauthorized


def _token():
    return pyjwt.encode({"exp": 9999999999, "sub": "u1"}, "x", algorithm="HS256")


class Handler(BaseHTTPRequestHandler):
    mode = "ok"
    seen = []

    def _json(self, code, obj):
        body = b"" if obj is None else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        Handler.seen.append((self.path, body, self.headers.get("Origin")))
        if self.path == "/api/token/":
            if Handler.mode == "bad-login":
                self._json(400, {"detail": "bad"})
            else:
                self._json(200, {"access": _token(), "refresh": "refresh-1"})
        elif self.path == "/api/token/refresh/":
            self._json(200, {"access": _token()})
        elif self.path == "/api/add-bookmark/":
            self._json(201, None)  # Beli answers writes with an EMPTY body
        else:
            self._json(404, {})

    def do_GET(self):
        Handler.seen.append((self.path, None, self.headers.get("Origin")))
        if Handler.mode == "unauthorized-once" and not getattr(Handler, "flipped", False):
            Handler.flipped = True
            self._json(401, {})
        elif self.path == "/api/user/logged-in/":
            self._json(200, {"uuid": "user-1"})
        else:
            self._json(200, {"results": []})

    def log_message(self, *a):
        pass


@pytest.fixture()
def mock_beli(monkeypatch):
    Handler.seen = []
    Handler.mode = "ok"
    Handler.flipped = False
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setattr(beli_client, "ONBOARD_HOST", base)
    monkeypatch.setattr(beli_client, "API_HOST", base)
    yield base
    server.shutdown()


def test_login_uses_phone_no_for_phone_ids(mock_beli):
    c = BeliClient("+19178872335", "pw")
    c.ensure_access_token()
    path, body, origin = Handler.seen[0]
    assert path == "/api/token/"
    assert body == {"phone_no": "+19178872335", "password": "pw"}
    assert origin == "capacitor://localhost"


def test_login_uses_email_for_email_ids(mock_beli):
    c = BeliClient("a@b.com", "pw")
    c.ensure_access_token()
    assert Handler.seen[0][1] == {"email": "a@b.com", "password": "pw"}


def test_token_cached_and_refreshed(mock_beli):
    c = BeliClient("a@b.com", "pw")
    t1 = c.ensure_access_token()
    t2 = c.ensure_access_token()
    assert t1 == t2
    assert sum(1 for p, _, _ in Handler.seen if p == "/api/token/") == 1


def test_401_triggers_relogin_retry(mock_beli):
    Handler.mode = "unauthorized-once"
    c = BeliClient("a@b.com", "pw")
    out = c.api_with_reauth("/api/user/logged-in/")
    assert out == {"uuid": "user-1"}
    assert sum(1 for p, _, _ in Handler.seen if p == "/api/token/") >= 1


def test_empty_write_body_tolerated(mock_beli):
    c = BeliClient("a@b.com", "pw")
    assert c.api_with_reauth("/api/add-bookmark/", method="POST", body={"a": 1}) is None


def test_bad_login_raises(mock_beli):
    Handler.mode = "bad-login"
    with pytest.raises(BeliError):
        BeliClient("a@b.com", "wrong").ensure_access_token()


def test_probe_credentials(mock_beli):
    user = BeliClient.probe_credentials("a@b.com", "pw")
    assert user["uuid"] == "user-1"


def test_direct_401_raises_unauthorized(mock_beli):
    Handler.mode = "unauthorized-once"
    c = BeliClient("a@b.com", "pw")
    with pytest.raises(BeliUnauthorized):
        c.api("/api/user/logged-in/")
