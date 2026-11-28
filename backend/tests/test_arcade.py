"""Profile ownership, per-launch run state, and the offline protocol boundary."""
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arcade import wire
from arcade.routes import router, store, current_user, package
from arcade.store import DEFAULTS, DEFAULT_XML


class Profiles:
    """Only profile/session inputs for route tests; persistence is exercised against PostgREST."""
    def __init__(self):
        self.profiles = {}

    def profile(self, user_id):
        return self.profiles.setdefault(user_id, {"settings": dict(DEFAULTS), "legacy_settings": DEFAULT_XML})

    def save_profile(self, user_id, settings, legacy_settings=None):
        self.profiles[user_id] = {"settings": settings, "legacy_settings": legacy_settings or DEFAULT_XML}

    def runs(self, user_id):
        return []

    def launch(self, user_id):
        self.owner = user_id
        return {"id": "test-launch", "token": "test+session/token"}

    def session(self, token):
        return {"user_id": self.owner} if token == "test+session/token" else None


def test_wire_preserves_plus_and_strips_session_fields(tmp_path):
    key = b"test-package-key"
    token = "test+token"
    encrypted = wire.encrypt(token, key)
    assert wire.decrypt(encrypted, key) == token
    xml = "<CreateSprintGameRecordRQ><SessionId>test+token</SessionId><Score>5</Score><Replay>abc</Replay></CreateSprintGameRecordRQ>"
    decoded = wire.decode(("encryptedXml=" + wire.encrypt(xml, key)).encode(), key)
    metrics, record = wire.metrics_and_record(decoded)
    assert metrics["score"] == 5
    assert "test+token" not in record
    assert "<Replay>abc</Replay>" in record
    assert wire.decode(b"xml=<LoginOpenWebRQ><SessionId>a+b=</SessionId></LoginOpenWebRQ>", key).findtext("SessionId") == "a+b="


def test_unknown_operations_and_entity_expansion_rejected():
    with pytest.raises(ValueError):
        wire.decode(b"xml=<DeleteAccountRQ/>", b"test-package-key")
    with pytest.raises(ValueError):
        wire.parse_xml('<!DOCTYPE a [<!ENTITY x "boom">]><a>&x;</a>')


def test_profile_api_requires_sign_in_and_scopes_to_caller(tmp_path):
    app = FastAPI()
    app.include_router(router, prefix="/arcade")
    state = Profiles()
    app.dependency_overrides[store] = lambda: state
    client = TestClient(app)
    assert client.get("/arcade/profile").status_code == 401
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="alice")
    profile = client.get("/arcade/profile").json()
    assert profile["das_ms"] == 200
    profile["arr_ms"] = 17
    assert client.put("/arcade/profile", json=profile).status_code == 200
    assert state.profile("alice")["settings"]["arr_ms"] == 17
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="bob")
    assert client.get("/arcade/profile").json()["arr_ms"] == 35
    assert client.get("/arcade/runs").json() == []
    assert client.put("/arcade/profile", json={**profile, "das_ms": 1}).status_code == 422
    duplicate = {"sprint": {"keys": {"left": "KeyJ", "right": "KeyJ"}, "pad": {}}}
    assert client.put("/arcade/profile", json={**profile, "controls": duplicate}).status_code == 400


@pytest.mark.parametrize("controls", [
    {"sprint": {"keys": {"left": "KeyJ", "right": "KeyJ"}}},
    {"sprint": {"pad": {"left": 0, "right": 0}}},
    {"sprint": {"keys": {"jump": "KeyJ"}}},
    {"sprint": {"pad": {"left": 32}}},
    {"sprint": {"pad": {"left": True}}},
    {"sprint": {"keys": {"left": "Key J"}}},
    {"Bad Game": {"keys": {}}},
    {"sprint": {"keys": {}, "macros": {}}},
])
def test_malformed_bindings_are_rejected(controls):
    from arcade.controls import validate
    assert validate(controls)


def test_bindings_are_stored_per_user_per_game():
    app = FastAPI()
    app.include_router(router, prefix="/arcade")
    state = Profiles()
    app.dependency_overrides[store] = lambda: state
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="alice")
    client = TestClient(app)
    assert client.get("/arcade/controls").json()["binding"]["keys"] == {"left": "KeyJ", "right": "KeyL", "soft": "KeyK"}
    wasd = {"keys": {"left": "KeyA", "right": "KeyD"}, "pad": {"left": 14, "hard": 0}}
    other = {"keys": {"fire": "Space"}, "pad": {}}
    profile = client.get("/arcade/profile").json()
    saved = client.put("/arcade/profile", json={**profile, "controls": {"sprint": wasd, "another-game": other}})
    assert saved.status_code == 200
    described = client.get("/arcade/controls").json()
    assert described["binding"] == wasd
    assert [action["game_key"] for action in described["actions"]][:2] == ["ArrowLeft", "ArrowRight"]
    assert state.profile("alice")["settings"]["controls"]["another-game"] == other
    app.dependency_overrides[current_user] = lambda: SimpleNamespace(id="bob")
    assert client.get("/arcade/controls").json()["binding"]["keys"]["left"] == "KeyJ"


