"""The separate player origin: host separation, credential stripping, frame policy."""
import struct
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from arcade.origin import PlayerOriginGuard, player_origin
from arcade.routes import router, launch
from arcade.store import DEFAULTS, DEFAULT_XML
from tests.arcade_hostile_movie import attempts, hostile_swf

PLAYER = "https://play.example.test"


def app_with(origin):
    app = FastAPI()

    # Registered before the Arcade router so the probe wins its asset path.
    @app.get("/arcade/profile-probe")
    @app.get("/arcade/assets/probe")
    def probe(request: Request):
        response = Response("ok")
        response.headers["x-saw-cookie"] = str("cookie" in request.headers)
        response.headers["x-saw-authorization"] = str("authorization" in request.headers)
        response.set_cookie("commons", "secret")
        return response

    app.include_router(router, prefix="/arcade")
    app.add_middleware(PlayerOriginGuard, origin=origin)
    return app


@pytest.mark.parametrize("value", ["http://play.example.test", "https://play.example.test/arcade",
                                   "https://user@play.example.test", "https://play.example.test?x=1", "play.example.test"])
def test_player_origin_must_be_a_bare_https_origin(value):
    with pytest.raises(RuntimeError):
        player_origin(value)


def test_player_origin_normalizes_and_allows_loopback_http():
    assert player_origin("") is None
    assert player_origin("https://Play.Example.test/") == "https://play.example.test"
    assert player_origin("http://localhost:8877") == "http://localhost:8877"


def test_player_host_serves_only_player_routes_without_credentials():
    client = TestClient(app_with(PLAYER), base_url=PLAYER)
    headers = {"cookie": "commons=secret", "authorization": "Bearer commons-token"}
    response = client.get("/arcade/assets/probe", headers=headers)
    assert response.status_code == 200
    assert response.headers["x-saw-cookie"] == "False"
    assert response.headers["x-saw-authorization"] == "False"
    assert "set-cookie" not in response.headers
    for path in ["/arcade/profile-probe", "/arcade/profile", "/arcade/sessions", "/account", "/health", "/"]:
        assert client.get(path, headers=headers).status_code == 404, path


def test_api_host_no_longer_serves_the_player_frame():
    client = TestClient(app_with(PLAYER), base_url="https://api.example.test")
    for path in ["/arcade/frame", "/arcade/frame.js", "/arcade/assets/probe", "/arcade/player/ruffle.js", "/arcade/compat/api"]:
        assert client.get(path).status_code == 404, path
    response = client.get("/arcade/profile-probe", headers={"cookie": "commons=secret"})
    assert response.status_code == 200
    assert response.headers["x-saw-cookie"] == "True"


def test_unconfigured_guard_keeps_the_frame_on_the_api_origin():
    client = TestClient(app_with(None), base_url="https://api.example.test")
    assert client.get("/arcade/frame").status_code == 200
    assert client.get("/arcade/profile-probe").headers["x-saw-cookie"] == "False"


def test_player_frame_is_embedded_only_by_commons_pages(monkeypatch):
    monkeypatch.setenv("ARCADE_PLAYER_ORIGIN", PLAYER)
    monkeypatch.setenv("CORS_EXTRA_ORIGINS", "https://commons.example.test")
    client = TestClient(app_with(PLAYER), base_url=PLAYER)
    policy = client.get("/arcade/frame").headers["content-security-policy"]
    ancestors = policy.split("frame-ancestors ")[1].split()
    assert "https://commons.example.test" in ancestors
    assert PLAYER not in ancestors
    assert "connect-src 'self';" in policy and "'unsafe-eval'" not in policy
    script = client.get("/arcade/frame.js").text
    assert '"https://commons.example.test"' in script and PLAYER not in script
    assert "'*'" not in script


class Profiles:
    def profile(self, user_id):
        return {"settings": dict(DEFAULTS), "legacy_settings": DEFAULT_XML}

    def launch(self, user_id):
        return {"id": "launch", "token": "token"}


def bundle(trusted):
    return SimpleNamespace(trusted=trusted, manifest={"wire_key": "test-package-key", "entry": "game", "origins": {},
                                                      "callbacks": {}, "frame_rates": [0, 60]})


def test_untrusted_games_launch_only_on_the_player_origin(monkeypatch):
    from fastapi import HTTPException
    user = SimpleNamespace(id="alice")
    monkeypatch.delenv("ARCADE_PLAYER_ORIGIN", raising=False)
    with pytest.raises(HTTPException) as error:
        launch(user, Profiles(), bundle(False))
    assert error.value.status_code == 503
    legacy = launch(user, Profiles(), bundle(True))
    assert legacy["trusted"] is True and "frame" not in legacy
    monkeypatch.setenv("ARCADE_PLAYER_ORIGIN", PLAYER)
    isolated = launch(user, Profiles(), bundle(False))
    assert isolated["trusted"] is False
    assert isolated["frame"] == PLAYER + "/arcade/frame"


def test_frame_locks_down_untrusted_movies():
    from pathlib import Path
    script = (Path(__file__).parents[1] / "arcade" / "frame.js").read_text()
    assert "const trusted = launch.trusted === true;" in script
    assert "allowScriptAccess: trusted, allowNetworking: trusted ? 'all' : 'internal'" in script
    assert "openUrlMode: 'deny'" in script


def test_hostile_fixture_is_a_well_formed_avm1_movie():
    movie = hostile_swf("https://api.example.test")
    assert movie[:4] == b"FWS\x08"
    assert struct.unpack("<I", movie[4:8])[0] == len(movie)
    for url in attempts("https://api.example.test").values():
        assert url.encode() + b"\x00\x00_level0\x00\x9a\x01\x00\x80" in movie
    assert b"ExternalInterface" in movie and b"javascript:" in movie
