"""OAuth configuration and token-boundary tests for the shared MCP service."""

import asyncio
import base64
import os
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp.server.auth import AccessToken, JWTVerifier, OAuthProxy, TokenVerifier
from fastmcp.server.auth.oauth_proxy.models import (
    JTIMapping,
    RefreshTokenMetadata,
    UpstreamTokenSet,
    _hash_token,
)
from key_value.aio.stores.memory import MemoryStore
from mcp.server.auth.provider import RefreshToken
from mcp.shared.auth import OAuthClientInformationFull

from cc_mcp import oauth_storage
from cc_mcp.server import (
    ToolProvider,
    AgentConfigError,
    AgentSettings,
    ResourceBoundOAuthProxy,
    SupabaseOAuthTokenVerifier,
    create_agent_app,
)
from cc_mcp.mount import mount_agent_app
from cc_mcp.oauth_storage import SupabaseOAuthStore
from tests.test_floor_planner_integration import local_floor_planner_api  # noqa: F401 - loopback fixture

READ_SCOPE = "commons:read"
EDIT_SCOPE = "commons:edit"
provider = ToolProvider("example", lambda mcp, context: None, {},
                        legacy_scopes={"example:read": "read", "example:edit": "edit"})

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
        challenge = client.get("/mcp")

    assert challenge.status_code == 401
    assert 'resource_metadata=' in challenge.headers['www-authenticate']

    assert authorization.status_code == 200
    metadata = authorization.json()
    assert metadata["authorization_endpoint"] == "http://127.0.0.1:8000/authorize"
    assert metadata["token_endpoint"] == "http://127.0.0.1:8000/token"
    assert metadata["revocation_endpoint"] == "http://127.0.0.1:8000/revoke"
    assert set(metadata["scopes_supported"]) == {READ_SCOPE, EDIT_SCOPE}
    # CIMD is off: URL client_ids would make this server fetch caller-chosen URLs.
    assert "client_id_metadata_document_supported" not in metadata
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
    signin_only = oauth.jwt_issuer.issue_access_token("mcp-test-client", [], jti, 3600)
    signin_access = await oauth.load_access_token(signin_only)
    assert signin_access is not None and signin_access.scopes == []
    unknown = oauth.jwt_issuer.issue_access_token("mcp-test-client", ["unknown:read"], jti, 3600)
    assert await oauth.load_access_token(unknown) is None
    assert "_legacy_grants" not in loaded.claims
    # Pre-commons tokens map to commons scopes but keep their old project reach.
    legacy = oauth.jwt_issuer.issue_access_token("mcp-test-client", ["example:read"], jti, 3600)
    legacy_access = await oauth.load_access_token(legacy)
    assert legacy_access.scopes == [READ_SCOPE]
    assert legacy_access.claims["_legacy_grants"] == {"example": ["read"]}
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
@pytest.mark.parametrize("scopes", [[READ_SCOPE], [READ_SCOPE, EDIT_SCOPE], ["example:read", "example:edit"]])
async def test_refresh_keeps_agent_scopes_local_and_revocation_removes_proxy_tokens(monkeypatch, scopes):
    """Legacy refresh tokens keep refreshing until their fixed window ends."""
    import fastmcp.server.auth.oauth_proxy.proxy as oauth_proxy_module

    app = make_agent_app()
    oauth: ResourceBoundOAuthProxy = app.state.cc_mcp_oauth
    client = OAuthClientInformationFull(
        client_id="mcp-refresh-client",
        redirect_uris=["http://localhost/callback"],
        scope=" ".join(scopes),
    )
    upstream_id = uuid4().hex
    old_access_jti = uuid4().hex
    refresh_jti = uuid4().hex
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
        async def aclose(self):
            pass

        def __init__(self, **kwargs):
            calls.append({"auth_method": kwargs["token_endpoint_auth_method"]})

        async def refresh_token(self, **kwargs):
            calls[-1]["request"] = kwargs
            return {
                "access_token": "upstream-test-access-token",
                "refresh_token": "rotated-upstream-refresh",
                "refresh_expires_in": 3600,
                "expires_in": 1200,
                "scope": "openid email",
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
    assert rotated.scope == " ".join(scopes)
    assert rotated.access_token
    assert rotated.refresh_token

    new_access_claims = oauth.jwt_issuer.verify_token(rotated.access_token)
    assert "token_use" not in new_access_claims
    assert oauth.jwt_issuer.verify_token(rotated.refresh_token, expected_token_use="refresh")["token_use"] == "refresh"
    refreshed = await oauth.load_access_token(rotated.access_token)
    assert refreshed.scopes == ([READ_SCOPE] if scopes == [READ_SCOPE] else [READ_SCOPE, EDIT_SCOPE])
    assert ("_legacy_grants" in refreshed.claims) == (scopes[0] != READ_SCOPE)
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
async def test_legacy_clients_and_authorization_requests_move_to_commons_scopes(monkeypatch):
    from mcp.server.auth.provider import AuthorizationParams
    from pydantic import AnyUrl

    app = make_agent_app()
    oauth: ResourceBoundOAuthProxy = app.state.cc_mcp_oauth
    await oauth.register_client(OAuthClientInformationFull(
        client_id="m1-era-client", redirect_uris=["http://localhost/callback"],
        scope="example:read example:edit",
    ))
    client = await oauth.get_client("m1-era-client")
    # A client registered with M1 scopes can reconnect asking for commons scopes.
    assert client.validate_scope("commons:read commons:edit") == [READ_SCOPE, EDIT_SCOPE]
    seen = {}

    async def capture(_self, _client, params):
        seen["scopes"] = params.scopes
        return "http://127.0.0.1:8000/consent"

    monkeypatch.setattr(OAuthProxy, "authorize", capture)
    await oauth.authorize(client, AuthorizationParams(
        state="s", scopes=["example:read", "example:edit", READ_SCOPE], code_challenge="c" * 43,
        redirect_uri=AnyUrl("http://localhost/callback"), redirect_uri_provided_explicitly=True,
    ))
    assert seen["scopes"] == [READ_SCOPE, EDIT_SCOPE]


def declared(name, tools, register=None, **kwargs):
    def default_register(mcp, context):
        for tool in tools:
            mcp.tool(name=tool)(lambda: tool)
    return ToolProvider(name, register or default_register, tools, **kwargs)


def test_startup_requires_unique_providers_and_exactly_declared_tools():
    environment = settings_environment()
    for providers in (
        (provider, provider),
        (declared("one", {"read_one": "read"}), declared("two", {"other": "read"}, register=lambda mcp, context: None)),
        (declared("one", {"read_one": "read"}, register=lambda mcp, context: (mcp.tool(name="read_one")(lambda: 1),
                                                                             mcp.tool(name="sneaky")(lambda: 2))),),
        (declared("one", {"read_one": "signin"}),),
        (declared("one", {"read_one": "admin"}),),
        (declared("one", {}, legacy_scopes={"commons:read": "read"}),),
    ):
        with pytest.raises(AgentConfigError):
            create_agent_app(object(), providers=providers, environment=environment, storage=MemoryStore())
    with TestClient(make_agent_app()) as client:
        scopes = client.get("/.well-known/oauth-authorization-server").json()["scopes_supported"]
    assert set(scopes) == {READ_SCOPE, EDIT_SCOPE}


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


# --- Agent connection index and disconnect (cc_mcp 0003, M4 PR 3) ---------------

USER_A = "2f3d0af8-3714-41b4-9065-37f8a7e2203b"
USER_B = "7a1c3e55-1d0b-4f6e-9b39-5d7ce1f7a001"
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"


class MemoryIndex:
    """cc_mcp_connections in memory, with the touch RPC's rules (the real SQL is
    covered by test_migration_convergence)."""

    def __init__(self):
        self.rows = {}
        self.touches = []

    def install(self, monkeypatch):
        from cc_mcp import connections
        for name in ("touch", "mark_revoked", "active_connections", "own_connection"):
            monkeypatch.setattr(connections, name, getattr(self, name))
        return self

    def touch(self, _client, **row):
        self.touches.append(row)
        existing = self.rows.get(row["upstream_token_id"])
        if existing is None:
            self.rows[row["upstream_token_id"]] = {**row, "id": str(uuid4()), "revoked_at": None}
        elif existing["user_id"] == row["user_id"]:
            used = [value for value in (existing["last_used_at"], row["last_used_at"]) if value]
            existing["last_used_at"] = max(used) if used else None
            existing["expires_at"] = row["expires_at"] or existing["expires_at"]

    def mark_revoked(self, _client, upstream_token_id):
        row = self.rows.get(upstream_token_id)
        if row and row["revoked_at"] is None:
            row["revoked_at"] = "now"

    def active_connections(self, _client, user_id):
        from cc_mcp.connections import LISTED
        return [{field: row[field] for field in LISTED.split(",")} for row in self.rows.values()
                if row["user_id"] == str(user_id) and row["revoked_at"] is None]

    def own_connection(self, _client, user_id, connection_id):
        return next(({"id": row["id"], "upstream_token_id": row["upstream_token_id"], "revoked_at": row["revoked_at"]}
                     for row in self.rows.values() if row["id"] == connection_id and row["user_id"] == str(user_id)),
                    None)

    def only(self):
        assert len(self.rows) == 1
        return next(iter(self.rows.values()))


class SessionVerifier(TokenVerifier):
    """Upstream Supabase access tokens for two synthetic users."""

    USERS = {"upstream-a": USER_A, "upstream-a-refreshed": USER_A, "upstream-b": USER_B}

    def __init__(self):
        super().__init__(required_scopes=[])

    async def verify_token(self, token):
        if token not in self.USERS:
            return None
        return AccessToken(token=token, client_id=OAUTH_CLIENT_ID, scopes=[],
                           claims={"sub": self.USERS[token], "aud": "authenticated"})


class AccountServiceClient:
    """The service client's Auth lookups: browser sessions and upstream agent tokens."""

    SESSIONS = {"session-a": USER_A, "session-b": USER_B, **SessionVerifier.USERS}

    class auth:  # noqa: N801 - mirrors supabase-py's client.auth
        @staticmethod
        def get_user(token):
            from types import SimpleNamespace
            from gotrue.errors import AuthApiError
            if token == "session-anonymous":
                return SimpleNamespace(user=SimpleNamespace(id=USER_B, is_anonymous=True))
            if token not in AccountServiceClient.SESSIONS:
                raise AuthApiError("invalid JWT", 401, None)
            return SimpleNamespace(user=SimpleNamespace(id=AccountServiceClient.SESSIONS[token], is_anonymous=False))


def ping_provider():
    def register(mcp, context):
        @mcp.tool(name="ping")
        def ping() -> str:
            return "pong"
    return ToolProvider("commons", register, {"ping": "signin"})


class LiveRowMemoryStore(MemoryStore):
    """MemoryStore with SupabaseOAuthStore's existing-only puts (its SQL is
    covered by the loopback test below)."""

    async def put(self, key, value, *, collection=None, ttl=None):
        if (oauth_storage.is_existing_only(collection or "default")
                and await self.get(key, collection=collection) is None):
            raise oauth_storage.RowGone(collection)
        await super().put(key, value, collection=collection, ttl=ttl)


def account_app(monkeypatch, oauth_configured=True):
    from commons_account.routes import router as account_router

    service = AccountServiceClient()
    agent = create_agent_app(
        service, providers=(ping_provider(),),
        environment=settings_environment() if oauth_configured else {},
        token_verifier=SessionVerifier(), storage=LiveRowMemoryStore(),
    )
    root = FastAPI()
    root.state.mcp_supabase = service
    root.state.cc_mcp_oauth = getattr(agent.state, "cc_mcp_oauth", None)
    root.include_router(account_router, prefix="/account")
    mount_agent_app(root, agent)
    return root, agent


class FakeUpstream:
    """Supabase's OAuth token endpoint, as the proxy's authlib client sees it."""

    refreshes = 0

    async def aclose(self):
        pass

    def __init__(self, **_kwargs):
        pass

    async def fetch_token(self, **kwargs):
        assert kwargs["code"] == "upstream-code"
        return {"access_token": "upstream-a", "refresh_token": "upstream-refresh-a",
                "expires_in": 3600, "token_type": "Bearer", "scope": "openid email"}

    async def refresh_token(self, **kwargs):
        FakeUpstream.refreshes += 1
        return {"access_token": "upstream-a-refreshed", "refresh_token": "upstream-refresh-a2",
                "expires_in": 3600, "refresh_expires_in": 7200, "scope": "openid email"}


async def approve(browser, client_name="Claude", redirect_uri=CLAUDE_CALLBACK):
    """DCR, PKCE authorize, proxy consent, upstream callback and code exchange over HTTP."""
    import hashlib
    import secrets as token_secrets
    from html.parser import HTMLParser
    from urllib.parse import parse_qs, urlsplit

    registered = await browser.post("/register", json={
        "client_name": client_name, "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "token_endpoint_auth_method": "none", "scope": f"{READ_SCOPE} {EDIT_SCOPE}",
    })
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]
    verifier = token_secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    authorized = await browser.get("/authorize", params={
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "agent-state",
        "scope": f"{READ_SCOPE} {EDIT_SCOPE}", "resource": "http://127.0.0.1:8000/mcp",
    })
    assert authorized.status_code == 302, authorized.text
    consent = await browser.get(urlsplit(authorized.headers["location"])._replace(scheme="", netloc="").geturl())

    class Hidden(HTMLParser):
        values = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "input" and attrs.get("type") == "hidden":
                self.values[attrs["name"]] = attrs.get("value", "")

    form = Hidden()
    form.feed(consent.text)
    upstream = await browser.post("/consent", data={**form.values, "action": "approve"})
    assert upstream.status_code == 302 and upstream.headers["location"].startswith(f"{SUPABASE_URL}/auth/v1/oauth/authorize")
    state = parse_qs(urlsplit(upstream.headers["location"]).query)["state"][0]
    callback = await browser.get("/auth/callback", params={"code": "upstream-code", "state": state})
    assert callback.status_code == 302, callback.text
    code = parse_qs(urlsplit(callback.headers["location"]).query)["code"][0]
    tokens = await browser.post("/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": client_id, "code_verifier": verifier, "resource": "http://127.0.0.1:8000/mcp",
    })
    assert tokens.status_code == 200, tokens.text
    return client_id, tokens.json()


