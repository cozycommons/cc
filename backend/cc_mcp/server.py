"""Shared OAuth-protected, resource-scoped Cozy Commons MCP server."""

from __future__ import annotations

import base64
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Callable, Any
from urllib.parse import urlsplit
from uuid import UUID

import jwt
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, JWTVerifier, OAuthProxy, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from mcp.server.auth.provider import RefreshToken
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

from .oauth_storage import SupabaseOAuthStore


@dataclass(frozen=True)
class ToolProvider:
    name: str
    scopes: tuple[str, ...]
    register: Callable[[FastMCP, "ToolContext"], None]


@dataclass(frozen=True)
class ToolContext:
    service_client: Any

    @staticmethod
    def need_scope(*required: str) -> AccessToken:
        access = get_access_token()
        if access is None:
            raise ToolError("Sign in to Cozy Commons to use these tools.")
        if not set(required).issubset(access.scopes):
            raise ToolError("Missing permission: " + ", ".join(required) + ". Reconnect with the required scopes.")
        return access

    async def signed_in_user(self, access: AccessToken):
        try:
            user = await run_in_threadpool(lambda: self.service_client.auth.get_user(access.token).user)
        except Exception as error:
            raise ToolError("Your Cozy Commons sign-in expired. Reconnect your agent.") from error
        if not user:
            raise ToolError("Sign in to Cozy Commons to use these tools.")
        return user


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


class ResourceBoundOAuthProxy(OAuthProxy):
    """Keep MCP scopes local and upstream Supabase credentials server-side."""

    def __init__(self, *args, default_scopes=(), **kwargs):
        super().__init__(*args, **kwargs)
        self._resource_scopes = frozenset(kwargs.get("valid_scopes", ()))
        # The upstream Supabase server has no RFC 7009 endpoint, but MCP clients
        # still need a local endpoint to revoke proxy-issued tokens.
        self.revocation_options = RevocationOptions(enabled=True)
        # DCR clients that omit scope get explicit read and edit consent by default.
        self._default_scope_str = " ".join(default_scopes)

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

    async def load_access_token(self, token: str) -> AccessToken | None:
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
        if not scopes or set(scopes) - self._resource_scopes:
            return None
        claims = {
            **access.claims,
            "_fastmcp_jti": jti,
            "_upstream_token_id": mapping.upstream_token_id,
        }
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

    names = [provider.name for provider in providers]
    scopes = [scope for provider in providers for scope in provider.scopes]
    if len(set(names)) != len(names) or len(set(scopes)) != len(scopes):
        raise AgentConfigError("Tool provider names and scopes must be unique.")
    if not scopes:
        raise AgentConfigError("At least one tool provider must be registered.")
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
        valid_scopes=scopes,
        default_scopes=scopes,
        extra_authorize_params={"scope": "openid email"},
        client_storage=storage,
        jwt_signing_key=settings.jwt_signing_key,
        require_authorization_consent=True,
    )
    mcp = FastMCP("Cozy Commons", auth=oauth, on_duplicate_tools="error")

    context = ToolContext(service_client)
    for provider in providers:
        provider.register(mcp, context)

    app = mcp.http_app(path=MCP_PATH, transport="streamable-http", stateless_http=True)
    app.state.cc_mcp_oauth = oauth
    app.state.cc_mcp = mcp
    return app
