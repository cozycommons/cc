"""MCP tool-argument errors and logs never echo what the agent sent."""
import logging
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from mcp.server.fastmcp.exceptions import ToolError as SdkToolError

import mcp_validation
from cc_mcp.server import COMMONS, READ_SCOPE, ToolProvider, build_server
from espn.mcp_server import mcp as espn_mcp
from ig_logger.sinks.beli.mcp_server import mcp as beli_mcp
from partiful.mcp_server import mcp as partiful_mcp
from resy.mcp_server import mcp as resy_mcp

SECRET = 'SYNTHETIC-API-TOKEN'


@pytest.fixture
def fastmcp_log():
    """Every record FastMCP 3's server logger emits, after its filters run."""
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    mcp_validation.install_log_filter()
    logger = logging.getLogger(mcp_validation.FASTMCP_SERVER_LOGGER)
    handler = Capture(level=logging.DEBUG)
    logger.addHandler(handler)
    yield records
    logger.removeHandler(handler)


@pytest.mark.parametrize('server', [beli_mcp, partiful_mcp, resy_mcp, espn_mcp])
def test_legacy_servers_use_the_redacting_fastmcp(server):
    assert isinstance(server, mcp_validation.FastMCP)


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments', [
    {'api_token': SECRET},                                # missing argument: the default echoes every argument
    {'api_token': SECRET, 'neighborhood': [SECRET]},      # wrong type
])
async def test_a_bad_legacy_call_never_returns_or_logs_its_api_token(fastmcp_log, caplog, arguments):
    caplog.set_level(logging.DEBUG)
    with pytest.raises(SdkToolError) as raised:
        await beli_mcp.call_tool('get_recs', arguments)
    assert 'neighborhood' in str(raised.value)
    assert SECRET not in str(raised.value) and raised.value.__cause__ is None
    assert SECRET not in caplog.text and not any(SECRET in line for line in fastmcp_log)


def secret_provider():
    def register(mcp, _context):
        @mcp.tool
        def echo(secret: str, value: str) -> str:
            return value

    return ToolProvider(COMMONS, register, {'echo': 'signin'})


@pytest.mark.asyncio
async def test_a_bad_cc_mcp_call_names_the_argument_but_never_returns_or_logs_input(monkeypatch, fastmcp_log):
    token = AccessToken(token='synthetic', client_id='test', scopes=[READ_SCOPE])
    monkeypatch.setattr('cc_mcp.server.get_access_token', lambda: token)
    mcp = build_server(object(), (secret_provider(),))
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as raised:
            await client.call_tool('echo', {'secret': SECRET})
        assert await client.call_tool('echo', {'secret': SECRET, 'value': 'ok'}) is not None
    assert "Invalid arguments for tool 'echo': value: Missing required argument" in str(raised.value)
    assert SECRET not in str(raised.value)
    # FastMCP still logs the failure, rewritten to location and message.
    assert fastmcp_log == ["Invalid arguments for tool 'echo': value: Missing required argument"]


def test_the_log_filter_drops_unstructured_detail():
    record = logging.LogRecord('fastmcp.server.server', logging.WARNING, __file__, 1,
                               'Invalid arguments for tool %r: %s', ('echo', f"input_value='{SECRET}'"), None)
    assert mcp_validation.RedactToolArgumentLogs().filter(record)
    assert record.getMessage() == "Invalid arguments for tool 'echo': arguments do not match the tool schema"


def test_the_app_installs_the_log_filter():
    source = (Path(__file__).resolve().parents[1] / 'main.py').read_text()
    assert 'mcp_validation.install_log_filter()' in source