async def call_ping(browser, access_token):
    return await browser.post("/mcp", headers={
        "Authorization": f"Bearer {access_token}", "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "ping", "arguments": {}}})


@pytest.mark.asyncio
async def test_real_oauth_flow_lists_the_connection_and_disconnect_revokes_access_and_refresh(monkeypatch):
    import httpx
    import fastmcp.server.auth.oauth_proxy.proxy as oauth_proxy_module

    index = MemoryIndex().install(monkeypatch)
    monkeypatch.setattr(oauth_proxy_module, "AsyncOAuth2Client", FakeUpstream)
    root, agent = account_app(monkeypatch)
    signed_in = {"Authorization": "Bearer session-a"}
    async with agent.router.lifespan_context(agent):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=root), base_url="http://testserver") as browser:
            client_id, tokens = await approve(browser)

            row = index.only()
            assert (row["user_id"], row["client_id"], row["client_name"], row["redirect_host"]) == (
                USER_A, client_id, "Claude", "claude.ai")
            assert row["scopes"] == [READ_SCOPE, EDIT_SCOPE] and row["approved_at"] and row["expires_at"]
            assert row["last_used_at"] is None  # approved, not used yet
            listed = (await browser.get("/account/connections", headers=signed_in)).json()
            assert [(c["client_name"], c["redirect_host"]) for c in listed] == [("Claude", "claude.ai")]
            assert "upstream_token_id" not in listed[0] and "user_id" not in listed[0]

            used = await call_ping(browser, tokens["access_token"])
            assert used.status_code == 200 and "pong" in used.text
            assert index.only()["last_used_at"]

            refreshed = await browser.post("/token", data={
                "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id})
            assert refreshed.status_code == 200, refreshed.text
            tokens = refreshed.json()
            assert index.only()["expires_at"] > row["approved_at"]
            assert (await call_ping(browser, tokens["access_token"])).status_code == 200

            connection_id = listed[0]["id"]
            assert (await browser.get("/account/connections", headers={"Authorization": "Bearer session-b"})).json() == []
            other = await browser.delete(f"/account/connections/{connection_id}", headers={"Authorization": "Bearer session-b"})
            assert other.status_code == 404
            assert (await call_ping(browser, tokens["access_token"])).status_code == 200  # untouched by the 404

            disconnected = await browser.delete(f"/account/connections/{connection_id}", headers=signed_in)
            assert disconnected.status_code == 204
            assert index.only()["revoked_at"]
            assert (await call_ping(browser, tokens["access_token"])).status_code == 401
            refresh_after = await browser.post("/token", data={
                "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id})
            assert refresh_after.status_code == 401 and refresh_after.json()["error"] == "invalid_grant"
            assert (await browser.get("/account/connections", headers=signed_in)).json() == []
            again = await browser.delete(f"/account/connections/{connection_id}", headers=signed_in)
            assert again.status_code == 204


@pytest.mark.asyncio
async def test_disconnect_revokes_only_that_connection(monkeypatch):
    import httpx
    import fastmcp.server.auth.oauth_proxy.proxy as oauth_proxy_module

    index = MemoryIndex().install(monkeypatch)
    monkeypatch.setattr(oauth_proxy_module, "AsyncOAuth2Client", FakeUpstream)
    root, agent = account_app(monkeypatch)
    signed_in = {"Authorization": "Bearer session-a"}
    async with agent.router.lifespan_context(agent):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=root), base_url="http://testserver") as browser:
            _, first = await approve(browser)
            _, second = await approve(browser, client_name="  Local\n  CLI " + "x" * 200,
                                      redirect_uri="http://127.0.0.1:53682/callback")
            listed = (await browser.get("/account/connections", headers=signed_in)).json()
            names = {c["redirect_host"]: c for c in listed}
            assert set(names) == {"claude.ai", "127.0.0.1"}
            assert names["127.0.0.1"]["client_name"] == ("Local CLI " + "x" * 200)[:80]
            response = await browser.delete(f"/account/connections/{names['claude.ai']['id']}", headers=signed_in)
            assert response.status_code == 204
            assert (await call_ping(browser, first["access_token"])).status_code == 401
            assert (await call_ping(browser, second["access_token"])).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("transparent", [False, True])
async def test_a_refresh_paused_across_a_disconnect_cannot_resurrect_the_connection(monkeypatch, transparent):
    import httpx
    from types import SimpleNamespace
    import fastmcp.server.auth.oauth_proxy.proxy as oauth_proxy_module

    index = MemoryIndex().install(monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()

    class PausedUpstream(FakeUpstream):
        async def refresh_token(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().refresh_token(**kwargs)

    monkeypatch.setattr(oauth_proxy_module, "AsyncOAuth2Client", PausedUpstream)
    signed_out = []
    monkeypatch.setattr(AccountServiceClient.auth, "admin", SimpleNamespace(
        sign_out=lambda jwt, scope: signed_out.append((jwt, scope))), raising=False)
    root, agent = account_app(monkeypatch)
    oauth = agent.state.cc_mcp_oauth
    signed_in = {"Authorization": "Bearer session-a"}
    async with agent.router.lifespan_context(agent):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=root), base_url="http://testserver") as browser:
            client_id, tokens = await approve(browser)
            connection_id = (await browser.get("/account/connections", headers=signed_in)).json()[0]["id"]
            refresh = {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id}

            # FastMCP has read the token set and is waiting on Supabase when the user disconnects.
            if transparent:
                stored = await oauth._upstream_token_store.get(key=index.only()["upstream_token_id"])
                stored.expires_at = 1
                await oauth._upstream_token_store.put(key=stored.upstream_token_id, value=stored, ttl=3600)
                monkeypatch.setattr(SessionVerifier, "USERS", {"upstream-a-refreshed": USER_A})
                refreshing = asyncio.create_task(call_ping(browser, tokens["access_token"]))
            else:
                refreshing = asyncio.create_task(browser.post("/token", data=refresh))
            await asyncio.wait_for(entered.wait(), 5)
            assert (await browser.delete(f"/account/connections/{connection_id}", headers=signed_in)).status_code == 204
            release.set()
            refreshed = await refreshing

            assert refreshed.status_code == 401, refreshed.text
            if not transparent:
                assert refreshed.json()["error"] == "invalid_grant", refreshed.text
            assert await oauth._upstream_token_store.get(key=index.only()["upstream_token_id"]) is None
            assert (await call_ping(browser, tokens["access_token"])).status_code == 401
            assert signed_out == [("upstream-a-refreshed", "local")]  # the new upstream session ends too
            retried = await browser.post("/token", data=refresh)
            assert retried.status_code == 401 and retried.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_repeating_a_disconnect_deletes_tokens_that_outlived_the_first(monkeypatch):
    import httpx
    import fastmcp.server.auth.oauth_proxy.proxy as oauth_proxy_module

    index = MemoryIndex().install(monkeypatch)
    monkeypatch.setattr(oauth_proxy_module, "AsyncOAuth2Client", FakeUpstream)
    root, agent = account_app(monkeypatch)
    oauth = agent.state.cc_mcp_oauth
    signed_in = {"Authorization": "Bearer session-a"}
    async with agent.router.lifespan_context(agent):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=root), base_url="http://testserver") as browser:
            _, tokens = await approve(browser)
            connection_id = (await browser.get("/account/connections", headers=signed_in)).json()[0]["id"]
            upstream_id = index.only()["upstream_token_id"]
            token_set = await oauth._upstream_token_store.get(key=upstream_id)
            assert (await browser.delete(f"/account/connections/{connection_id}", headers=signed_in)).status_code == 204
            assert index.only()["revoked_at"]

            # A token set written back after the first disconnect (as a pre-fix refresh could).
            await oauth._upstream_token_store.put(key=upstream_id, value=token_set, ttl=3600)
            assert (await call_ping(browser, tokens["access_token"])).status_code == 200
            assert (await browser.delete(f"/account/connections/{connection_id}", headers=signed_in)).status_code == 204
            assert await oauth._upstream_token_store.get(key=upstream_id) is None
            assert (await call_ping(browser, tokens["access_token"])).status_code == 401