def test_profiles_saved_with_sprint_extra_keys_keep_them():
    from arcade.store import upgrade
    settings = upgrade({**DEFAULTS, "keys": {}})
    assert "keys" not in settings
    assert settings["controls"]["sprint"]["keys"] == {}
    assert settings["controls"]["sprint"]["pad"]["left"] == 14
    kept = {"sprint": {"keys": {"left": "KeyA"}, "pad": {}}}
    assert upgrade({**DEFAULTS, "keys": {"left": "KeyJ"}, "controls": kept})["controls"] == kept


def test_launch_resolves_bindings_to_the_games_own_keys():
    from arcade.controls import resolve
    game = {"left": 65, "right": 68, "hard": 32, "soft": 83, "cw": 88, "ccw": 90, "hold": 16}
    resolved = resolve(game, {"keys": {"left": "KeyJ", "right": "KeyD", "hold": "ArrowUp"},
                              "pad": {"left": 14, "hold": 4, "unknown": 3}})
    assert resolved["targets"]["left"] == {"code": "KeyA", "key": "a", "key_code": 65}
    assert resolved["targets"]["hard"] == {"code": "Space", "key": " ", "key_code": 32}
    assert resolved["targets"]["hold"]["key"] == "Shift"
    # D is already the game's own right key, so the extra binding is dropped.
    assert resolved["keys"] == {"KeyJ": "left", "ArrowUp": "hold"}
    assert resolved["buttons"] == {"14": "left", "4": "hold"}
    arrows = resolve({"left": 37}, {"keys": {}, "pad": {}})["targets"]["left"]
    assert arrows == {"code": "ArrowLeft", "key": "ArrowLeft", "key_code": 37}


def test_frame_has_own_csp_without_general_eval_permission():
    app = FastAPI()
    app.include_router(router, prefix="/arcade")
    response = TestClient(app).get("/arcade/frame")
    policy = response.headers["content-security-policy"]
    assert "'wasm-unsafe-eval'" in policy
    assert "'unsafe-eval'" not in policy
    assert "connect-src 'self'" in policy
    assert response.headers["referrer-policy"] == "no-referrer"

def test_url_encoded_movie_session_is_authenticated(tmp_path):
    from urllib.parse import quote
    app = FastAPI()
    app.include_router(router, prefix="/arcade")
    state = Profiles()
    key = "test-package-key"
    issued = state.launch("alice")
    carried = quote(wire.encrypt(issued["token"], key.encode()), safe="")
    bundle = SimpleNamespace(manifest={"wire_key": key})
    app.dependency_overrides[store] = lambda: state
    app.dependency_overrides[package] = lambda: bundle
    response = TestClient(app).post("/arcade/compat/api", content=(
        f"xml=<LoginOpenWebRQ><SessionId>{carried}</SessionId></LoginOpenWebRQ>"))
    assert response.status_code == 200
    assert "SessionKey" in response.text

def test_saved_custom_controls_drive_the_extra_key_targets():
    from arcade.routes import controls_for
    custom = "<UserSettings><IsCustomControls>true</IsCustomControls><Controls>65,68,32,83,88,90,67,27,0,13</Controls></UserSettings>"
    assert controls_for(custom)["left"] == 65
    assert controls_for(custom)["right"] == 68
    assert controls_for("<UserSettings/>")["left"] == 37


def test_launch_requires_corrected_package_before_overriding_frame_rate(tmp_path):
    from arcade.routes import launch
    from fastapi import HTTPException
    state = Profiles()
    user = SimpleNamespace(id="alice")
    bundle = SimpleNamespace(manifest={"wire_key": "test-package-key", "entry": "game",
                                      "origins": {}, "callbacks": {}, "frame_rates": [0]})
    with pytest.raises(HTTPException) as error:
        launch(user, state, bundle)
    assert error.value.status_code == 409
    bundle.manifest["frame_rates"].append(60)
    launched = launch(user, state, bundle)
    assert launched["frame_rate"] == 60
    assert launched["input"]["keys"] == {"KeyJ": "left", "KeyL": "right", "KeyK": "soft"}
    assert launched["input"]["targets"]["soft"]["code"] == "ArrowDown"


def test_completion_signal_follows_a_successfully_saved_record():
    from arcade.routes import game_reply
    key = 'test-package-key'
    bundle = SimpleNamespace(manifest={'wire_key': key})
    state = Profiles()
    issued = state.launch('alice')
    state.saved = False
    def save_run(session, metrics, record):
        state.saved = True
    state.save_run = save_run
    body = f"xml=<CreateSprintGameRecordRQ><SessionId>{issued['token']}</SessionId><LinesCleared>0</LinesCleared></CreateSprintGameRecordRQ>".encode()
    response = game_reply(body, state, bundle)
    assert state.saved
    assert response.headers['X-Arcade-Run'] == 'finished'
    login = game_reply(f"xml=<LoginOpenWebRQ><SessionId>{issued['token']}</SessionId></LoginOpenWebRQ>".encode(), state, bundle)
    assert 'X-Arcade-Run' not in login.headers
    def fail_save(*args):
        raise ValueError('Record unavailable')
    state.save_run = fail_save
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        game_reply(body, state, bundle)
    assert error.value.status_code == 400
