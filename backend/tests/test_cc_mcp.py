"""OAuth configuration and token-boundary tests for the shared MCP service."""

import base64
import os
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp.server.auth import AccessToken, JWTVerifier, TokenVerifier
from fastmcp.server.auth.oauth_proxy import (
    JTIMapping,
    RefreshTokenMetadata,
    UpstreamTokenSet,
    _hash_token,
)
from key_value.aio.stores.memory import MemoryStore
from mcp.server.auth.provider import RefreshToken
from mcp.shared.auth import OAuthClientInformationFull

from cc_mcp.server import (
    ToolProvider,
    ToolContext,
    AgentConfigError,
    AgentSettings,
    ResourceBoundOAuthProxy,
    SupabaseOAuthTokenVerifier,
    create_agent_app,
)
from cc_mcp.mount import mount_agent_app

READ_SCOPE = "example:read"
EDIT_SCOPE = "example:edit"
provider = ToolProvider("example", (READ_SCOPE, EDIT_SCOPE), lambda mcp, context: None)

SUPABASE_URL = "http://127.0.0.1:54321"
OAUTH_CLIENT_ID = "11111111-1111-4111-8111-111111111111"


def settings_environment(**overrides):
    from cryptography.fernet import Fernet

    values = {
        "CC_MCP_BASE_URL": "http://127.0.0.1:8000",
        "CC_MCP_OAUTH_CLIENT_ID": OAUTH_CLIENT_ID,
        "CC_MCP_OAUTH_CLIENT_SECRET": "local-oauth-client-secret",
        "CC_MCP_JWT_SIGNING_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "CC_MCP_STORAGE_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "SUPABASE_URL": SUPABASE_URL,
    }
    values.update(overrides)
    return values


class FixedTokenVerifier(TokenVerifier):
    def __init__(self):
        super().__init__(required_scopes=[])

    async def verify_token(self, token):
        if token != "upstream-test-access-token":
            return None
        return AccessToken(
            token=token,
            client_id=OAUTH_CLIENT_ID,
            scopes=[],
            claims={"sub": "a-real-user", "aud": "authenticated"},
        )


def make_agent_app(environment=None, verifier=None, storage=None):
    return create_agent_app(
        object(),
        providers=(provider,),
        environment=environment or settings_environment(),
        token_verifier=verifier or FixedTokenVerifier(),
        storage=storage or MemoryStore(),
    )


def test_missing_or_unsafe_configuration_keeps_mcp_closed():
    app = create_agent_app(None, environment={})
    with TestClient(app) as client:
        response = client.get("/mcp")
    assert response.status_code == 503
    assert response.json() == {"detail": "Cozy Commons agent access is not configured."}
    assert response.headers["Cache-Control"] == "private, no-store"

    for override in (
        {"CC_MCP_BASE_URL": "http://example.test/floor-planner"},
        {"CC_MCP_BASE_URL": "https://example.test/feature"},
        {"SUPABASE_URL": "https://supabase.example/custom-path"},
        {"CC_MCP_JWT_SIGNING_KEY": "not-base64"},
        {"CC_MCP_STORAGE_ENCRYPTION_KEY": "not-a-fernet-key"},
    ):
        with pytest.raises(AgentConfigError):
            AgentSettings.from_environment(settings_environment(**override))


def test_mounted_oauth_metadata_uses_the_mcp_resource_and_local_scopes():
    agent = make_agent_app()
    application = FastAPI()
    mount_agent_app(application, agent)

    with TestClient(application) as client:
        authorization = client.get(
            "/.well-known/oauth-authorization-server"
        )
        protected = client.get("/.well-known/oauth-protected-resource/mcp")

    assert authorization.status_code == 200
    metadata = authorization.json()
    assert metadata["authorization_endpoint"] == "http://127.0.0.1:8000/authorize"
    assert metadata["token_endpoint"] == "http://127.0.0.1:8000/token"
    assert metadata["revocation_endpoint"] == "http://127.0.0.1:8000/revoke"
    assert set(metadata["scopes_supported"]) == {READ_SCOPE, EDIT_SCOPE}
    assert protected.status_code == 200
    assert protected.json()["resource"] == "http://127.0.0.1:8000/mcp"


