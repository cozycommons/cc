"""Portable job contracts through the manager API and stdio adapter; no Docker."""

from concurrent.futures import ThreadPoolExecutor
import threading

import httpx
import pytest

from app_runtime import mcp_server
from app_runtime.tests.test_api import client, headers


def saved_job(api, *, name="job", output="", status="finished", bytes_seen=None):
    job = {"id": name, "app": "trip", "status": status, "output": output,
           "bytes_seen": len(output.encode()) if bytes_seen is None else bytes_seen,
           "truncated": False, "exit_code": 0 if status == "finished" else None,
           "caller": "owner", "request_hash": "private"}
    api.store.put(job, "jobs")
    return job


def test_utf8_pages_have_exact_byte_cursors_and_no_loss(client):
    c, api, _ = client
    saved_job(api, output="A🌿B🌿C")
    chunks, cursor = [], 0
    while True:
        response = c.get(f"/api/apps/trip/jobs/job?after={cursor}&max_output_bytes=4",
                         headers=headers("friend"))
        assert response.status_code == 200
        page = response.json()
        assert page["state"] == "completed" and page["exit_code"] == 0
        assert len(page["output"].encode()) <= 4
        assert page["next_cursor"] == cursor + len(page["output"].encode())
        assert not page["output_gap"]
        assert "caller" not in page and "request_hash" not in page
        chunks.append(page["output"])
        if not page["more_output"]:
            break
        assert page["next_cursor"] > cursor
        cursor = page["next_cursor"]
    assert "".join(chunks) == "A🌿B🌿C"
    assert page["next_cursor"] == len("A🌿B🌿C".encode())


def test_discarded_output_gap_and_invalid_cursors_are_explicit(client):
    c, api, _ = client
    saved_job(api, output="🌿tail", bytes_seen=100)
    url = "/api/apps/trip/jobs/job"
    result = c.get(url + "?after=0&max_output_bytes=4", headers=headers("friend")).json()
    assert result["output"] == "🌿"
    assert result["output_gap"] and result["truncated"]
    assert result["available_from"] == 92 and result["next_cursor"] == 96
    assert result["more_output"]
    for cursor in [93, 94, 95, 101]:
        assert c.get(url + f"?after={cursor}", headers=headers("friend")).status_code == 422
    end = c.get(url + "?after=100", headers=headers("friend")).json()
    assert end["output"] == "" and end["next_cursor"] == 100
    assert not end["more_output"] and not end["output_gap"]


@pytest.mark.parametrize("query", ["max_output_bytes=0", "max_output_bytes=1",
    "max_output_bytes=3", "max_output_bytes=65537", "after=-1", "wait_ms=-1", "wait_ms=10001"])
def test_invalid_read_bounds_are_rejected(client, query):
    c, api, _ = client
    saved_job(api, output="🌿")
    assert c.get("/api/apps/trip/jobs/job?" + query, headers=headers("friend")).status_code == 422


@pytest.mark.parametrize("body", [
    {"command": ""}, {"command": "   "}, {"command": "id", "after": 1},
    {"command": "id", "cwd": "relative"}, {"command": "id", "cwd": "/work\x00space"},
    {"command": "id", "idempotency_key": " "}, {"command": "id", "timeout": 0},
])
def test_invalid_start_has_no_persisted_job_or_runtime_effect(client, body):
    c, api, fake = client
    called = []
    fake.run = lambda *args, **kwargs: called.append((args, kwargs))
    assert c.post("/api/apps/trip/exec", json=body, headers=headers("friend")).status_code == 422
    assert not called and api.store.all("jobs") == []


