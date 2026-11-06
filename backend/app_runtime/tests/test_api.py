import importlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

from app_runtime.core import digest


class FakeRuntime:
    def __init__(self):
        self.fail_reload = False
        self.files = {}

    def create(self, record, token):
        self.created = record["name"]

    def status(self, name):
        return "running"

    def reload_proxy(self):
        if self.fail_reload:
            raise RuntimeError("proxy unavailable")

    def file(self, name, path, content=None):
        if content is not None:
            self.files[(name, path)] = content
        return self.files.get((name, path), "")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app_runtime import docker_runtime

    fake = FakeRuntime()
    monkeypatch.setattr(docker_runtime, "Runtime", lambda: fake)
    users = tmp_path / "users.json"
    users.write_text(
        json.dumps(
            {
                "owner": "owner-key",
                "friend": "friend-key",
                "viewer": "viewer-key",
                "outsider": "outsider-key",
            }
        )
    )
    monkeypatch.setenv("APPS_USERS", str(users))
    monkeypatch.setenv("APPS_CREATORS", "owner")
    monkeypatch.setenv("APPS_STATE", str(tmp_path))
    monkeypatch.setenv("APPS_PROXY_CONFIG", str(tmp_path / "Caddyfile"))
    sys.modules.pop("app_runtime.api", None)
    api = importlib.import_module("app_runtime.api")
    api.store.put(
        {
            "name": "trip",
            "status": "running",
            "members": {"owner": "owner", "friend": "contributor", "viewer": "viewer"},
            "routes": {},
            "app_token_hash": digest("app-key"),
            "db_password": "never-expose",
        }
    )
    with TestClient(api.app, raise_server_exceptions=False) as client:
        yield client, api, fake


def headers(user):
    return {"Authorization": "Bearer " + user + "-key"}


def test_membership_and_private_public_transitions(client):
    c, _, _ = client
    assert c.get("/api/apps").status_code == 401
    assert c.get("/api/apps", headers=headers("outsider")).json() == []
    result = c.get("/api/apps", headers=headers("friend"))
    assert "never-expose" not in result.text and "app_token_hash" not in result.text
    path = "/api/apps/trip/routes/default"
    assert (
        c.put(path, json={"port": 3000}, headers=headers("viewer")).status_code == 403
    )
    assert (
        c.put(path, json={"port": 3000}, headers=headers("friend")).status_code == 200
    )
    assert c.get("/authorize/trip/default").status_code == 401
    assert (
        c.get("/authorize/trip/default", headers=headers("viewer")).status_code == 204
    )
    assert (
        c.get("/authorize/trip/default", headers=headers("outsider")).status_code == 404
    )
    assert (
        c.put(
            path, json={"port": 3000, "public": True}, headers=headers("friend")
        ).status_code
        == 200
    )
    assert c.get("/authorize/trip/default").status_code == 204
    assert c.delete(path, headers=headers("friend")).status_code == 200
    assert c.get("/authorize/trip/default").status_code == 404


def test_scoped_app_token_cannot_administer_platform(client):
    c, _, _ = client
    token = headers("app")
    assert c.post("/api/apps", json={"name": "evil"}, headers=token).status_code == 403
    assert (
        c.post("/api/apps/trip/exec", json={"command": "id"}, headers=token).status_code
        == 403
    )
    assert (
        c.put(
            "/api/apps/trip/members/outsider",
            json={"role": "contributor"},
            headers=token,
        ).status_code
        == 403
    )
    assert (
        c.put(
            "/api/apps/other/routes/default", json={"port": 3000}, headers=token
        ).status_code
        == 403
    )
    assert (
        c.put(
            "/api/apps/trip/routes/default", json={"port": 3000}, headers=token
        ).status_code
        == 200
    )


def test_revocation_and_invalid_role(client):
    c, _, _ = client
    path = "/api/apps/trip/members/viewer"
    assert (
        c.put(path, json={"role": "contributor"}, headers=headers("friend")).status_code
        == 403
    )
    assert (
        c.put(path, json={"role": "owner"}, headers=headers("owner")).status_code == 422
    )
    assert (
        c.put(path, json={"role": "none"}, headers=headers("owner")).status_code == 200
    )
    assert c.get("/api/apps", headers=headers("viewer")).json() == []


def test_failed_publish_rolls_back_registry(client):
    c, api, fake = client
    fake.fail_reload = True
    assert (
        c.put(
            "/api/apps/trip/routes/default",
            json={"port": 3000, "public": True},
            headers=headers("friend"),
        ).status_code
        == 503
    )
    assert not api.store.get("trip")["routes"]
    assert c.get("/authorize/trip/default").status_code == 404


def test_viewer_cannot_read_files_or_jobs(client):
    c, _, _ = client
    for path in ["/api/apps/trip/file?path=/workspace/a", "/api/apps/trip/jobs/job"]:
        assert c.get(path, headers=headers("viewer")).status_code == 403
    assert (
        c.post(
            "/api/apps/trip/exec", json={"command": "id"}, headers=headers("viewer")
        ).status_code
        == 403
    )


def test_invalid_input_and_restore_confirmation(client):
    c, _, _ = client
    assert (
        c.put(
            "/api/apps/trip/routes/default", json={"port": 0}, headers=headers("owner")
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/apps/trip/exec",
            json={"command": "sleep 9999", "timeout": 9999},
            headers=headers("owner"),
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/apps/trip/backups/" + "a" * 32 + "/restore",
            json={},
            headers=headers("owner"),
        ).status_code
        == 422
    )


def test_cross_origin_mutation_denied(client):
    c, _, _ = client
    assert (
        c.post(
            "/api/apps/trip/lifecycle/stop",
            headers={**headers("owner"), "Origin": "http://trip.localhost:8090"},
        ).status_code
        == 403
    )


def test_unicode_output_is_bounded_in_bytes(client):
    _, api, fake = client

    def run(name, command, timeout, on_output):
        on_output("🌿" * 40000)
        return 0

    fake.run = run
    job = {
        "id": "unicode",
        "app": "trip",
        "status": "running",
        "output": "",
        "bytes_seen": 0,
        "truncated": False,
    }
    api.execute_job(job, "test", 10)
    saved = api.store.get("unicode", "jobs")
    assert saved["truncated"]
    assert len(saved["output"].encode()) <= 65536
    assert saved["exit_code"] == 0


def test_creation_requires_platform_permission(client):
    c, _, fake = client
    for user in ["friend", "viewer", "outsider"]:
        assert (
            c.post(
                "/api/apps", json={"name": "new-app"}, headers=headers(user)
            ).status_code
            == 403
        )
    result = c.post("/api/apps", json={"name": "new-app"}, headers=headers("owner"))
    assert result.status_code == 201
    assert fake.created == "new-app"
    assert result.json()["repository"] == {
        "kind": "local",
        "initial_path": "/workspace",
        "default_branch": "main",
    }
    assert "db_password" not in result.text
    assert (
        c.post(
            "/api/apps", json={"name": "new-app"}, headers=headers("owner")
        ).status_code
        == 409
    )
