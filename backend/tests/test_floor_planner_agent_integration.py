"""Real MCP protocol, edit CAS, and encrypted OAuth storage on loopback Supabase."""

import base64
import json
import os
import re
from uuid import uuid4
from urllib.parse import urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.oauth_proxy import (
    JTIMapping,
    RefreshTokenMetadata,
    UpstreamTokenSet,
    _hash_token,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull

from cc_mcp.mount import mount_agent_app
from cc_mcp.server import create_agent_app
from floor_planner.agent_tools import EDIT_SCOPE, READ_SCOPE, provider
from cc_mcp.oauth_storage import SupabaseOAuthStore
from floor_planner.routes import router
from tests.test_floor_planner_integration import create_account, local_floor_planner_api


class LocalSupabaseSessionVerifier(TokenVerifier):
    """Exercise the MCP proxy with a real loopback Supabase session JWT."""

    def __init__(self, token, client_id):
        super().__init__(required_scopes=[])
        self._token = token
        self._client_id = client_id

    async def verify_token(self, token):
        if token != self._token:
            return None
        return AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=[],
            claims={"aud": "authenticated"},
        )


def mcp_environment(api_url):
    return {
        "CC_MCP_BASE_URL": "http://127.0.0.1:8099",
        "CC_MCP_OAUTH_CLIENT_ID": "11111111-1111-4111-8111-111111111111",
        "CC_MCP_OAUTH_CLIENT_SECRET": "loopback-only-client-secret",
        "CC_MCP_JWT_SIGNING_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "CC_MCP_STORAGE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SUPABASE_URL": api_url,
    }


