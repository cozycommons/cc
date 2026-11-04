"""Shared OAuth-protected, resource-scoped Cozy Commons MCP server."""

from __future__ import annotations

import base64
import logging
import os
import time
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Callable, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import jwt
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, JWTVerifier, OAuthProxy, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import AuthorizationParams, RefreshToken
from mcp.server.auth.settings import RevocationOptions
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route, request_response
from mcp.server.streamable_http import MCP_PROTOCOL_VERSION_HEADER
from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE, RequestBodyLimitMiddleware

from . import connections, projects
from .oauth_storage import SupabaseOAuthStore

logger = logging.getLogger(__name__)

# Two stable scopes cover every project. Adding a project or tool never changes
# them, so existing connections keep working; per-user enablement picks projects.
READ_SCOPE = "commons:read"
EDIT_SCOPE = "commons:edit"
SCOPES = (READ_SCOPE, EDIT_SCOPE)
COMMONS = "commons"
Access = Literal["signin", "read", "edit"]
LEVEL_SCOPE = {"signin": None, "read": READ_SCOPE, "edit": EDIT_SCOPE}
SIGN_IN_MESSAGE = "Sign in to Cozy Commons to use these tools."


@dataclass(frozen=True)
class AccountLink:
    """One-time proof that the signed-in Commons user owns a project account.

    `linked(service_client, user)` returns a non-secret account summary or None.
    Until linked, every project tool except `tool` returns `instructions`.
    """

    instructions: str
    linked: Callable[[Any, Any], dict | None]
    tool: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class ToolProvider:
    """The project contract: see docs/mcp/README.md, "Adding a project".

    `tools` declares every tool the provider registers and its access level;
    startup fails if registration and declaration differ. `status` must be cheap
    and read-only; its `in_use` flag enables the project by default for people
    who already use it. `legacy_scopes` maps pre-commons scopes to a level that
    is honored for this project only, until those tokens expire.
    """

    name: str
    register: Callable[[FastMCP, "ToolContext"], None]
    tools: Mapping[str, Access]
    title: str = ""
    description: str = ""
    url: str = ""
    status: Callable[[Any, Any], dict] | None = None
    link: AccountLink | None = None
    legacy_scopes: Mapping[str, Access] = field(default_factory=dict)

    @property
    def display_name(self):
        return self.title or self.name


# One resolved user per request token: the middleware and the tool share it.
_request_user: ContextVar[tuple[str, Any] | None] = ContextVar("cc_mcp_request_user", default=None)


@dataclass(frozen=True)
class ToolContext:
    service_client: Any
    providers: tuple[ToolProvider, ...] = ()

    @staticmethod
    def need_scope(*required: str) -> AccessToken:
        access = get_access_token()
        if access is None:
            raise ToolError(SIGN_IN_MESSAGE)
        if not set(required).issubset(access.scopes):
            missing = ", ".join(sorted(set(required) - set(access.scopes)))
            raise ToolError(f"Missing permission: {missing}. Reconnect your agent to grant {missing}.")
        return access

    async def signed_in_user(self, access: AccessToken):
        cached = _request_user.get()
        if cached and cached[0] == access.token:
            return cached[1]
        try:
            user = await run_in_threadpool(lambda: self.service_client.auth.get_user(access.token).user)
        except Exception as error:
            raise ToolError("Your Cozy Commons sign-in expired. Reconnect your agent.") from error
        if not user:
            raise ToolError(SIGN_IN_MESSAGE)
        _request_user.set((access.token, user))
        return user

    def provider(self, name: str) -> ToolProvider | None:
        return next((provider for provider in self.providers if provider.name == name), None)


def legacy_grants(access: AccessToken) -> dict | None:
    """Per-project levels for a token issued before commons scopes, else None."""
    return access.claims.get("_legacy_grants") if access.claims else None


