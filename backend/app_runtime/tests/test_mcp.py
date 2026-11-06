"""MCP execution waits without resubmitting commands or hiding failures."""

import pytest

from app_runtime import mcp_server


def test_exec_waits_and_preserves_bounded_result(monkeypatch):
    calls = []
    finished = {"id": "job", "status": "finished", "exit_code": 7,
                "output": "partial output", "truncated": True}
    replies = iter([{"id": "job"}, {"status": "running"}, finished])

    def call(method, path, data=None):
        calls.append((method, path, data))
        return next(replies)

    monkeypatch.setattr(mcp_server, "call", call)
    monkeypatch.setattr(mcp_server.time, "sleep", lambda _: None)
    assert mcp_server.exec_command("trip", "some-command", 3) == finished
    assert [c[0] for c in calls] == ["POST", "GET", "GET"]
    assert calls[0][2] == {"command": "some-command", "timeout": 3}
    assert calls[-1][1] == "/api/apps/trip/jobs/job"


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_exec_returns_manager_failure(monkeypatch, status):
    result = {"id": "job", "status": status, "error": "Manager restarted"}
    replies = iter([{"id": "job"}, result])
    monkeypatch.setattr(mcp_server, "call", lambda *args: next(replies))
    assert mcp_server.exec_command("trip", "echo test") == result


def test_exec_stops_polling_without_retrying_command(monkeypatch):
    calls = []

    def call(method, *args):
        calls.append(method)
        return {"id": "job", "status": "running"}

    times = iter([0, 17])
    monkeypatch.setattr(mcp_server, "call", call)
    monkeypatch.setattr(mcp_server.time, "monotonic", lambda: next(times))
    with pytest.raises(TimeoutError, match="inspect it through the platform CLI"):
        mcp_server.exec_command("trip", "some-command", 1)
    assert calls == ["POST", "GET"]
