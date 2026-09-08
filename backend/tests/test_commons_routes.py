from fastapi import FastAPI
from fastapi.testclient import TestClient

import commons.routes as routes


def client(monkeypatch):
    app = FastAPI()
    app.include_router(routes.router, prefix="/commons")
    app.state.commons_supabase = object()
    monkeypatch.setattr(routes, "read_scene", lambda _client: {
        "id": "commons-home", "layout_version": 1, "version": 2,
        "state": {"schema_version": 1, "objects": {}, "actors": {}},
        "updated_at": "2026-09-07T12:00:00Z",
    })
    return TestClient(app)


def test_scene_is_publicly_readable(monkeypatch):
    response = client(monkeypatch).get("/commons/scene")

    assert response.status_code == 200
    assert response.json()["version"] == 2


def test_scene_command_requires_a_strict_command_shape(monkeypatch):
    response = client(monkeypatch).post(
        "/commons/scene/commands",
        json={
            "client_command_id": "c1",
            "expected_version": 2,
            "kind": "move_object",
            "payload": {"object_id": "record-player", "x": 0.3, "y": 0.4},
            "unexpected": True,
        },
    )

    assert response.status_code == 422


def test_stale_scene_command_is_a_conflict(monkeypatch):
    monkeypatch.setattr(routes, "commit_scene_command", lambda *_args: (_ for _ in ()).throw(
        routes.SceneConflictError("stale_version", 3)
    ))
    response = client(monkeypatch).post(
        "/commons/scene/commands",
        headers={"X-Scene-Client-Id": "browser-1"},
        json={
            "client_command_id": "c1", "expected_version": 2,
            "kind": "walk_actor",
            "payload": {"actor_id": "host", "x": 0.3, "y": 0.4},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "commons.stale_version", "current_version": 3}