def check_access(access: AccessToken | None, provider: ToolProvider, level: Access) -> AccessToken:
    if access is None:
        raise ToolError(SIGN_IN_MESSAGE)
    scope = LEVEL_SCOPE[level]
    if scope and scope not in access.scopes:
        raise ToolError(f"Missing permission: {scope}. Reconnect your agent to grant {scope}.")
    grants = legacy_grants(access)
    # Legacy edit tools also required the project's read scope; never let another
    # project's translated grant stand in for it.
    needed = {"read", "edit"} if level == "edit" else {level}
    if scope and grants is not None and not needed.issubset(grants.get(provider.name, ())):
        raise ToolError(
            f"This connection was approved before {provider.display_name} joined the connector. "
            "Reconnect your agent once to grant commons:read and commons:edit."
        )
    return access


class ProjectAccessMiddleware(Middleware):
    """Show and allow only the signed-in user's enabled projects' tools.

    Hiding is not authorization: every call is checked again here, after the
    scope check and before the tool runs, and refused with the exact fix.
    """

    def __init__(self, context: ToolContext, tools: Mapping[str, tuple[ToolProvider, Access]]):
        self.context = context
        self.tools = tools

    async def _states(self, access, providers):
        user = await self.context.signed_in_user(access)
        return await run_in_threadpool(
            projects.project_states, self.context.service_client, user, providers, False
        )

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)
        visible = {COMMONS}
        access = get_access_token()
        if access is not None:
            try:
                states = await self._states(access, [p for p in self.context.providers if p.name != COMMONS])
                visible |= {name for name, state in states.items() if state["enabled"]}
            except ToolError:
                pass

        def allowed(name):
            provider, level = self.tools[name]
            try:
                check_access(access, provider, level)
            except ToolError:
                return False
            return provider.name in visible

        return [tool for tool in tools if tool.key in self.tools and allowed(tool.key)]

    async def on_call_tool(self, context, call_next):
        entry = self.tools.get(context.message.name)
        if entry is None:
            # Only declared, registered tools are callable; this fails closed on mounts.
            raise ToolError(f"Unknown tool {context.message.name!r}. Call list_projects to see available tools.")
        provider, level = entry
        access = check_access(get_access_token(), provider, level)
        if provider.name != COMMONS:
            state = (await self._states(access, [provider]))[provider.name]
            if not state["enabled"]:
                raise ToolError(
                    f"{provider.display_name} is not enabled; call enable_project('{provider.name}')."
                )
            if provider.link and context.message.name != provider.link.tool and not state["linked"]:
                raise ToolError(
                    f"Link your {provider.display_name} account first: {provider.link.instructions}"
                )
        return await call_next(context)


MCP_PATH = "/mcp"
CALLBACK_PATH = "/auth/callback"
AUTH_DISABLED_MESSAGE = "Cozy Commons agent access is not configured."


class AgentConfigError(ValueError):
    """OAuth configuration is absent or unsafe; MCP remains unavailable."""


