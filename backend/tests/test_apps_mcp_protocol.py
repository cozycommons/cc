"""Real native MCP dispatch for hosted and stdio job tools; manager is synthetic."""

from types import SimpleNamespace

from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from mcp.server.fastmcp.exceptions import ToolError as StdioToolError
import pytest

from app_runtime import agent_tools, mcp_server
from cc_mcp import server


@pytest.fixture
def hosted(monkeypatch):
    holder = SimpleNamespace(token=AccessToken(token="synthetic", client_id="test",
                                               scopes=[server.READ_SCOPE, server.EDIT_SCOPE]))
    monkeypatch.setattr(server, "get_access_token", lambda: holder.token)

    async def signed_in(token):
        assert token is holder.token
        return SimpleNamespace(id="synthetic-owner")

    mcp = FastMCP("Apps job protocol test")
    agent_tools.register_tools(mcp, SimpleNamespace(signed_in_user=signed_in))
    return mcp, holder


@pytest.mark.asyncio
async def test_native_hosted_catalog_registers_split_jobs_with_edit_scope(hosted):
    mcp, _ = hosted
    async with Client(mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    assert {"exec_command", "job_read", "job_cancel"} <= tools.keys()
    assert tools["job_read"].annotations.readOnlyHint
    assert tools["job_cancel"].annotations.destructiveHint
    for name in ["exec_command", "job_read", "job_cancel"]:
        assert agent_tools.provider.tools[name] == "edit"


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"app": "trip", "command": "id", "after": 1},
    {"app": "trip", "command": "id", "job_id": "old"},
    {"app": "trip", "command": "id", "cancel": True},
    {"app": "trip", "command": " "},
    {"app": "trip", "command": "id", "cwd": "relative"},
    {"app": "trip", "command": "id", "max_output_bytes": 1},
])
async def test_native_hosted_invalid_start_never_contacts_manager(hosted, monkeypatch, arguments):
    mcp, _ = hosted
    calls = []

    async def request(*args, **kwargs):
        calls.append((args, kwargs))
        return {"id": "unexpected"}

    monkeypatch.setattr(agent_tools, "request", request)
    async with Client(mcp) as client:
        result = await client.call_tool("exec_command", arguments, raise_on_error=False)
    assert result.is_error and calls == []


@pytest.mark.asyncio
async def test_native_hosted_lost_wait_keeps_accepted_job_handle(hosted, monkeypatch):
    mcp, _ = hosted
    calls = []

    async def request(token, method, path, data=None, **kwargs):
        calls.append((method, path, data))
        if method == "POST":
            return {"id": "accepted"}
        raise ToolError("Synthetic manager observation lost")

    monkeypatch.setattr(agent_tools, "request", request)
    async with Client(mcp) as client:
        result = await client.call_tool("exec_command", {"app": "trip", "command": "synthetic",
            "idempotency_key": "recover", "timeout_seconds": 9, "cwd": "/workspace/source"})
    body = result.structured_content
    assert not result.is_error
    assert body["job_id"] == "accepted" and body["start_accepted"]
    assert body["state"] == "unknown" and body["error"]["code"] == "WAIT_UNAVAILABLE"
    assert [row[0] for row in calls] == ["POST", "GET"]
    assert calls[0][2] == {"command": "synthetic", "timeout": 9,
                           "cwd": "/workspace/source", "idempotency_key": "recover"}


@pytest.mark.asyncio
async def test_native_hosted_split_jobs_only_read_or_cancel(hosted, monkeypatch):
    mcp, _ = hosted
    calls = []

    async def request(token, method, path, data=None, **kwargs):
        calls.append((method, path))
        return {"id": "job", "job_id": "job", "state": "cancel_requested", "output": "private log"}

    monkeypatch.setattr(agent_tools, "request", request)
    async with Client(mcp) as client:
        read = await client.call_tool("job_read", {"app": "trip", "job_id": "job",
            "cursor": 12, "wait_ms": 0, "max_output_bytes": 4})
        cancelled = await client.call_tool("job_cancel", {"app": "trip", "job_id": "job"})
    assert read.structured_content["output"] == "private log"
    assert "output" not in cancelled.structured_content
    assert calls == [("GET", "/api/apps/trip/jobs/job?after=12&wait_ms=0&max_output_bytes=4"),
                     ("POST", "/api/apps/trip/jobs/job/cancel")]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    ("job_read", {"app": "trip", "job_id": "job"}),
    ("job_cancel", {"app": "trip", "job_id": "job"}),
])
async def test_native_hosted_job_tools_require_edit_scope(hosted, monkeypatch, tool, arguments):
    mcp, holder = hosted
    holder.token = AccessToken(token="synthetic", client_id="test", scopes=[server.READ_SCOPE])
    calls = []

    async def request(*args, **kwargs):
        calls.append((args, kwargs))
        return {}

    monkeypatch.setattr(agent_tools, "request", request)
    async with Client(mcp) as client:
        result = await client.call_tool(tool, arguments, raise_on_error=False)
    assert result.is_error and calls == []
    assert "commons:edit" in result.content[0].text


@pytest.mark.asyncio
async def test_native_stdio_dispatch_rejects_start_cursor_before_manager_call(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server, "call", lambda *args, **kwargs: calls.append((args, kwargs)))
    with pytest.raises(StdioToolError):
        await mcp_server.mcp.call_tool("exec_command", {"app": "trip", "command": "id", "after": 1})
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"app": "trip", "path": "file", "content": "PRIVATE_SENTINEL"},
    {"app": "trip", "path": "file", "content": {"PRIVATE_SENTINEL": "value"}, "expected_sha256": None},
    {"app": "trip", "path": "file", "content": "ok", "expected_sha256": None, "PRIVATE_SENTINEL": "value"},
])
async def test_stdio_validation_never_echoes_file_contents_or_extra_keys(arguments, monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server, 'call', lambda *args: calls.append(args))
    with pytest.raises(StdioToolError) as error:
        await mcp_server.mcp.call_tool('write_file', arguments)
    assert 'PRIVATE_SENTINEL' not in str(error.value)
    assert calls == []


@pytest.mark.asyncio
async def test_hosted_closed_schema_rejects_unknown_fields_before_dispatch(hosted, monkeypatch):
    mcp, _ = hosted
    calls = []
    async def request(*args, **kwargs):
        calls.append(args)
        return {}
    monkeypatch.setattr(agent_tools, 'request', request)
    async with Client(mcp) as client:
        tools = await client.list_tools()
        assert all(t.inputSchema['additionalProperties'] is False for t in tools)
        result = await client.call_tool('exec_command', {'app': 'trip', 'command': 'echo',
            'PRIVATE_SENTINEL': 'value'}, raise_on_error=False)
    assert result.is_error and 'PRIVATE_SENTINEL' not in str(result.content)
    assert calls == []