def test_cwd_reaches_runtime_and_is_part_of_retry_identity(client):
    c, api, fake = client
    entered = threading.Event()
    calls = []

    def run(name, command, timeout, output, job_id=None, cwd="/workspace"):
        calls.append((name, command, timeout, cwd))
        output("done\n")
        entered.set()
        return 7

    fake.run = run
    body = {"command": "synthetic", "timeout": 9, "cwd": "/workspace/source",
            "idempotency_key": "cwd-retry"}
    response = c.post("/api/apps/trip/exec", json=body, headers=headers("friend"))
    assert response.status_code == 202 and entered.wait(2)
    job_id = response.json()["id"]
    completed = c.get(f"/api/apps/trip/jobs/{job_id}?wait_ms=1000", headers=headers("friend")).json()
    assert completed["state"] == "completed" and completed["exit_code"] == 7
    assert calls == [("trip", "synthetic", 9, "/workspace/source")]
    assert c.post("/api/apps/trip/exec", json=body, headers=headers("friend")).json()["id"] == job_id
    for changes in [{"cwd": "/workspace/elsewhere"}, {"timeout": 10}, {"command": "different"}]:
        assert c.post("/api/apps/trip/exec", json={**body, **changes}, headers=headers("friend")).status_code == 409
    assert len(calls) == 1


def test_explicit_default_cwd_keeps_legacy_retry_identity(client):
    c, _, fake = client
    fake.run = lambda *args, **kwargs: 0
    body = {"command": "synthetic", "idempotency_key": "legacy-cwd"}
    original = c.post("/api/apps/trip/exec", json=body, headers=headers("friend")).json()
    retry = c.post("/api/apps/trip/exec", json={**body, "cwd": "/workspace"}, headers=headers("friend"))
    assert retry.status_code == 202 and retry.json()["id"] == original["id"]


def test_bounded_wait_wakes_for_output(client, monkeypatch):
    c, api, _ = client
    saved_job(api, status="running")
    entered = threading.Event()
    original_wait = api.job_changed.wait

    def wait(timeout=None):
        entered.set()
        return original_wait(timeout)

    monkeypatch.setattr(api.job_changed, "wait", wait)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(c.get, "/api/apps/trip/jobs/job?after=0&wait_ms=10000",
                              headers=headers("friend"))
        try:
            assert entered.wait(2)
            with api.job_changed:
                job = api.store.get("job", "jobs")
                job.update(output="ready 🌿\n", bytes_seen=len("ready 🌿\n".encode()))
                api.store.put(job, "jobs")
                api.job_changed.notify_all()
            response = request.result(timeout=2)
            assert response.status_code == 200
            assert response.json()["output"] == "ready 🌿\n"
            assert response.json()["state"] == "running"
        finally:
            with api.job_changed:
                job = api.store.get("job", "jobs")
                job["status"] = "finished"
                api.store.put(job, "jobs")
                api.job_changed.notify_all()


def test_wait_returns_immediately_when_wait_slots_are_full(client, monkeypatch):
    c, api, _ = client
    saved_job(api, status="running")
    monkeypatch.setattr(api, "wait_slots", threading.BoundedSemaphore(1))
    assert api.wait_slots.acquire(blocking=False)
    monkeypatch.setattr(api.job_changed, "wait", lambda timeout=None: pytest.fail("waited without a slot"))
    try:
        response = c.get("/api/apps/trip/jobs/job?after=0&wait_ms=10000", headers=headers("friend"))
        assert response.status_code == 200 and response.json()["state"] == "running"
    finally:
        api.wait_slots.release()


def test_wait_rechecks_membership_after_wake(client, monkeypatch):
    c, api, _ = client
    saved_job(api, status="running")
    entered = threading.Event()
    original_wait = api.job_changed.wait

    def wait(timeout=None):
        entered.set()
        return original_wait(timeout)

    monkeypatch.setattr(api.job_changed, "wait", wait)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(c.get, "/api/apps/trip/jobs/job?after=0&wait_ms=10000",
                              headers=headers("friend"))
        try:
            assert entered.wait(2)
            revoked = c.put("/api/apps/trip/members/friend", json={"role": "none"}, headers=headers("owner"))
            assert revoked.status_code == 200
            with api.job_changed:
                # A real output/status event wakes the waiter after revocation.
                job = api.store.get("job", "jobs")
                job.update(output="private", bytes_seen=7)
                api.store.put(job, "jobs")
                api.job_changed.notify_all()
            response = request.result(timeout=2)
            assert response.status_code == 404
            assert "private" not in response.text
        finally:
            with api.job_changed:
                job = api.store.get("job", "jobs")
                job["status"] = "finished"
                api.store.put(job, "jobs")
                api.job_changed.notify_all()