@pytest.mark.asyncio
async def test_existing_only_puts_update_live_rows_and_never_recreate_deleted_ones(local_floor_planner_api):
    _, service, *_ = local_floor_planner_api
    store = SupabaseOAuthStore(service)
    collection, key = f"test-existing-only-{uuid4().hex}", uuid4().hex
    try:
        with pytest.raises(oauth_storage.RowGone), oauth_storage.ExistingOnly(collection):
            await store.put(key, {"v": 0}, collection=collection, ttl=60)
        assert await store.get(key, collection=collection) is None

        await store.put(key, {"v": 1}, collection=collection, ttl=60)
        with oauth_storage.ExistingOnly(collection):
            await store.put(key, {"v": 2}, collection=collection, ttl=60)
            await store.put(uuid4().hex, {"other": True}, collection="elsewhere-" + collection, ttl=60)
        assert await store.get(key, collection=collection) == {"v": 2}

        assert await store.delete(key, collection=collection)
        with pytest.raises(oauth_storage.RowGone), oauth_storage.ExistingOnly(collection):
            await store.put(key, {"v": 3}, collection=collection, ttl=60)
        assert await store.get(key, collection=collection) is None
    finally:
        await store.destroy_collection(collection)
        await store.destroy_collection("elsewhere-" + collection)


