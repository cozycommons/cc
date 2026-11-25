"""Smoke tests for the Maple telemetry MCP tools (in-memory client)."""

import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from maple import accounts, logic, mcp_server
from tests.maple_fakes import FakeSupabase
from tests.test_maple_logic import ENTRY


@pytest.fixture()
def db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setenv("SUPABASE_URL", "http://localhost:54321")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-service-key")
    monkeypatch.setattr(mcp_server, "create_client", lambda url, key: fake)
    return fake


@pytest.fixture()
def token(db):
    created = accounts.create_account(db, "warner")
    logic.ingest_runs(db, created["id"], [dict(ENTRY)])
    return created["token"]


async def call(tool, **arguments):
    async with Client(mcp_server.mcp) as client:
        result = await client.call_tool(tool, arguments)
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_get_me(db, token):
    assert (await call("get_me", api_token=token))["label"] == "warner"


@pytest.mark.asyncio
async def test_get_recent_exp_runs(db, token):
    body = await call("get_recent_exp_runs", api_token=token)
    assert len(body["runs"]) == 1
    assert body["runs"][0]["map"] == "Cave of Evil Eye III"
    assert body["runs"][0]["exp_per_hour"] == 109994.0


@pytest.mark.asyncio
async def test_get_exp_runs_by_map(db, token):
    body = await call("get_exp_runs_by_map", api_token=token, map="Cave of Evil Eye III")
    assert len(body["runs"]) == 1
    body = await call("get_exp_runs_by_map", api_token=token, map="Nowhere")
    assert body["runs"] == []


@pytest.mark.asyncio
async def test_get_best_exp_rates(db, token):
    body = await call("get_best_exp_rates", api_token=token)
    assert body["maps"][0]["map"] == "Cave of Evil Eye III"
    assert body["maps"][0]["best_exp_per_hour"] == 109994.0


@pytest.mark.asyncio
async def test_bad_token_rejected(db):
    with pytest.raises(ToolError):
        await call("get_recent_exp_runs", api_token="ccm_" + "x" * 43)