def test_cancel_request_and_observed_terminal_state_are_distinct(client):
    c, api, fake = client
    job = saved_job(api, status="running", output="effect already happened\n")
    cancelled = []
    fake.cancel = lambda app, job_id: cancelled.append((app, job_id))
    url = "/api/apps/trip/jobs/job"
    result = c.post(url + "/cancel", headers=headers("friend")).json()
    assert result["state"] == "cancel_requested" and result["exit_code"] is None
    assert result["output"] == "effect already happened\n"
    fake.run = lambda *args, **kwargs: 130
    api.execute_job(job, "synthetic", 5)
    terminal = c.get(url, headers=headers("friend")).json()
    assert terminal["state"] == "cancelled" and terminal["exit_code"] == 130
    assert terminal["output"] == result["output"]
    assert c.post(url + "/cancel", headers=headers("friend")).json()["state"] == "cancelled"
    assert cancelled == [("trip", "job")]


@pytest.mark.parametrize("arguments", [
    {"command": "id", "after": 1}, {"command": "id", "cancel": True},
    {"command": "id", "job_id": "old"}, {"command": " "},
    {"command": "id", "cwd": "relative"}, {"command": "id", "max_output_bytes": 1},
    {"command": "id", "timeout": 5, "timeout_seconds": 7},
])
def test_stdio_malformed_start_rejected_before_any_manager_call(monkeypatch, arguments):
    calls = []
    monkeypatch.setattr(mcp_server, "call", lambda *args, **kwargs: calls.append((args, kwargs)))
    with pytest.raises(ValueError):
        mcp_server.exec_command("trip", **arguments)
    assert calls == []


@pytest.mark.parametrize("failure", [httpx.ConnectError("synthetic disconnect"), ValueError("bad response")])
def test_stdio_accepted_start_keeps_handle_when_wait_response_is_lost(monkeypatch, failure):
    calls = []

    def call(method, path, data=None):
        calls.append((method, path, data))
        if method == "POST":
            return {"id": "accepted"}
        raise failure

    monkeypatch.setattr(mcp_server, "call", call)
    result = mcp_server.exec_command("trip", "synthetic", idempotency_key="recover", cwd="/workspace/source", timeout_seconds=9)
    assert result["job_id"] == "accepted" and result["start_accepted"]
    assert result["state"] == "unknown" and result["error"]["code"] == "WAIT_UNAVAILABLE"
    assert [row[0] for row in calls] == ["POST", "GET"]
    assert calls[0][2] == {"command": "synthetic", "timeout": 9, "cwd": "/workspace/source", "idempotency_key": "recover"}


def test_stdio_read_and_cancel_never_submit_execution(monkeypatch):
    calls = []

    def call(method, path, data=None):
        calls.append((method, path))
        return {"id": "job", "job_id": "job", "state": "cancel_requested", "output": "private log"}

    monkeypatch.setattr(mcp_server, "call", call)
    assert mcp_server.job_read("trip", "job", cursor=12, wait_ms=0, max_output_bytes=4)["output"] == "private log"
    cancelled = mcp_server.job_cancel("trip", "job")
    assert cancelled["state"] == "cancel_requested" and "output" not in cancelled
    assert calls == [("GET", "/api/apps/trip/jobs/job?after=12&wait_ms=0&max_output_bytes=4"),
                     ("POST", "/api/apps/trip/jobs/job/cancel")]