def test_account_connections_require_a_real_session_and_a_configured_connector(monkeypatch):
    MemoryIndex().install(monkeypatch)
    root, _ = account_app(monkeypatch)
    with TestClient(root) as client:
        assert client.get("/account/connections").status_code == 401
        assert client.get("/account/connections", headers={"Authorization": "Bearer expired"}).status_code == 401
        assert client.get("/account/connections",
                          headers={"Authorization": "Bearer session-anonymous"}).status_code == 403
        # An agent's upstream token is not a browser session for another user's data, and a
        # malformed id looks like a missing one.
        assert client.delete("/account/connections/not-a-uuid",
                             headers={"Authorization": "Bearer session-a"}).status_code == 404
        assert client.delete(f"/account/connections/{uuid4()}",
                             headers={"Authorization": "Bearer session-a"}).status_code == 404
    unconfigured, _ = account_app(monkeypatch, oauth_configured=False)
    with TestClient(unconfigured) as client:
        response = client.get("/account/connections", headers={"Authorization": "Bearer session-a"})
        assert response.status_code == 503
        assert client.delete(f"/account/connections/{uuid4()}",
                             headers={"Authorization": "Bearer session-a"}).status_code == 503


async def seed_connection(oauth, *, created_at=1_700_000_000.0, client_name="Pre-M4 agent"):
    """A connection approved before the index existed: tokens in the store, no row."""
    await oauth.register_client(OAuthClientInformationFull(
        client_id="pre-m4-client", client_name=client_name,
        redirect_uris=["https://chatgpt.com/connector/oauth/callback"], scope=f"{READ_SCOPE} {EDIT_SCOPE}",
    ))
    upstream_id, jti = uuid4().hex, uuid4().hex
    await oauth._upstream_token_store.put(key=upstream_id, value=UpstreamTokenSet(
        upstream_token_id=upstream_id, access_token="upstream-a", refresh_token="upstream-refresh-a",
        refresh_token_expires_at=4_000_000_000, expires_at=4_000_000_000, token_type="Bearer",
        scope="openid email", client_id="pre-m4-client", created_at=created_at,
    ), ttl=3600)
    await oauth._jti_mapping_store.put(key=jti, value=JTIMapping(jti=jti, upstream_token_id=upstream_id, created_at=1),
                                       ttl=3600)
    return upstream_id, oauth.jwt_issuer.issue_access_token("pre-m4-client", [READ_SCOPE, EDIT_SCOPE], jti, 3600)