@pytest.mark.asyncio
async def test_resource_tokens_reject_refresh_jwts_raw_supabase_tokens_and_other_audiences():
    app = make_agent_app()
    oauth: ResourceBoundOAuthProxy = app.state.cc_mcp_oauth
    jti = uuid4().hex
    upstream_id = uuid4().hex
    await oauth._upstream_token_store.put(
        key=upstream_id,
        value=UpstreamTokenSet(
            upstream_token_id=upstream_id,
            access_token="upstream-test-access-token",
            refresh_token=None,
            refresh_token_expires_at=None,
            expires_at=4_000_000_000,
            token_type="Bearer",
            scope="openid email",
            client_id=OAUTH_CLIENT_ID,
            created_at=1,
        ),
        ttl=3600,
    )
    await oauth._jti_mapping_store.put(
        key=jti,
        value=JTIMapping(jti=jti, upstream_token_id=upstream_id, created_at=1),
        ttl=3600,
    )

    scopes = [READ_SCOPE, EDIT_SCOPE]
    access = oauth.jwt_issuer.issue_access_token("mcp-test-client", scopes, jti, 3600)
    refresh = oauth.jwt_issuer.issue_refresh_token("mcp-test-client", scopes, jti, 3600)
    wrong_audience = oauth.jwt_issuer.__class__(
        issuer=str(oauth.base_url),
        audience="http://127.0.0.1:8000/another-resource",
        signing_key=oauth._jwt_signing_key,
    ).issue_access_token("mcp-test-client", scopes, jti, 3600)

    loaded = await oauth.load_access_token(access)
    assert loaded is not None
    assert loaded.token == "upstream-test-access-token"
    assert loaded.scopes == scopes
    assert loaded.client_id == "mcp-test-client"
    assert await oauth.load_access_token(refresh) is None
    assert await oauth.load_access_token(wrong_audience) is None
    assert await oauth.load_access_token("a raw Supabase session token") is None
    assert oauth._prepare_scopes_for_upstream_refresh(scopes) == []


@pytest.mark.asyncio
async def test_supabase_jwt_verifier_checks_signature_issuer_audience_client_and_subject():
    environment = settings_environment()
    settings = AgentSettings.from_environment(environment)
    verifier = SupabaseOAuthTokenVerifier(settings)
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    verifier._verifiers["ES256"] = JWTVerifier(
        public_key=public_pem,
        issuer=f"{SUPABASE_URL}/auth/v1",
        audience="authenticated",
        algorithm="ES256",
        required_scopes=[],
    )

    def signed(**changes):
        claims = {
            "iss": f"{SUPABASE_URL}/auth/v1",
            "aud": "authenticated",
            "client_id": OAUTH_CLIENT_ID,
            "sub": "2f3d0af8-3714-41b4-9065-37f8a7e2203b",
            "exp": 4_000_000_000,
            "iat": 1,
        }
        claims.update(changes)
        return jwt.encode(claims, private_pem, algorithm="ES256", headers={"kid": "test"})

    assert await verifier.verify_token(signed())
    assert await verifier.verify_token(signed(client_id="some-other-app")) is None
    assert await verifier.verify_token(signed(aud="another-api")) is None
    assert await verifier.verify_token(signed(iss="https://wrong.example/auth/v1")) is None
    assert await verifier.verify_token(signed(sub="not-a-user-uuid")) is None
    assert await verifier.verify_token(signed(exp=None)) is None
    assert await verifier.verify_token(signed(exp=1)) is None
    assert await verifier.verify_token(jwt.encode({"sub": "ignored"}, "bad", algorithm="HS256")) is None


