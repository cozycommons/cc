# Cozy Commons MCP

One connection and browser sign-in serves deliberately registered feature tool
sets. Floor Planner is the first provider; existing Beli, Resy, Partiful and ESPN
MCP endpoints are not automatically exposed through it.

## Connection and deployment

The deployment endpoint is `https://api.cozycommons.dev/mcp`.
Its OAuth callback is `/auth/callback`, authorization metadata is at
`/.well-known/oauth-authorization-server`, and resource metadata is at
`/.well-known/oauth-protected-resource/mcp`. Mount it after explicit API
routes, so existing REST routes and feature-specific MCP endpoints keep working.
MCP clients dynamically register with this proxy and must support remote MCP
over Streamable HTTP with OAuth authorization code and PKCE.

The proxy uses the Supabase Auth OAuth server as the identity provider. Before
enabling it in a deployment, enable that server and register a confidential
Cozy Commons MCP application. Configure its redirect URI to exactly
`<CC_MCP_BASE_URL>/auth/callback`, and use the registered client ID
and secret as the MCP upstream credentials. Supabase token endpoint
authentication is `client_secret_basic`. The web application must route
Supabase's configured OAuth authorization page to `/oauth/consent` so users
can approve or deny a connection in their existing signed-in session. Set Supabase Auth's Site URL to the deployed frontend origin and its authorization
page path to `/oauth/consent`. The local stack defaults to port 8080; use that
port or update the local Site URL when running another frontend port. Keep
upstream dynamic client registration disabled; MCP clients register with the
Cozy Commons proxy instead.

The API needs these deployment settings:

- `CC_MCP_BASE_URL`: public HTTPS API origin without a path (for example
  `https://api.cozycommons.dev`).
- `CC_MCP_OAUTH_CLIENT_ID` and
  `CC_MCP_OAUTH_CLIENT_SECRET`: the registered Supabase OAuth app.
- `CC_MCP_JWT_SIGNING_KEY`: base64url encoding of 32 random bytes,
  used only to sign resource-bound proxy access and refresh tokens.
- `CC_MCP_STORAGE_ENCRYPTION_KEY`: a Fernet key for encrypting
  upstream OAuth state before it is written to Postgres.
- `SUPABASE_URL`: the existing Supabase project URL.

If any required setting is missing or invalid, the main API still starts and
Cozy Commons MCP requests return `503` with an explicit unavailable message.
There is no memory or local-disk fallback. Migration
`0001_cc_mcp_oauth_state.sql` creates the service-role-only state
table; the service client encrypts values with Fernet before PostgREST writes
them. Browser roles receive no table access.

The OAuth server's OIDC scopes are `openid email`. These scopes identify the
user; they do not limit Supabase database permissions. The proxy issues its
own JWTs with audience bound to the `/mcp` resource and keeps
`floor-plans:read` and `floor-plans:edit` scopes in those local tokens. Raw
Supabase session tokens are rejected by MCP. Tools use the shared context to
validate the current user with Supabase Auth.
Each feature owns its account binding, authorization, and write validation.
Floor Planner additionally requires a verified email and revision-checked
writes. The upstream JWT
verifier accepts asymmetric ES256 or RS256 signatures and checks the Supabase
issuer, `authenticated` audience, and registered OAuth `client_id`.

Refreshing rotates the proxy's access and refresh token references; local
agent scopes are not sent as Supabase scopes. Revoking a refresh token removes
its reference and encrypted upstream token set, immediately invalidating all
access references in that grant; sibling access-reference rows expire with
their JWTs. A user can also revoke the Cozy Commons application grant in
Supabase Auth; already-issued access JWTs may remain valid until their expiry,
so clients should disconnect and reconnect after a grant change. No user can
use the MCP connection to change sharing, visibility, ownership, or plan
deletion.

Production OAuth settings are configured separately from this code;
the application must remain unavailable until an administrator registers and
configures its confidential Supabase OAuth client and the deployment keys.

## Adding a feature

The composition root in `backend/main.py` explicitly passes providers into
`create_agent_app`. The shared package never imports feature modules. A provider
supplies a unique name, its unique permission scopes, and a registration function:

```python
from cc_mcp.server import ToolProvider


def register_tools(mcp, context):
    @mcp.tool(annotations={"readOnlyHint": True})
    async def list_trips():
        access = context.need_scope("trips:read")
        user = await context.signed_in_user(access)
        # Query only trips this user is authorized to read.
        return await list_authorized_trips(user.id)


provider = ToolProvider("trips", ("trips:read",), register_tools)
```

Register that provider alongside Floor Planner in the composition root. This is
an illustration, not an implemented Trips tool. Every private-data tool must
check its scope, obtain a current user, and enforce its feature's membership
rules. A connection does not grant access to every record or bypass existing
permissions. Tool names and scopes must be unique across providers.

Clients should request only the scopes needed for their task. Clients that omit
scopes are prompted for the currently registered scopes; adding a provider does
not expand existing tokens. Reconnect and consent to acquire new permissions.

The shared `cc_mcp` migration family has no dependency on Floor Planner tables.
Run the canonical migration runner with `--family cc_mcp`, or use the shared
release runner which applies all families. `/ready` attests its service-only
OAuth table and grants. Keep signing/encryption keys stable across replicas and
restarts; rotating them invalidates existing connections. Never put those keys
or upstream credentials in the frontend.

## Validation and limitations

Shared auth tests cover JWT issuer/audience/client checks, scoped tokens,
refresh isolation, revocation, and discovery. The Floor Planner protocol test
uses real loopback Supabase state to exercise its provider through the shared
endpoint. Local browser OAuth, tool edits, refresh, and restart persistence were
verified during development. Native Codex and Claude client setup and production
OAuth configuration still need deployment validation. USDZ scans remain private
to collaborators and are not exposed by the MCP tools.
