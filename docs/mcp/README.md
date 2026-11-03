# Cozy Commons MCP

One connection and browser sign-in serves deliberately registered feature tool
sets: Commons discovery, Floor Planner, and Trips. Existing Beli, Resy, Partiful
and ESPN MCP endpoints keep their separate pasted-token authentication.

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
`floor-plans:read`, `floor-plans:edit`, `trips:read`, and `trips:edit` scopes in those local tokens. Raw
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
`create_agent_app`. The shared server never imports feature modules; the Commons
registry owns its feature status callbacks. A provider
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

This minimal example illustrates the provider interface; the implemented Trips
provider is `backend/trips/agent_tools.py`. Every feature-data tool must
check its scope, obtain a current user, and enforce its feature's membership
rules. A connection does not grant access to every record or bypass existing
permissions. Tool names, provider names and scopes must be unique across providers. A provider
may declare zero scopes (Commons does); the combined scope set must be nonempty.
A valid proxy token with no feature scopes can use the sign-in-only tools;
unknown scopes remain rejected.

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

## Commons discovery and Trips

Call `list_projects` first. `whoami` and `list_projects` require a current Commons
sign-in without any additional feature scope. The project registry includes all
public frontend projects plus the four separate MCP integrations. Read-only,
cheap status callbacks report trip counts and owned/accepted shared plans;
other projects return an explicit setup URL or unknown status. Status lookup
failures do not prevent discovery. M3 can attach a status callback to each
`Project` without changing the shared server.

`get_trip_overview` needs `trips:read`. Omit `trip_id` to list authorized trips;
pass it to get member IDs, names, Venmo usernames, currency, revision, integer
balances and settlement payments. Trips does not currently store travel dates;
list entries therefore return `dates: null`. Settlement reuses the canonical
fewest-payment solver up to 16 nonzero balances, with its deterministic greedy
fallback above that limit. Venmo links use existing handle validation and URL
helpers, and require USD and the appropriate payer/payee handle. A missing link
is null. Links do not execute a payment.

`add_expense` and `record_repayment` need `trips:edit`, exact trip/member IDs,
positive integer cents and a required `idempotency_key` (1–200 characters).
Preview with `dry_run=true` (the default), review with the user, then submit
`dry_run=false` with the same key and arguments. Preview does not reserve a key
or change a revision. Repayment records money already paid; it never sends money.
All reads and writes check the signed-in user's trip membership. Unknown member
IDs/names return suggested member names with exact IDs; names are never resolved
automatically. Money is in the trip currency's minor units, returned as currency
alongside cents; no currency conversion occurs.

Expenses accept `payers: [{member_id, amount_cents}]` totaling `total_cents`, and
`member_ids` listing participants exactly once. `split_mode` is `even`, `percent`
or `exact`. For percent, `parts` maps every participant ID to positive integer
basis points totaling 10000 (1250 = 12.5%); largest remainders get pennies first,
with trip member order breaking ties. Even splits give remainder pennies in
trip member order. Exact parts are nonnegative cents totaling `total_cents`.
Expense `date` defaults to today; category is food/stay/transport/activities/other.
These validations and calculations reuse the REST ledger and its input models.

Migration `0003_trips_agent_receipts.sql` adds a service-only receipt table keyed
by signed-in user and idempotency key, plus an atomic ledger CAS/receipt RPC.
Keys cover all write kinds and trips for that user. Replaying an identical
payload returns its original saved result, even if a later REST edit/deletion
changes that ledger item. Reusing a key for different details errors; use a new
key for a new operation. Default dates and generated IDs are excluded from the
request identity, as is `dry_run`. Receipts persist until the local account is
deleted. Concurrent retries serialize on the key; the ledger update and receipt
commit together. A revision conflict rereads and reapplies once; a second
conflict asks the agent to read/review the trip before retrying.

DCR requests omitting scope receive all registered provider scopes. Existing
Floor Planner grants do **not** gain Trips permissions automatically. Reconnect
and consent to the new scopes: a missing write permission says, for example,
“Reconnect to grant trips:edit.” The unrelated `/beli/mcp`, `/resy/mcp`,
`/partiful/mcp`, and `/espn/mcp` endpoints remain unchanged.

## Local real OAuth exercise

Use Python 3.12/3.13, Node 22, Docker and psql. Start the isolated stack;
setup applies all migration families, including Trips and cc_mcp:

```bash
scripts/dice-dev.sh setup
scripts/commons-connector-local.sh setup
scripts/commons-connector-local.sh serve
```

In another terminal:

```bash
scripts/commons-connector-local.sh test
# Optional human browser consent instead of unattended approval:
scripts/commons-connector-local.sh test --interactive
```

The checked-in `supabase/config.toml` enables the local OAuth server, disables
upstream dynamic registration, and sets Site URL `http://localhost:8080` with
`/oauth/consent` as its authorization page. The Bash 3.2 helper registers a
confidential local app with callback `http://127.0.0.1:8000/auth/callback` through
the local Auth admin API. It creates proxy signing/encryption keys and writes
only the local MCP settings to ignored `.dice-dev/commons-mcp.json` (mode 0600).
The service key is read from the exact loopback stack at runtime. `serve` starts
the shared API on loopback with dotenv loading and scheduled jobs disabled and
an explicitly scrubbed environment. No production configuration is used.
After resetting the stack, remove that local JSON file and run the helper's
`setup` again. Keep it stable across ordinary API restarts.

The test uses the MCP SDK's real OAuth provider for DCR, authorization code,
PKCE and Streamable HTTP with an ephemeral loopback callback and in-memory
tokens. By default it creates a uniquely named synthetic local user through
Auth admin, signs in by email/password, approves the proxy's CSRF-protected
consent form, then calls the same authorization-details and approve-consent
APIs as `frontend/src/auth/OAuthConsent.jsx`, authenticated with that user's
session. Every redirect is checked for HTTP loopback before following it.
The pinned SDK replaces requested scopes during discovery, so this exercise
selects its explicit scopes immediately before the normal authorization flow.
It also obtains a separate `trips:read` grant and verifies that a fresh committed
expense is denied without `trips:edit`, leaving the ledger unchanged.

The script creates a synthetic trip with guests, calls all five new tools
(both overview forms), previews and commits both write types, replays both keys,
and asserts previews/replays did not advance revisions. Synthetic users and
trips remain in the loopback sandbox for inspection. Tokens and keys are never
printed or committed. For interactive mode, also run the normal local frontend
on port 8080 (for example `scripts/start-local-dice-frontend.sh`) and sign in
with a synthetic sandbox account. The script can also run directly with
`backend/.venv/bin/python scripts/commons-connector-e2e.py --interactive`, using
`LOCAL_SUPABASE_SERVICE_ROLE_KEY` from the local stack. Non-loopback endpoints
are refused before loading that key. See the handoff status for PASS evidence.

Any agent supporting remote MCP + OAuth and Streamable HTTP can connect.
“Grokbot” and “Dots” remain unidentified clients; compatibility with their
specific connection requirements has not been verified.