@pytest.mark.asyncio
async def test_use_lazily_indexes_a_pre_index_connection_and_touches_at_most_every_five_minutes(monkeypatch):
    import cc_mcp.server as server_module

    index = MemoryIndex().install(monkeypatch)
    _, agent = account_app(monkeypatch)
    oauth = agent.state.cc_mcp_oauth
    upstream_id, access = await seed_connection(oauth)
    clock = [1000.0]
    monkeypatch.setattr(server_module.time, "monotonic", lambda: clock[0])

    assert await oauth.load_access_token(access)
    row = index.only()
    assert (row["upstream_token_id"], row["user_id"], row["client_name"], row["redirect_host"]) == (
        upstream_id, USER_A, "Pre-M4 agent", "chatgpt.com")
    assert row["approved_at"] == "2023-11-14T22:13:20+00:00"  # the original approval, not first use
    assert row["last_used_at"]
    for _ in range(5):
        assert await oauth.load_access_token(access)
    assert len(index.touches) == 1
    clock[0] += server_module.TOUCH_INTERVAL_SECONDS
    assert await oauth.load_access_token(access)
    assert len(index.touches) == 2


@pytest.mark.asyncio
async def test_index_failures_never_fail_auth_and_client_revoke_marks_the_row(monkeypatch):
    from cc_mcp import connections

    index = MemoryIndex().install(monkeypatch)
    _, agent = account_app(monkeypatch)
    oauth = agent.state.cc_mcp_oauth
    upstream_id, access = await seed_connection(oauth)

    def broken(*_args, **_kwargs):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(connections, "touch", broken)
    assert await oauth.load_access_token(access)  # auth still works; the touch is skipped
    assert index.rows == {}
    monkeypatch.setattr(connections, "touch", index.touch)
    oauth._touched.clear()
    assert await oauth.load_access_token(access)
    assert index.only()["revoked_at"] is None

    refresh_jti = uuid4().hex
    await oauth._jti_mapping_store.put(key=refresh_jti, value=JTIMapping(
        jti=refresh_jti, upstream_token_id=upstream_id, created_at=1), ttl=3600)
    refresh = oauth.jwt_issuer.issue_refresh_token("pre-m4-client", [READ_SCOPE], refresh_jti, 3600)
    await oauth.revoke_token(RefreshToken(token=refresh, client_id="pre-m4-client", scopes=[READ_SCOPE],
                                          expires_at=4_000_000_000))
    assert index.only()["revoked_at"]
    assert await oauth.load_access_token(access) is None


