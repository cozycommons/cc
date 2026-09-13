from time import sleep

from fastapi import FastAPI
from fastapi.testclient import TestClient

import service_health


class _Query:
    def __init__(self, error=None):
        self.error = error

    def select(self, _columns):
        return self

    def limit(self, _count):
        return self

    def execute(self):
        if self.error:
            raise self.error
        from types import SimpleNamespace
        return SimpleNamespace(data=True)


class _Supabase:
    def __init__(self, error=None):
        self.error = error
        self.tables = []

    def rpc(self, name):
        self.tables.append(name)
        return _Query(self.error)


def _client(supabase=None):
    app = FastAPI()
    if supabase is not None:
        app.state.supabase_admin = supabase
    app.include_router(service_health.router)
    return TestClient(app)


def test_health_is_a_cheap_liveness_check():
    response = _client().get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_checks_database_and_core_schema():
    supabase = _Supabase()
    response = _client(supabase).get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert supabase.tables == ["dice_release_readiness"]


def test_ready_fails_when_database_is_unavailable():
    response = _client(_Supabase(RuntimeError("offline"))).get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "reason": "database_unavailable",
    }


def test_ready_has_a_bounded_timeout(monkeypatch):
    monkeypatch.setattr(service_health, "_READINESS_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(service_health, "_check_required_schema", lambda _client: sleep(0.05))
    response = _client(_Supabase()).get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "reason": "database_timeout"}