@dataclass(frozen=True)
class AgentSettings:
    base_url: str
    supabase_url: str
    oauth_client_id: str
    oauth_client_secret: str
    jwt_signing_key: bytes
    storage_encryption_key: bytes

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None):
        values = os.environ if environment is None else environment
        names = (
            "CC_MCP_BASE_URL",
            "CC_MCP_OAUTH_CLIENT_ID",
            "CC_MCP_OAUTH_CLIENT_SECRET",
            "CC_MCP_JWT_SIGNING_KEY",
            "CC_MCP_STORAGE_ENCRYPTION_KEY",
            "SUPABASE_URL",
        )
        missing = [name for name in names if not values.get(name, "").strip()]
        if missing:
            raise AgentConfigError("Required Cozy Commons MCP settings are missing.")

        base_url = values["CC_MCP_BASE_URL"].rstrip("/")
        base = urlsplit(base_url)
        if (
            base.scheme not in {"https", "http"}
            or not base.hostname
            or base.username
            or base.password
            or base.query
            or base.fragment
            or (base.scheme != "https" and base.hostname not in {"localhost", "127.0.0.1", "::1"})
            or base.path not in {"", "/"}
        ):
            raise AgentConfigError("Cozy Commons MCP base URL must be an HTTPS origin (HTTP is loopback-only).")

        supabase_url = values["SUPABASE_URL"].rstrip("/")
        upstream = urlsplit(supabase_url)
        if (
            upstream.scheme not in {"https", "http"}
            or not upstream.hostname
            or upstream.username
            or upstream.password
            or upstream.path not in {"", "/"}
            or upstream.query
            or upstream.fragment
            or (upstream.scheme != "https" and upstream.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise AgentConfigError("Supabase URL must use HTTPS (HTTP is loopback-only).")

        try:
            jwt_key = base64.b64decode(
                values["CC_MCP_JWT_SIGNING_KEY"], altchars=b"-_", validate=True
            )
            storage_key = values["CC_MCP_STORAGE_ENCRYPTION_KEY"].encode("ascii")
            from cryptography.fernet import Fernet

            Fernet(storage_key)
        except Exception as error:
            raise AgentConfigError("Cozy Commons MCP signing and encryption keys must be valid base64 keys.") from error
        if len(jwt_key) != 32:
            raise AgentConfigError("Cozy Commons MCP JWT signing key must decode to 32 bytes.")

        return cls(
            base_url=base_url,
            supabase_url=supabase_url,
            oauth_client_id=values["CC_MCP_OAUTH_CLIENT_ID"].strip(),
            oauth_client_secret=values["CC_MCP_OAUTH_CLIENT_SECRET"].strip(),
            jwt_signing_key=jwt_key,
            storage_encryption_key=storage_key,
        )


class SupabaseOAuthTokenVerifier(TokenVerifier):
    """Verify Supabase OAuth access JWTs before the proxy maps them to a user."""

    def __init__(self, settings: AgentSettings):
        super().__init__(required_scopes=[])
        issuer = f"{settings.supabase_url}/auth/v1"
        jwks_uri = f"{issuer}/.well-known/jwks.json"
        self._oauth_client_id = settings.oauth_client_id
        self._verifiers = {
            algorithm: JWTVerifier(
                jwks_uri=jwks_uri,
                issuer=issuer,
                audience="authenticated",
                algorithm=algorithm,
                required_scopes=[],
            )
            for algorithm in ("ES256", "RS256")
        }

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            algorithm = jwt.get_unverified_header(token).get("alg")
        except jwt.PyJWTError:
            return None
        verifier = self._verifiers.get(algorithm)
        if verifier is None:
            return None
        verified = await verifier.verify_token(token)
        if not verified:
            return None
        claims = verified.claims
        if claims.get("client_id") != self._oauth_client_id:
            return None
        expires_at = claims.get("exp")
        if (
            not isinstance(expires_at, (int, float))
            or isinstance(expires_at, bool)
            or expires_at <= time.time()
        ):
            return None
        try:
            UUID(str(claims.get("sub")))
        except (TypeError, ValueError):
            return None
        audience = claims.get("aud")
        if audience != "authenticated" and not (
            isinstance(audience, list) and "authenticated" in audience
        ):
            return None
        return verified


# A connection's last_used_at is written at most this often per worker.
TOUCH_INTERVAL_SECONDS = 300


class ResourceBoundOAuthProxy(OAuthProxy):
    """Keep MCP scopes local and upstream Supabase credentials server-side.

    With `index_client`, approvals, refreshes and use also write the
    cc_mcp_connections index (best effort: an index failure never fails auth).
    """

    def __init__(self, *args, default_scopes=(), legacy_scopes=None, index_client=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._index_client = index_client
        self._touched: dict[str, float] = {}
        self._resource_scopes = frozenset(kwargs.get("valid_scopes", ()))
        # Pre-commons scope -> (project, level). Tokens issued before commons
        # scopes keep exactly their old per-project reach until they expire.
        self._legacy_scopes = dict(legacy_scopes or {})
        # The upstream Supabase server has no RFC 7009 endpoint, but MCP clients
        # still need a local endpoint to revoke proxy-issued tokens.
        self.revocation_options = RevocationOptions(enabled=True)
        # DCR clients that omit scope get explicit read and edit consent by default.
        self._default_scope_str = " ".join(default_scopes)

    def _current_scopes(self, scopes) -> list[str]:
        """Translate requested legacy scopes to their commons equivalents."""
        translated = []
        for scope in scopes:
            if scope in self._legacy_scopes:
                scope = LEVEL_SCOPE[self._legacy_scopes[scope][1]]
            if scope and scope not in translated:
                translated.append(scope)
        return translated

    async def get_client(self, client_id: str):
        client = await super().get_client(client_id)
        # Clients registered before commons scopes may request them on reconnect.
        if client is not None and client.scope:
            registered = client.scope.split()
            current = self._current_scopes(registered)
            client.scope = " ".join([*registered, *(s for s in current if s not in registered)])
        return client

    async def authorize(self, client, params: AuthorizationParams) -> str:
        # New grants only ever carry commons scopes; consent shows those.
        if params.scopes:
            params = params.model_copy(update={"scopes": self._current_scopes(params.scopes)})
        return await super().authorize(client, params)

    def _prepare_scopes_for_upstream_refresh(self, scopes: list[str]) -> list[str]:
        # FastMCP scopes authorize tools; Supabase receives only its OIDC scopes.
        return []

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        revocation = RevocationHandler(self, ClientAuthenticator(self))
        authenticator = ClientAuthenticator(self)

        async def handle_revocation(request: Request):
            form_data = await request.form()
            if form_data.get("client_secret") is None:
                # MCP's pinned auth SDK models client_secret as required even for
                # public clients. Authenticate the original request first, then
                # add the optional empty field expected by its RFC 7009 handler.
                try:
                    await authenticator.authenticate_request(request)
                except AuthenticationError:
                    return await revocation.handle(request)
                request._form = FormData(
                    [*form_data.multi_items(), ("client_secret", "")]
                )
            return await revocation.handle(request)

        revocation_endpoint = CORSMiddleware(
            app=RequestBodyLimitMiddleware(
                request_response(handle_revocation), DEFAULT_MAX_REQUEST_BODY_SIZE
            ),
            allow_origins=["*"],
            allow_methods=["POST", "OPTIONS"],
            allow_headers=[MCP_PROTOCOL_VERSION_HEADER],
        )
        for index, route in enumerate(routes):
            if isinstance(route, Route) and route.path == "/revoke":
                routes[index] = Route(
                    "/revoke",
                    endpoint=revocation_endpoint,
                    methods=["POST", "OPTIONS"],
                )
                break
        return routes

    async def exchange_authorization_code(self, client, authorization_code):
        issued = await super().exchange_authorization_code(client, authorization_code)
        await self._index(issued.access_token, used=False,
                          redirect_host=connections.redirect_host(authorization_code.redirect_uri))
        return issued

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        issued = await super().exchange_refresh_token(client, refresh_token, scopes)
        await self._index(issued.access_token, used=False)  # moves expires_at
        return issued

    async def load_access_token(self, token: str) -> AccessToken | None:
        access = await self._load_access_token(token)
        if access is None:
            return None
        # Throttled per worker; this also indexes connections approved before
        # the index existed the first time they are used.
        upstream_token_id = access.claims["_upstream_token_id"]
        now = time.monotonic()
        if now - self._touched.get(upstream_token_id, -TOUCH_INTERVAL_SECONDS) >= TOUCH_INTERVAL_SECONDS:
            if len(self._touched) > 10_000:
                self._touched = {key: at for key, at in self._touched.items() if now - at < TOUCH_INTERVAL_SECONDS}
            self._touched[upstream_token_id] = now
            await self._index(token, used=True, access=access)
        return access

    async def _index(self, token: str, *, used: bool, redirect_host: str | None = None,
                     access: AccessToken | None = None) -> None:
        if self._index_client is None:
            return
        try:
            access = access or await self._load_access_token(token)
            if access is None:
                return
            upstream_token_id = access.claims["_upstream_token_id"]
            tokens = await self._upstream_token_store.get(key=upstream_token_id)
            if tokens is None:
                return
            client = await self.get_client(access.client_id)
            if redirect_host is None and client is not None:
                redirect_host = connections.redirect_host(*(client.redirect_uris or ()))
            await run_in_threadpool(
                connections.touch, self._index_client,
                upstream_token_id=upstream_token_id,
                user_id=access.claims["sub"],
                client_id=access.client_id,
                client_name=connections.client_label(getattr(client, "client_name", None)),
                redirect_host=redirect_host,
                scopes=access.scopes,
                approved_at=connections.timestamp(tokens.created_at),
                expires_at=connections.timestamp(tokens.refresh_token_expires_at or tokens.expires_at),
                last_used_at=connections.timestamp(time.time()) if used else None,
            )
        except Exception:  # noqa: BLE001 - the index is display data; auth never depends on it.
            logger.warning("Agent connection index write failed", exc_info=True)

    async def _mark_revoked(self, upstream_token_id: str) -> None:
        if self._index_client is None:
            return
        try:
            await run_in_threadpool(connections.mark_revoked, self._index_client, upstream_token_id)
        except Exception:  # noqa: BLE001 - the tokens are already gone; the row expires with them.
            logger.warning("Agent connection index revoke failed", exc_info=True)

    async def _load_access_token(self, token: str) -> AccessToken | None:
        try:
            local_claims = self.jwt_issuer.verify_token(token)
        except Exception:
            return None
        if local_claims.get("token_use", "access") != "access":
            return None
        jti = local_claims.get("jti")
        mapping = await self._jti_mapping_store.get(key=jti) if isinstance(jti, str) else None
        if not mapping:
            return None
        access = await super().load_access_token(token)
        if not access:
            return None
        scopes = local_claims.get("scope", "").split()
        if set(scopes) - self._resource_scopes - set(self._legacy_scopes):
            return None
        claims = {
            **access.claims,
            "_fastmcp_jti": jti,
            "_upstream_token_id": mapping.upstream_token_id,
        }
        claims.pop("_legacy_grants", None)  # only this proxy may set it
        legacy = [scope for scope in scopes if scope in self._legacy_scopes]
        if legacy:
            grants: dict[str, list[str]] = {}
            for scope in legacy:
                project, level = self._legacy_scopes[scope]
                grants.setdefault(project, []).append(level)
            claims["_legacy_grants"] = grants
            scopes = self._current_scopes(scopes)
        return access.model_copy(
            update={
                "client_id": local_claims.get("client_id"),
                "scopes": scopes,
                "claims": claims,
            }
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, RefreshToken):
            try:
                claims = self.jwt_issuer.verify_token(token.token)
            except Exception:
                return
            jti = claims.get("jti")
            mapping = await self._jti_mapping_store.get(key=jti) if jti else None
            if mapping:
                if jti:
                    await self._jti_mapping_store.delete(key=jti)
                await self._revoke_proxy_token_set(mapping.upstream_token_id)
                await self._mark_revoked(mapping.upstream_token_id)
            await super().revoke_token(token)
            return

        jti = token.claims.get("_fastmcp_jti")
        if jti:
            await self._jti_mapping_store.delete(key=jti)

    async def _revoke_proxy_token_set(self, upstream_token_id: str) -> None:
        # Removing the upstream credential invalidates every access/refresh
        # reference in the family. Other access JTI rows expire with their JWTs.
        await self._upstream_token_store.delete(key=upstream_token_id)


async def _unavailable(_request: Request) -> JSONResponse:
    return JSONResponse(
        {"detail": AUTH_DISABLED_MESSAGE},
        status_code=503,
        headers={"Cache-Control": "private, no-store"},
    )


def unavailable_agent_app() -> Starlette:
    paths = (MCP_PATH, "/authorize", "/token", "/register", "/revoke", "/consent",
             CALLBACK_PATH, "/.well-known/oauth-authorization-server",
             "/.well-known/oauth-protected-resource/mcp")
    return Starlette(routes=[
        Route(path, _unavailable, methods=["GET", "POST", "DELETE", "OPTIONS"])
        for path in paths
    ])


def create_agent_app(
    service_client,
    *,
    providers: tuple[ToolProvider, ...] = (),
    environment: Mapping[str, str] | None = None,
    token_verifier: TokenVerifier | None = None,
    storage=None,
) -> Starlette:
    """Build the MCP ASGI app; absent or invalid OAuth setup fails closed at 503."""
    try:
        settings = AgentSettings.from_environment(environment)
    except AgentConfigError:
        return unavailable_agent_app()

    verifier = token_verifier or SupabaseOAuthTokenVerifier(settings)
    if storage is None:
        from cryptography.fernet import Fernet
        from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

        storage = FernetEncryptionWrapper(
            key_value=SupabaseOAuthStore(service_client),
            fernet=Fernet(settings.storage_encryption_key),
            raise_on_decryption_error=True,
        )

    oauth = ResourceBoundOAuthProxy(
        upstream_authorization_endpoint=f"{settings.supabase_url}/auth/v1/oauth/authorize",
        upstream_token_endpoint=f"{settings.supabase_url}/auth/v1/oauth/token",
        upstream_client_id=settings.oauth_client_id,
        upstream_client_secret=settings.oauth_client_secret,
        token_endpoint_auth_method="client_secret_basic",
        token_verifier=verifier,
        base_url=settings.base_url,
        redirect_path=CALLBACK_PATH,
        valid_scopes=list(SCOPES),
        default_scopes=SCOPES,
        legacy_scopes={
            scope: (provider.name, level)
            for provider in providers for scope, level in provider.legacy_scopes.items()
        },
        extra_authorize_params={"scope": "openid email"},
        client_storage=storage,
        jwt_signing_key=settings.jwt_signing_key,
        require_authorization_consent=True,
        index_client=service_client,
    )
    mcp = build_server(service_client, providers, auth=oauth)
    app = mcp.http_app(path=MCP_PATH, transport="streamable-http", stateless_http=True)
    app.state.cc_mcp_oauth = oauth
    app.state.cc_mcp = mcp
    return app


INSTRUCTIONS = (
    "Call list_projects first to discover projects, which are enabled for this user, and setup steps. "
    "Call enable_project(project_id) to add a project's tools; refresh your tool list if they do not appear. "
    "Use exact IDs and integer cents. Preview every write with dry_run=true, review it with the user, "
    "then repeat with dry_run=false and the same idempotency_key. Never infer an ID from a name. "
    "Errors name the fix: follow them (enable a project, link an account or reconnect)."
)


def build_server(service_client, providers: tuple[ToolProvider, ...], *, auth=None) -> FastMCP:
    """Register providers, validate their declared tools and install access middleware."""
    names = [provider.name for provider in providers]
    if len(set(names)) != len(names):
        raise AgentConfigError("Tool provider names must be unique.")
    legacy = [scope for provider in providers for scope in provider.legacy_scopes]
    if len(set(legacy)) != len(legacy) or set(legacy) & set(SCOPES):
        raise AgentConfigError("Legacy scopes must be unique and distinct from commons scopes.")

    mcp = FastMCP("Cozy Commons", auth=auth, on_duplicate_tools="error", instructions=INSTRUCTIONS)
    context = ToolContext(service_client, tuple(providers))
    registry: dict[str, tuple[ToolProvider, Access]] = {}
    for provider in providers:
        before = set(mcp._tool_manager._tools)
        provider.register(mcp, context)
        registered = set(mcp._tool_manager._tools) - before
        if registered != set(provider.tools):
            raise AgentConfigError(
                f"Provider {provider.name} must declare exactly the tools it registers: "
                f"undeclared {sorted(registered - set(provider.tools))}, "
                f"missing {sorted(set(provider.tools) - registered)}."
            )
        for tool, level in provider.tools.items():
            allowed = {"signin"} if provider.name == COMMONS else {"read", "edit"}
            if level not in allowed:
                raise AgentConfigError(f"Tool {tool} must declare one of {sorted(allowed)}.")
            registry[tool] = (provider, level)
        if provider.link and provider.link.tool and provider.link.tool not in provider.tools:
            raise AgentConfigError(f"Link tool {provider.link.tool} is not a {provider.name} tool.")
    if mcp._mounted_servers:
        raise AgentConfigError("Providers must register tools directly; mounted servers bypass validation.")
    mcp.add_middleware(ProjectAccessMiddleware(context, registry))
    return mcp