@pytest.mark.asyncio
async def test_url_client_ids_are_never_fetched(monkeypatch):
    from fastmcp.server.auth.cimd import CIMDFetcher

    async def no_fetch(*_args, **_kwargs):
        raise AssertionError("CIMD must stay disabled: unauthenticated callers would choose the URL")

    monkeypatch.setattr(CIMDFetcher, "fetch", no_fetch)
    agent = make_agent_app()
    assert await agent.state.cc_mcp_oauth.get_client("https://example.test/client.json") is None


def test_get_on_the_stateless_mcp_route_challenges_or_refuses_without_streaming():
    agent = make_agent_app()

    async def verify_token(token):
        if token == "proxy-access-token":
            return AccessToken(token=token, client_id="client", scopes=[READ_SCOPE, EDIT_SCOPE])
        return None

    agent.state.cc_mcp_oauth.verify_token = verify_token
    application = FastAPI()
    mount_agent_app(application, agent)
    with TestClient(application) as client:
        anonymous = client.get("/mcp", headers={"Accept": "text/event-stream"})
        anonymous_head = client.head("/mcp")
        authenticated = client.get("/mcp", headers={"Accept": "text/event-stream",
                                                    "Authorization": "Bearer proxy-access-token"})
        authenticated_head = client.head("/mcp", headers={"Authorization": "Bearer proxy-access-token"})
    for challenged in (anonymous, anonymous_head):
        assert challenged.status_code == 401
        assert 'resource_metadata=' in challenged.headers['www-authenticate']
    for refused in (authenticated, authenticated_head):
        assert refused.status_code == 405
        assert refused.headers['allow'] == 'POST, DELETE'
        assert 'text/event-stream' not in refused.headers.get('content-type', '')