@pytest.mark.asyncio
async def test_refresh_keeps_agent_scopes_local_and_revocation_removes_proxy_tokens(monkeypatch):
    import fastmcp.server.auth.oauth_proxy as oauth_proxy_module

    app = make_agent_app()
    oauth: ResourceBoundOAuthProxy = app.state.cc_mcp_oauth
    client = OAuthClientInformationFull(
        client_id="mcp-refresh-client",
        redirect_uris=["http://localhost/callback"],
        scope=f"{READ_SCOPE} {EDIT_SCOPE}",
    )
    upstream_id = uuid4().hex
    old_access_jti = uuid4().hex
    refresh_jti = uuid4().hex
    scopes = [READ_SCOPE, EDIT_SCOPE]
    refresh_jwt = oauth.jwt_issuer.issue_refresh_token(
        client.client_id, scopes, refresh_jti, 3600
    )
    await oauth._upstream_token_store.put(
        key=upstream_id,
        value=UpstreamTokenSet(
            upstream_token_id=upstream_id,
            access_token="previous-upstream-token",
            refresh_token="upstream-refresh-token",
            refresh_token_expires_at=4_000_000_000,
            expires_at=4_000_000_000,
            token_type="Bearer",
            scope="openid email",
            client_id=client.client_id,
            created_at=1,
        ),
        ttl=3600,
    )
    for jti in (old_access_jti, refresh_jti):
        await oauth._jti_mapping_store.put(
            key=jti,
            value=JTIMapping(jti=jti, upstream_token_id=upstream_id, created_at=1),
            ttl=3600,
        )
    await oauth._refresh_token_store.put(
        key=_hash_token(refresh_jwt),
        value=RefreshTokenMetadata(
            client_id=client.client_id,
            scopes=scopes,
            expires_at=4_000_000_000,
            created_at=1,
        ),
        ttl=3600,
    )

    calls = []

    class RecordingOAuthClient:
        def __init__(self, **kwargs):
            calls.append({"auth_method": kwargs["token_endpoint_auth_method"]})

        async def refresh_token(self, **kwargs):
            calls[-1]["request"] = kwargs
            return {
                "access_token": "upstream-test-access-token",
                "refresh_token": "rotated-upstream-refresh",
                "refresh_expires_in": 3600,
                "expires_in": 1200,
            }

    monkeypatch.setattr(oauth_proxy_module, "AsyncOAuth2Client", RecordingOAuthClient)
    refresh_model = RefreshToken(
        token=refresh_jwt,
        client_id=client.client_id,
        scopes=scopes,
        expires_at=4_000_000_000,
    )
    rotated = await oauth.exchange_refresh_token(client, refresh_model, scopes)

    assert calls[0]["auth_method"] == "client_secret_basic"
    assert calls[0]["request"]["scope"] is None
    assert calls[0]["request"]["refresh_token"] == "upstream-refresh-token"
    assert rotated.scope == f"{READ_SCOPE} {EDIT_SCOPE}"
    assert rotated.access_token
    assert rotated.refresh_token

    new_access_claims = oauth.jwt_issuer.verify_token(rotated.access_token)
    assert "token_use" not in new_access_claims
    assert oauth.jwt_issuer.verify_token(rotated.refresh_token)["token_use"] == "refresh"
    assert await oauth.load_access_token(rotated.access_token) is not None
    assert await oauth.load_access_token(rotated.refresh_token) is None

    await oauth.revoke_token(
        RefreshToken(
            token=rotated.refresh_token,
            client_id=client.client_id,
            scopes=scopes,
            expires_at=4_000_000_000,
        )
    )
    # The upstream token set backs the entire proxy token family; deleting it
    # immediately invalidates sibling access references without enumerating
    # encrypted persistent-store keys.
    assert await oauth._upstream_token_store.get(key=upstream_id) is None
    assert await oauth.load_access_token(rotated.access_token) is None


@pytest.mark.asyncio
async def test_independent_feature_providers_share_auth_but_keep_permission_boundaries(monkeypatch):
    from fastmcp.exceptions import ToolError

    def register_first(mcp, context):
        @mcp.tool()
        def read_example():
            context.need_scope(READ_SCOPE)
            return "example"

    def register_second(mcp, context):
        @mcp.tool()
        def read_other_feature():
            context.need_scope("other:read")
            return "other"

    first = ToolProvider("example", (READ_SCOPE, EDIT_SCOPE), register_first)
    second = ToolProvider("other", ("other:read",), register_second)
    app = create_agent_app(
        object(), providers=(first, second), environment=settings_environment(),
        token_verifier=FixedTokenVerifier(), storage=MemoryStore(),
    )
    tools = await app.state.cc_mcp.get_tools()
    assert set(tools) == {"read_example", "read_other_feature"}
    monkeypatch.setattr("cc_mcp.server.get_access_token", lambda: AccessToken(
        token="upstream-test-access-token", client_id="client", scopes=[READ_SCOPE],
    ))
    assert (await tools["read_example"].run({})).content[0].text == "example"
    with pytest.raises(ToolError, match="other:read"):
        await tools["read_other_feature"].run({})
    with TestClient(app) as client:
        scopes = client.get("/.well-known/oauth-authorization-server").json()["scopes_supported"]
    assert set(scopes) == {READ_SCOPE, EDIT_SCOPE, "other:read"}


def test_duplicate_provider_names_and_scopes_fail_at_startup():
    for providers in ((provider, provider), (provider, ToolProvider("other", (READ_SCOPE,), lambda mcp, context: None))):
        with pytest.raises(AgentConfigError, match="unique"):
            create_agent_app(object(), providers=providers, environment=settings_environment(), storage=MemoryStore())


def test_unconfigured_shared_mount_preserves_explicit_routes_and_unknown_404s():
    app = FastAPI()

    @app.get("/existing")
    def existing():
        return {"ok": True}

    mount_agent_app(app, create_agent_app(None, environment={}))
    with TestClient(app) as client:
        assert client.get("/existing").json() == {"ok": True}
        assert client.get("/mcp").status_code == 503
        assert client.get("/not-a-route").status_code == 404
