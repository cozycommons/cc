"""MCP execution waits without resubmitting commands or hiding failures."""

import pytest

from app_runtime import mcp_server


def test_exec_waits_and_preserves_bounded_result(monkeypatch):
    calls = []
    finished = {"id": "job", "status": "finished", "exit_code": 7,
                "output": "partial output", "truncated": True}
    replies = iter([{"id": "job"}, finished])

    def call(method, path, data=None):
        calls.append((method, path, data))
        return next(replies)

    monkeypatch.setattr(mcp_server, "call", call)
    assert mcp_server.exec_command("trip", "some-command", 3) == finished
    assert [c[0] for c in calls] == ["POST", "GET"]
    assert calls[0][2] == {"command": "some-command", "timeout": 3}
    assert calls[-1][1] == "/api/apps/trip/jobs/job?after=0&wait_ms=1000&max_output_bytes=4096&wait_for=completion"


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

    monkeypatch.setattr(mcp_server, "call", call)
    result = mcp_server.exec_command("trip", "some-command", 1)
    assert result['status'] == 'running'
    assert calls == ["POST", "GET"]


@pytest.mark.parametrize('arguments', [
    {'app': 'trip', 'path': 'file', 'content': 'PRIVATE_SENTINEL'},
    {'app': 'trip', 'path': 'file', 'content': 'ok', 'expected_sha256': None, 'PRIVATE_SENTINEL': 'private'},
])
def test_standalone_sdk_redacts_file_input_and_unknown_keys(arguments):
    import asyncio
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError) as error:
        asyncio.run(mcp_server.mcp.call_tool('write_file', arguments))
    assert 'PRIVATE_SENTINEL' not in str(error.value)