@pytest.mark.asyncio
async def test_mounted_streamable_http_lists_reads_and_atomically_edits(local_floor_planner_api):
    api, service, settings, accounts, documents = local_floor_planner_api
    owner_email = f"floor-agent-{uuid4().hex}@floor-planner.local"
    owner, _owner_client = create_account(service, settings, accounts, owner_email)
    session_token = owner["Authorization"].split(" ", 1)[1]
    created = api.post(
        "/floor-planner/plans",
        headers=owner,
        json={
            "title": "MCP integration",
            "template": "blank",
            "scene": {
                "version": 2,
                "title": "MCP integration",
                "units": "inches",
                "rooms": [],
                "elements": [],
                "viewport": None,
            },
        },
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    documents.append(plan_id)

    environment = mcp_environment(settings["API_URL"])
    client_id = environment["CC_MCP_OAUTH_CLIENT_ID"]
    storage_key = environment["CC_MCP_STORAGE_ENCRYPTION_KEY"].encode()
    storage = FernetEncryptionWrapper(
        key_value=SupabaseOAuthStore(service),
        fernet=Fernet(storage_key),
        raise_on_decryption_error=True,
    )
    mcp_app = create_agent_app(
        service,
        providers=(provider,),
        environment=environment,
        token_verifier=LocalSupabaseSessionVerifier(session_token, client_id),
        storage=storage,
    )
    root_app = FastAPI()
    root_app.include_router(router, prefix="/floor-planner")
    mount_agent_app(root_app, mcp_app)
    oauth = mcp_app.state.cc_mcp_oauth
    jti = uuid4().hex
    upstream_id = uuid4().hex

    async def seed_token(local_scopes, mcp_client_id, include_refresh=False):
        await oauth._upstream_token_store.put(
            key=upstream_id,
            value=UpstreamTokenSet(
                upstream_token_id=upstream_id,
                access_token=session_token,
                refresh_token="loopback-upstream-refresh" if include_refresh else None,
                refresh_token_expires_at=4_000_000_000 if include_refresh else None,
                expires_at=4_000_000_000,
                token_type="Bearer",
                scope="openid email",
                client_id=mcp_client_id,
                created_at=1,
            ),
            ttl=3600,
        )
        await oauth._jti_mapping_store.put(
            key=jti,
            value=JTIMapping(jti=jti, upstream_token_id=upstream_id, created_at=1),
            ttl=3600,
        )
        access_token = oauth.jwt_issuer.issue_access_token(
            mcp_client_id, local_scopes, jti, 3600
        )
        rows = service.table("cc_mcp_oauth_state").select("value").eq("key", upstream_id).execute().data
        assert rows and session_token not in json.dumps(rows)
        return access_token

    async def seed_refresh(mcp_client_id, scopes):
        refresh_token = oauth.jwt_issuer.issue_refresh_token(
            mcp_client_id, scopes, jti, 3600
        )
        await oauth._refresh_token_store.put(
            key=_hash_token(refresh_token),
            value=RefreshTokenMetadata(
                client_id=mcp_client_id,
                scopes=scopes,
                expires_at=4_000_000_000,
                created_at=1,
            ),
            ttl=3600,
        )
        return refresh_token

    async def cleanup_token():
        await oauth._jti_mapping_store.delete(key=jti)
        await oauth._upstream_token_store.delete(key=upstream_id)

    def httpx_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=root_app),
            base_url="http://testserver",
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    try:
        async with mcp_app.router.lifespan_context(mcp_app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=root_app), base_url="http://testserver"
            ) as browser:
                challenge = await browser.get("/mcp")
                authorization_metadata = await browser.get(
                    "/.well-known/oauth-authorization-server"
                )
                metadata_url = re.search(
                    r'resource_metadata="([^"]+)"',
                    challenge.headers.get("www-authenticate", ""),
                )
                assert challenge.status_code == 401
                assert metadata_url is not None
                resource_metadata = await browser.get(urlsplit(metadata_url.group(1)).path)
                assert authorization_metadata.status_code == 200
                assert authorization_metadata.json()["authorization_endpoint"].endswith(
                    "/authorize"
                )
                assert authorization_metadata.json()["revocation_endpoint"].endswith(
                    "/revoke"
                )
                assert resource_metadata.status_code == 200
                assert resource_metadata.json()["resource"] == (
                    "http://127.0.0.1:8099/mcp"
                )
                registration = await browser.post(
                    "/register",
                    json={
                        "client_name": "Loopback floor-plan test",
                        "redirect_uris": ["http://localhost:53682/callback"],
                        "grant_types": ["authorization_code", "refresh_token"],
                        "response_types": ["code"],
                        "token_endpoint_auth_method": "none",
                        "scope": f"{READ_SCOPE} {EDIT_SCOPE}",
                    },
                )
                assert registration.status_code == 201, registration.text
                mcp_client_id = registration.json()["client_id"]

            access_token = await seed_token(
                [READ_SCOPE, EDIT_SCOPE], mcp_client_id
            )

            async with streamablehttp_client(
                "http://testserver/mcp",
                headers={"Authorization": f"Bearer {access_token}"},
                httpx_client_factory=httpx_factory,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    assert {
                        tool.name
                        for tool in tools.tools
                    } == {
                        "list_floor_plans",
                        "get_floor_plan",
                        "describe_floor_plan_schema",
                        "edit_floor_plan",
                    }
                    plans = await session.call_tool("list_floor_plans", {})
                    assert plans.structuredContent["mine"][0]["id"] == plan_id
                    current = await session.call_tool("get_floor_plan", {"plan_id": plan_id})
                    assert current.structuredContent["revision"] == 1

                    element = {
                        "id": "agent-rectangle",
                        "type": "rectangle",
                        "x": 100,
                        "y": 90,
                        "width": 50,
                        "height": 24,
                        "rotation": 0,
                        "label": "Desk",
                    }
                    invalid_bool_revision = await session.call_tool(
                        "edit_floor_plan",
                        {
                            "plan_id": plan_id,
                            "expected_revision": True,
                            "operations": [{"op": "add", "element": element}],
                        },
                    )
                    assert invalid_bool_revision.isError
                    saved = await session.call_tool(
                        "edit_floor_plan",
                        {
                            "plan_id": plan_id,
                            "expected_revision": 1,
                            "operations": [{"op": "add", "element": element}],
                        },
                    )
                    assert not saved.isError, saved
                    assert saved.structuredContent["revision"] == 2
                    stale = await session.call_tool(
                        "edit_floor_plan",
                        {
                            "plan_id": plan_id,
                            "expected_revision": 1,
                            "operations": [{
                                "op": "update",
                                "id": "agent-rectangle",
                                "changes": {"x": 400},
                            }],
                        },
                    )
                    assert stale.isError
                    latest = await session.call_tool("get_floor_plan", {"plan_id": plan_id})
                    assert latest.structuredContent["revision"] == 2
                    assert latest.structuredContent["scene"]["elements"] == [element]

            read_only_token = await seed_token([READ_SCOPE], mcp_client_id)
            async with streamablehttp_client(
                "http://testserver/mcp",
                headers={"Authorization": f"Bearer {read_only_token}"},
                httpx_client_factory=httpx_factory,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    denied = await session.call_tool(
                        "edit_floor_plan",
                        {
                            "plan_id": plan_id,
                            "expected_revision": 2,
                            "operations": [{"op": "delete", "id": "agent-rectangle"}],
                        },
                    )
                    assert denied.isError

            refresh_access_token = await seed_token(
                [READ_SCOPE, EDIT_SCOPE], mcp_client_id, include_refresh=True
            )
            refresh_token = await seed_refresh(
                mcp_client_id, [READ_SCOPE, EDIT_SCOPE]
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=root_app), base_url="http://testserver"
            ) as revoke_client:
                revoked = await revoke_client.post(
                    "/revoke",
                    data={
                        "client_id": mcp_client_id,
                        "token": refresh_token,
                        "token_type_hint": "refresh_token",
                    },
                )
            assert revoked.status_code == 200
            assert await oauth._jti_mapping_store.get(key=jti) is None
            assert await oauth._upstream_token_store.get(key=upstream_id) is None
            assert await oauth.load_access_token(refresh_access_token) is None
    finally:
        await cleanup_token()
