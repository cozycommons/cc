"""Profile ownership, per-launch run state, and the offline protocol boundary."""
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from arcade import wire
from arcade.routes import router, store, current_user, package
from arcade.store import Store


def test_profiles_and_runs_survive_reopen_without_crossing_owners(tmp_path):
    state = Store(tmp_path / "arcade.sqlite")
    alice = state.profile("alice")["settings"]
    alice["das_ms"] = 150
    state.save_profile("alice", alice)
    a = state.launch("alice")
    b = state.launch("bob")
    a_session, b_session = state.session(a["token"]), state.session(b["token"])
    first = state.start_run(a_session)
    second = state.start_run(b_session)
    state.save_run(a_session, {"Score": "100"})
    reopened = Store(tmp_path / "arcade.sqlite")
    assert reopened.profile("alice")["settings"]["das_ms"] == 150
    assert reopened.profile("bob")["settings"]["das_ms"] == 200
    assert reopened.runs("alice")[0]["id"] == first
    assert reopened.runs("bob")[0]["id"] == second
    assert reopened.runs("bob")[0]["metrics"] == {}
    assert reopened.session("unissued") is None


def test_two_tabs_have_separate_active_runs(tmp_path):
    state = Store(tmp_path / "state.sqlite")
    tabs = [state.session(state.launch("alice")["token"]) for _ in range(2)]
    ids = [state.start_run(tab) for tab in tabs]
    state.save_run(tabs[0], {"Score": "5"})
    state.save_run(tabs[1], {"Score": "9"})
    runs = {row["id"]: row["metrics"]["Score"] for row in state.runs("alice")}
    assert runs == {ids[0]: "5", ids[1]: "9"}


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
    state = Store(tmp_path / "state.sqlite")
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
    assert client.put("/arcade/profile", json={**profile, "keys":{"left":"KeyJ","right":"KeyJ"}}).status_code == 400


def test_expired_game_cannot_write(tmp_path):
    import hashlib
    state = Store(tmp_path / "state.sqlite")
    session = state.launch("alice")
    with state.connect() as db:
        db.execute("UPDATE sessions SET expires_at=0 WHERE token_hash=?",
                   (hashlib.sha256(session["token"].encode()).hexdigest(),))
    assert state.session(session["token"]) is None


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
    state = Store(tmp_path / "state.sqlite")
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


def test_old_profile_receives_frame_rate_default_without_losing_handling(tmp_path):
    import json
    state = Store(tmp_path / "state.sqlite")
    state.profile("alice")
    with state.connect() as db:
        db.execute("UPDATE profiles SET settings=? WHERE user_id=?",
                   (json.dumps({"das_ms": 150, "arr_ms": 17}), "alice"))
    settings = state.profile("alice")["settings"]
    assert settings["frame_rate"] == 60
    assert (settings["das_ms"], settings["arr_ms"]) == (150, 17)


def test_launch_requires_corrected_package_before_overriding_frame_rate(tmp_path):
    from arcade.routes import launch
    from fastapi import HTTPException
    state = Store(tmp_path / "state.sqlite")
    user = SimpleNamespace(id="alice")
    bundle = SimpleNamespace(manifest={"wire_key": "test-package-key", "entry": "game",
                                      "origins": {}, "callbacks": {}, "frame_rates": [0]})
    with pytest.raises(HTTPException) as error:
        launch(user, state, bundle)
    assert error.value.status_code == 409
    bundle.manifest["frame_rates"].append(60)
    assert launch(user, state, bundle)["frame_rate"] == 60
