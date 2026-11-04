# Cozy Commons MCP

One connection and browser sign-in serves every registered project: Commons
discovery and enablement, Trips, Floor Planner, Beli, Resy, Partiful and ESPN. Two
stable scopes, `commons:read` and `commons:edit`, cover all of them, and each
user enables the projects whose tools their agent sees. Adding a project or tool therefore never
changes the scope set or forces existing users to reconnect. The existing Beli,
Resy, Partiful and ESPN MCP endpoints keep their separate pasted-token
authentication.

## Connect an agent

Open [Connect your agent](https://cozycommons.dev/connect) (`/connect`) for the
public URL, client setup, consent and disconnect instructions. Agents can load
[SKILL.md](SKILL.md) for discovery, safe writes and worked Trips examples.

- Claude: Settings → Connectors → Add custom connector; paste the URL. Labels
  vary by plan/version. Choose remote/web OAuth and automatic registration.
  [Official guide](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
- ChatGPT: enable developer mode where available and add a custom MCP
  connector/app with OAuth. Workspace permissions may require an administrator.
  [Official guide](https://developers.openai.com/api/docs/guides/custom-mcp-server).
- Muse and Grok: add a custom/remote MCP connector if the client supports the
  protocol below. Exact menus and compatibility are not verified.
- Generic client: Streamable HTTP + OAuth with dynamic client registration and
  PKCE. API-key-only and stdio-only clients cannot use this endpoint.

The connector's approval page names the agent and the requested scopes
(`commons:read commons:edit` by default). Sign in with Google to Cozy Commons,
then review the application and account on `/oauth/consent`. Choose Allow
connection or Deny. Call `list_projects` first, then `enable_project` for any
project that is off; preview writes and get user confirmation before committing.
To disconnect, open Connected agents on [your account](https://cozycommons.dev/account#agents)
(`/account#agents`) and choose Disconnect; that connection's access and refresh
tokens stop working on the next request. Also remove the connector in the agent.

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
own JWTs with audience bound to the `/mcp` resource and keeps the
`commons:read` and `commons:edit` scopes in those local tokens. Raw
Supabase session tokens are rejected by MCP. Tools use the shared context to
validate the current user with Supabase Auth.
Each project owns its account binding, authorization, and write validation.
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

## Scopes, enablement and the tool list

Every tool declares one access level. `signin` tools (the `commons` provider
only: `whoami`, `list_projects`, `enable_project`, `disable_project`) need a
valid connection and no scope. `read` tools need `commons:read`; `edit` tools
need `commons:edit`. Clients that omit scopes at registration get both.

`ProjectAccessMiddleware` (FastMCP 2.14 middleware, `backend/cc_mcp/server.py`)
filters `tools/list` to `commons` plus the projects enabled for the signed-in
user, and checks every `tools/call` again: missing sign-in, then scope, then
enablement, then any account link. Hiding a tool is not authorization; a call to
a disabled project's tool returns, for example, “Cozy Trips is not enabled; call
enable_project('trips').” The connector runs with `stateless_http=True`, so the
filter runs on every request and needs no session state.

`cc_mcp_project_settings` (migration `0002_cc_mcp_project_settings.sql`) stores a
user's explicit choice per project: user, project, enabled and timestamps. It is
service-role only with RLS enabled and no browser access; `/ready` attests it.
Without a stored row a project is enabled when its status callback reports
`in_use` (Trips: the user belongs to a trip; Floor Planner: the user owns or
accepted a plan), so existing users lose nothing. A status failure leaves a
default project off (fail closed) but never overrides a stored choice; a settings
lookup failure refuses the call and asks the agent to retry. Disabling hides
tools and keeps all project data.

`enable_project` and `disable_project` send `notifications/tools/list_changed`
on the response stream of that call (with its request ID). Stateless HTTP has no
standalone server stream, so this is best effort: the MCP Python SDK receives it
(see the local exercise), while some clients only refetch tools on reconnect.
Both results therefore tell the agent to refresh its tool list or reconnect if
the new tools do not appear; the setting is saved either way.

### Connections approved before commons scopes

M1 tokens carry `trips:read`, `trips:edit`, `floor-plans:read` and/or
`floor-plans:edit`. They keep working: on load the proxy maps each one to the
matching commons scope and records the old per-project grant, and the middleware
allows such a token only within those projects. A pre-commons token cannot reach
a project added later; the call says “Reconnect your agent once to grant
commons:read and commons:edit.” Refreshing keeps the old scopes, and FastMCP
caps the refresh family at 30 days after the original approval (Supabase returns
no refresh lifetime), so every pre-commons connection ends within 30 days of its
approval. Nobody has to reconnect at deploy; users reconnect when a token family
expires or when they want a newly added project. Clients registered with the old
scopes may request the commons scopes on reconnect, and an authorization request
that still names old scopes is granted the commons equivalents, which the
approval page shows.

## Adding a project

`backend/cc_mcp/registry.py` lists every provider served at `/mcp`;
`backend/main.py` passes it to `create_agent_app`. A provider is the project
contract (`ToolProvider` in `backend/cc_mcp/server.py`):

```python
provider = ToolProvider(
    "beli", register_tools,
    {"get_restaurant_recs": "read", "save_restaurant": "edit", "link_beli_account": "edit"},
    title="Beli", description="Restaurant recommendations and your Beli Want to Try list.",
    url=DOCS_URL,
    status=beli_status,  # cheap, read-only; {"in_use": bool, "next_step": "..."}
    link=AccountLink(
        "Call link_beli_account(api_token) once with your existing ccb_ token.",
        linked=linked_beli_account,  # (service_client, user) -> non-secret summary or None
        tool="link_beli_account",
    ),
)
```

Startup fails unless the provider declares exactly the tools it registers, each
project tool is `read` or `edit`, names are unique and any link tool belongs to
the provider. `tests/test_cc_mcp_tool_safety.py` enumerates every registered tool
and fails until the project has a fixture with valid arguments and either an
“another user's resource” case or a stated reason it has none. For each tool it
asserts: no token is refused; a token without the tool's scope is refused (so a
read-only token cannot call any edit tool); a disabled project's tool is hidden
and refused; a pre-commons token for another project is refused; another user's
resource is refused. None of these changes the scope set, so existing
connections keep working and see the new project in `list_projects`.

Checklist:

1. Keep it to about five well-combined tools. Merge reads that differ only by a
   filter into one tool with a parameter.
2. Declare each tool `read` or `edit`, and call `context.need_scope(READ_SCOPE)`
   or `EDIT_SCOPE` in the tool as well. Resolve the user with
   `context.signed_in_user`, then enforce the project's own ownership rules.
3. Writes take `dry_run` (default `true`) and a required `idempotency_key`, with
   a durable receipt so a retry returns the original result (see Trips).
4. Money is integer cents (or minor units with the currency named). Use exact
   IDs; never resolve names silently.
5. Errors name the fix: an exact ID suggestion, `enable_project('…')`, the link
   step or “Reconnect your agent…”.
6. Accounts that are not Commons users (Beli, Resy, Partiful, ESPN) declare an
   `AccountLink`. The link lives in the project's own tables, keyed by the
   Commons user ID; tools resolve the account from the signed-in user server-side
   and never accept a pasted token after linking. Until linked, every tool except
   the link tool returns the link instructions, and `list_projects` shows them as
   the next step.
7. Provide a cheap `status` callback whose `in_use` means “this user already uses
   the project”; it enables the project by default.
8. Add the provider to the registry, add its safety fixture, and leave the
   project's legacy endpoint unchanged.

The shared `cc_mcp` migration family has no dependency on project tables.
Run the canonical migration runner with `--family cc_mcp`, or use the shared
release runner which applies all families. `/ready` attests its service-only
OAuth and project-settings tables and grants. Keep signing/encryption keys stable
across replicas and restarts; rotating them invalidates existing connections.
Never put those keys or upstream credentials in the frontend.

## Validation and limitations

Shared auth tests cover JWT issuer/audience/client checks, scoped tokens,
pre-commons tokens and clients, refresh isolation, revocation, discovery,
enablement and the per-tool safety gates. The Floor Planner protocol test
uses real loopback Supabase state to exercise its provider through the shared
endpoint. Local browser OAuth, tool edits, refresh, and restart persistence were
verified during development. Native Codex and Claude client setup and production
OAuth configuration still need deployment validation. USDZ scans remain private
to collaborators and are not exposed by the MCP tools.

## Commons discovery and Trips

Call `list_projects` first. `whoami`, `list_projects`, `enable_project` and
`disable_project` require a current Commons sign-in and no scope. For each
connector project, `list_projects` returns whether it is enabled and why
(`your choice`, `default: you already use it` or `default: off until enabled`),
whether its account is linked (projects with an account link), its tools with
their access level, its status and the exact next step. Other public projects
are listed with their URL.
Status lookup failures do not prevent discovery. `enable_project(project_id)`
returns the project's tools and any one-time link step.

`get_trip_overview` needs `commons:read`. Omit `trip_id` to list authorized trips;
pass it to get member IDs, names, Venmo usernames, currency, revision, integer
balances and settlement payments. Trips does not currently store travel dates;
list entries therefore return `dates: null`. Settlement reuses the canonical
fewest-payment solver up to 16 nonzero balances, with its deterministic greedy
fallback above that limit. Venmo links use existing handle validation and URL
helpers, and require USD and the appropriate payer/payee handle. A missing link
is null. Links do not execute a payment.

`add_expense` and `record_repayment` need `commons:edit`, exact trip/member IDs,
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

DCR requests omitting scope receive `commons:read commons:edit`. A missing
permission says, for example, “Reconnect your agent to grant commons:edit.”
The legacy `/beli/mcp`, `/resy/mcp`, `/partiful/mcp`, and `/espn/mcp`
endpoints remain unchanged.

## Beli

Provider `backend/ig_logger/sinks/beli/agent_tools.py`, three tools:

- `get_restaurant_recs(neighborhood, day?, time?, table_size=2, limit=10)`
  (`read`): your Want to Try bookmarks first, then Beli trending, each with its
  Beli business ID, hours and reservation slots. `day` is `YYYY-MM-DD` or a
  lowercase weekday; `time` is 24-hour `HH:MM`.
- `save_restaurant(name, idempotency_key, city?, dry_run=true)` (`edit`): the
  existing confidence-gated bookmark flow (`logic.bookmark_name`). Ambiguous
  names return candidates and save nothing; saved or ranked places are reported,
  never duplicated.
- `link_beli_account(api_token)` (`edit`): links with a `ccb_` token the user
  already holds. The link step no longer asks for one: it sends the user to
  `https://cozycommons.dev/account#beli`.

Linking on the account page: `POST /account/linked-accounts/beli` with
`{login, password}` and the Commons session. The server checks the login with
Beli first; a wrong password stores nothing. An existing account with the same
login (emails compared case-insensitively, phone numbers by digits) is reused:
its stored password is refreshed and its `ccb_` token, receipts and watcher
subscription stay. Otherwise a new account is created with a token nobody sees.
Then `beli_link_account` links it, refusing an account another Commons user
owns. `GET /account/linked-accounts` returns `{beli: summary | null}`. Attempts
are limited to 10 per user per hour.

A Beli account belongs to whoever holds its `ccb_` token (minted once by
`POST /beli/onboard`; only its sha256 hash is stored). Migration
`0017_beli_account_owner.sql` adds `beli_accounts.owner_user_id` (references
`auth.users`, `on delete set null`) with a partial unique index, so a Commons
user links at most one account and an account has at most one Commons owner.
`link_beli_account` hashes the presented token, matches it in constant time and
calls `beli_link_account(account, user)`, which in one transaction refuses an
account owned by someone else ("This Beli account is linked to another Commons
user") and moves the caller's earlier link if they link a different account of
theirs. The token is never stored or returned; attempts are limited to 10 per
user per hour, like onboarding. Linking changes only `owner_user_id`: the
`ccb_` token, `/beli/*` routes, `/beli/mcp` and `@beli_eats` watcher
subscriptions are untouched, and existing accounts stay unlinked until their
owner links them. Until linked, the middleware answers every Beli tool except
the link tool with the link step, and `list_projects` shows `linked: false` with
that step. Beli is on by default (status `in_use`) once linked. There is no Beli
web onboarding page, so linking happens only through the tool.

Tools resolve the account from the signed-in user, decrypt its Beli login with
the existing Fernet key per call and never return credentials. `save_restaurant`
commits are receipted in `beli_agent_receipts` (keyed by user and key; the
fingerprint is account, name and city). A commit reserves its key before calling
Beli, so a concurrent retry cannot write twice; it records the result, which a
replay returns, and a reused key with different details is refused. Nothing is
reserved by a preview, and the reservation is released only when no write
request was sent (ambiguous, no match, or a failure before the write). A key
with no recorded result, however old, never writes again: a retry with the same
key checks Beli's bookmarks, marks the key done if the place is there, and
otherwise returns an error asking for a same-key retry later. Both tables
and the function are service-role only (RLS on, browser roles revoked); the Beli
schema contract checks the index, every service grant individually, browser
denial and the function's privileges at release time.

## Resy

Provider `backend/resy/agent_tools.py`, four tools plus the link step. Resy
bookings and cancellations are real: they can charge a deposit and a
cancellation fee to the user's saved card.

- `find_resy_tables(date, party_size=2, query? | venue_id?, location="New York",
  time?)` (`read`): pass `query` (name or cuisine, searched near `location`) or
  `venue_id`. Each slot has its `slot_token`, time, type and the listed
  `deposit_cents` / `cancellation_fee_cents`. `time` keeps slots within an hour.
  Merges the legacy `search_restaurants` and `check_availability`.
- `list_resy_reservations(scope="upcoming")` (`read`): `upcoming`, `past` or
  `all`, with the `reservation_id` that cancelling takes. Resy tokens are not
  returned.
- `book_resy_table(venue_id, date, idempotency_key, party_size=2, slot_token? |
  desired_time?, payment_method_id?, terms_id?, dry_run=true)` (`edit`).
- `cancel_resy_reservation(reservation_id, idempotency_key, terms_id?,
  dry_run=true)` (`edit`).
- `link_resy_account(api_token)` (`edit`): the one-time link step with the
  existing `ccr_` token.

Linking mirrors Beli: migration `0018_beli_resy_account_owner.sql` adds
`resy_accounts.owner_user_id` (partial unique index, `on delete set null`) and
`resy_link_account(account, user)`, which refuses another owner's account and
moves the caller's earlier link in one transaction. The token is hashed and
compared in constant time, never stored or returned, and limited to 10 attempts
per user per hour. `/resy/*`, `/resy/mcp` and `ccr_` tokens are unchanged;
existing accounts stay unlinked. Resy is on by default once linked. There is no
Resy web onboarding page, so linking happens only through the tool.

Previews. A booking preview reads the slot from Resy's availability, the slot's
booking details (`/3/details`) and the saved cards, and returns `terms`: venue,
date, time, party size, slot type and token, `deposit_cents`,
`cancellation_fee_cents`, the time after which the fee applies, the cancellation
policy lines, and the masked card (`Visa ....4242`), plus a `summary` sentence
naming each and the account's `payment_methods`. Amounts are integer cents with
the currency named; an amount Resy does not state is `null` and the summary says
so rather than showing zero. Two slots at the same `desired_time` (for example
dining room and bar) are refused with each slot's token. `payment_method_id` must
be one of the linked account's own cards. A cancellation preview reads the
caller's own reservations and returns the fee, the deadline, whether the fee
applies now and the policy. Only a reservation in the linked account's own Resy
list can be cancelled; any other id is "not in your Resy account". Reservations
Resy marks as not cancellable online are refused with "contact the restaurant".

Commits. `dry_run=false` requires the preview's `terms_id` (a short hash of the
terms). The commit re-reads the terms; if anything changed (slot gone, fee or
deposit, policy, card, or the fee deadline passing for a cancellation), nothing
is sent and the error carries the new summary and `terms_id` to confirm with the
user. Then the commit writes a receipt to `resy_agent_receipts` (user, key,
request fingerprint and the confirmed terms) immediately before the single
request to Resy, and records Resy's answer on it. Resy has no idempotency key, so
the receipt is the guard and is never released: the connector has no `DELETE`
grant on the table, and the Beli schema contract fails release if one appears.
When Resy's answer is lost (timeout, 5xx, a dropped connection), the call says
the booking "may have gone through" and asks for the same key and arguments. A
retry with that key never sends again: it reads the user's Resy reservations,
records the booking once a matching reservation (venue, date, time, party size)
appears or the cancellation once the reservation is gone, and otherwise returns
an error asking for a same-key retry later and, if nothing ever appears, for the
user to check the Resy app. No message tells the agent to use a new key for a
retry. A key with recorded details refuses different details: an unconfirmed key
asks for its original arguments; a finished one names what it already did.
Replays return the original result even after the slot is gone. Reads that fail
before the write (Resy errors, expired login) spend no key and say nothing was
booked or cancelled; a dead login asks the user to onboard again and relink.

## Partiful

Provider `backend/partiful/agent_tools.py`, read-only, one tool plus the link
step:

- `get_partiful_events(event_id? | scope?, start?, end?)` (`read`): without
  `event_id`, the legacy `list_events` (`scope` `all` (default), `hosted`,
  `rsvps` or `invited`; inclusive `YYYY-MM-DD` `start`/`end` on the event date);
  with it, the legacy `get_event`. Pass `event_id` alone. Both return exactly
  what the legacy tools return: no guest lists. An event the user's own
  Partiful session cannot see is "Event not found"; the connector never uses
  another account's session.
- `link_partiful_account(api_token)` (`edit`): the one-time link step with the
  existing `ccp_` token.

Linking mirrors Beli and Resy: migration `0019_beli_partiful_account_owner.sql`
adds `partiful_accounts.owner_user_id` (partial unique index, `on delete set
null`) and `partiful_link_account(account, user)`, which refuses another owner's
account and moves the caller's earlier link in one transaction. The token is
hashed and compared in constant time, never stored or returned, and limited to
10 attempts per user per hour. Linking changes only `owner_user_id`; the stored
Firebase refresh token and uid are untouched. `/partiful/*`, `/partiful/mcp` and
`ccp_` tokens are unchanged; existing accounts stay unlinked. Partiful is on by
default once linked. Onboarding is SMS-based and has no web page, so linking
happens only through the tool. There are no writes and so no receipts table.

Partiful may rotate the refresh token on any read, and every path (`/partiful`,
`/partiful/mcp`, `/mcp`) persists the new one. The `/partiful` routes therefore
read accounts through an uncached client (`app.state.partiful_supabase`), not
the shared 120-second read cache, which would otherwise hand them a refresh
token another path had already retired. A dead session asks the user to
onboard again and relink.

## ESPN

Provider `backend/espn/agent_tools.py`, five tools plus the link step. The
legacy `/espn/mcp` has fifteen; reads merge by a parameter and every write keeps
the existing propose -> approve gate. Approving submits for real: a roster edit
adds and drops players (a waiver target becomes a claim, bid 0), a trade sends
an offer the other manager sees, and a lineup moves players between slots.

- `get_fantasy_league(view="league", team_id?, limit=25)` (`read`): `league`
  (settings, teams and `your_team_id`), `standings`, `team` (one roster;
  `team_id` defaults to your own team), `draft` or `transactions`. Merges
  `get_league`, `get_standings`, `get_team`, `get_draft` and `get_transactions`.
- `get_fantasy_trends(kind="players", limit=10)` (`read`): `players` (ownership
  and performance from league snapshots) or `teams`. Merges
  `get_player_trends` and `get_team_trends`.
- `get_fantasy_activity(kind, proposal_id?, limit=25, scoring_period_id?)`
  (`read`): `lineup_runs`, `roster_edits` or `trades`, newest first, or one by
  id. An edit or trade with an unresolved ESPN outcome is reconciled by
  rereading ESPN, never resubmitted. Merges `get_lineup_runs`,
  `get_roster_edits` and `get_trades`.
- `propose_fantasy_change(kind, ...)` (`edit`): validates against the live league
  and stores a pending proposal; sends nothing to ESPN. `lineup` (`date` or
  `scoring_period_id`, neither = today) records a dry-run lineup run under the
  standing rule that every scheduled player starts; `roster_edit`
  (`add_player_id` and/or `drop_player_id`) and `trade`
  (`counterparty_team_id`, `give_player_ids`, `receive_player_ids`) store a
  pending row with a 30-minute expiry. Arguments of another kind are refused.
  Returns `proposal_id` and a `summary`. Merges `run_lineup(dry_run=true)`,
  `propose_roster_edit` and `propose_trade`.
- `approve_fantasy_change(kind, proposal_id, idempotency_key, dry_run=true)`
  (`edit`): `dry_run=true` shows what approving submits and sends nothing;
  `dry_run=false` submits that one proposal through `roster_edits.approve_edit`,
  `trades.approve_trade` or a live `lineup.run_lineup` for the previewed
  scoring period. A lineup preview is approvable for 30 minutes, like edits and
  trades. Merges `approve_roster_edit`, `approve_trade` and the live
  `run_lineup`.
- `link_espn_account(api_token)` (`edit`): the one-time link step with the
  existing `cce_` token.

Linking mirrors the other projects: migration
`0089_beli_espn_account_owner.sql` adds `espn_accounts.owner_user_id` (partial
unique index, `on delete set null`), `espn_link_account(account, user)` and
`espn_agent_receipts`. One Commons user links one ESPN account, and an account
has at most one Commons owner, so a league's cookies are never shared between
Commons users. The account is one manager's cookies, and every write acts on the
team those cookies own (the SWID member), as on `/espn`. Linking changes only
`owner_user_id`: cookies, lineup automation and `espn_team_claims` are untouched,
and the connector does not read or change team claims. `/espn/*`, `/espn/mcp`
and `cce_` tokens are unchanged; existing accounts stay unlinked. ESPN is on by
default once linked; linking happens only through the tool. A legacy
`DELETE /espn/account` still deletes a linked account and its proposals.

Approvals. The proposal row is ESPN's own guard: an approval claims it
atomically (pending -> executing) before anything is sent, and an unresolved
row is only reconciled. On top, a commit writes a receipt (user, key, the kind
and proposal id, and the summary) immediately before the approval and records
the outcome on it. The receipt is never released: the connector has no `DELETE`
grant on the table, and the Beli schema contract fails release if one appears.
When ESPN's answer is lost, the call says the change "may have gone through"
and asks for the same key and arguments. A retry with that key never submits
again: for an edit or trade it rereads ESPN through the existing
reconciliation, and for a lineup it replans that day read-only (a dry-run run)
and counts the change set when no move remains. Otherwise it asks for a same-key
retry later. An approval refused before it claimed its proposal (for example,
another unresolved write with the same players) records `not_sent`, so the key
replays that refusal; nothing was sent under it. A key with recorded details
refuses another proposal. Replays return the original result. Before any key is
reserved, an unknown, expired, already decided or unresolved proposal is
refused with the fix (`get_fantasy_activity` to reconcile an unresolved one).
Expired cookies ask the user to onboard again and relink.

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
It also obtains a separate `commons:read` grant and verifies that both Trips
writes are denied without `commons:edit`, leaving the ledger unchanged.

The script checks that a new user sees only commons tools, that joining a
synthetic trip enables Trips by default, and that `enable_project` /
`disable_project` change `tools/list`, deliver `notifications/tools/list_changed`
and refuse a disabled project's calls. It calls every Trips tool (both overview
forms), previews and commits both write types, replays both keys, and asserts
previews/replays did not advance revisions. Finally it signs a pre-commons
`trips:*` token with the server's key and the session's real upstream mapping,
exactly as M1 issued them, and checks it still works for Trips and is refused for
Floor Planner with the reconnect step.

For Beli, `serve` points the Beli API client at a fake synthetic Beli API that
the test runs on `127.0.0.1:8766`, and gives synthetic logins a per-process
credentials key, so nothing reaches Beli. The test checks that Beli starts off
and unlinked, that its tools return the link step, onboards two synthetic
accounts through the real `POST /beli/onboard`, links one to a second synthetic
user, and checks that linking it or a wrong token is refused. It then links its
own account, checks the `ccb_` token still works on `/beli/me`, calls
`get_restaurant_recs`, and previews, commits, replays and reuses a
`save_restaurant` key with new details, asserting exactly one Beli write. The
read-only grant reads recs and is refused on `save_restaurant`.

For Resy, `serve` likewise points the Resy client at a fake synthetic Resy API
on `127.0.0.1:8767` (synthetic API key, per-process credentials key, no request
pacing), so nothing reaches Resy. The test checks that Resy starts off and
unlinked and that its tools return the link step, onboards two synthetic accounts
through the real `POST /resy/onboard`, refuses linking the one linked to the
second user and a wrong token, links its own and checks the `ccr_` token still
works on `/resy/me`. It finds tables, previews a booking (deposit, cancellation
fee, policy and masked card in the summary), refuses a commit without
`terms_id`, then commits while the fake records the booking and answers 504: the
call reports an unconfirmed booking, and the same-key retry settles it from the
reservations list with exactly one booking request sent. It replays the key,
refuses the key with new details, lists reservations, previews, cancels and
replays the cancellation, and refuses cancelling another user's reservation id.
The read-only grant finds tables and is refused on both Resy writes.

For Partiful, `serve` points the Partiful API, Firebase sign-in and token refresh
at a fake on `127.0.0.1:8768` (per-process credentials key, no pacing), so
nothing reaches Partiful or Google. The fake rotates the refresh token on every
refresh and retires the old one. The test checks that Partiful starts off and
unlinked, onboards two synthetic phone numbers through the real
`/partiful/onboard/start` and `/verify`, refuses linking the one linked to the
second user and a wrong token, links its own without changing the stored
session, and checks the `ccp_` token on `/partiful/me`. It lists events (no
guest data), filters by scope, reads one event, is refused another user's
event, and then calls the legacy `/partiful/events`, which must still work after
the connector's rotations. The read-only grant reads events and cannot link.

For ESPN, `serve` points ESPN reads, writes and the public scoreboard at a fake
on `127.0.0.1:8769` (per-process credentials key, no pacing), so nothing reaches
ESPN. The fake serves the connector tests' synthetic league
(`backend/tests/espn_fakes.py`), one per SWID cookie, and records every write.
The test checks that ESPN starts off and unlinked, onboards two synthetic
accounts through the real `POST /espn/onboard`, refuses linking the one linked to
the second user and a wrong token, links its own without changing the stored
cookies, and checks the `cce_` token on `/espn/me`. It reads the league, your
team, standings and both trends, then proposes, previews, approves and replays a
lineup. It proposes a roster edit and approves it while the fake records the
write, answers 504 and hides it from reads: the call reports an unconfirmed
approval, a same-key retry stays open, and once the fake shows the write the
same-key retry settles it from ESPN with exactly one roster request sent. It
refuses the key for another proposal, approves a trade offer, reads activity,
is refused another user's edit on both read and approve, and checks that the
legacy `/espn/roster/edits` lists the connector's edit. The read-only grant reads
the league and is refused on proposals and approvals.
Synthetic users, trips and Beli, Resy, Partiful and ESPN accounts remain in the
loopback sandbox for inspection. Tokens and keys are never printed or committed. For interactive mode, also run the normal local frontend
on port 8080 (for example `scripts/start-local-dice-frontend.sh`) and sign in
with a synthetic sandbox account. The script can also run directly with
`backend/.venv/bin/python scripts/commons-connector-e2e.py --interactive`, using
`LOCAL_SUPABASE_SERVICE_ROLE_KEY` from the local stack. Non-loopback endpoints
are refused before loading that key. See the handoff status for PASS evidence.

Any agent supporting remote MCP + OAuth and Streamable HTTP can connect.
“Grokbot” and “Dots” remain unidentified clients; compatibility with their
specific connection requirements has not been verified.
