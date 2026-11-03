# Cozy Commons universal agent connector

## Status

- M1: merged in #197 (Commons discovery + Trips on `/mcp`).
- M2: merged in #198 (`/connect` page, `docs/mcp/SKILL.md`).
- M3a: merged in #199 (connector foundation: commons scopes, per-user
  enablement, filtered tool list, account-link contract, generic safety test).
- M3b: merged in #200 (Beli on `/mcp`).
- M3c (this PR, `commons-connector-m3c-resy`): Resy on `/mcp`, rebased on main
  after #200.
  Opened non-draft; the orchestrator runs the external review and merges.
- M3d–M3e: not started. Plan below; one PR each, in order.
- Loopback only. Local OAuth client credentials and signing/encryption keys live
  only in ignored `.dice-dev/commons-mcp.json` (0600). No production connection.

### M3a decisions

- **Scopes.** `commons:read` and `commons:edit` replace `trips:*` and
  `floor-plans:*`. The approval page requests both by default. Tools declare
  `signin` (commons tools only), `read` or `edit`. New projects never change the
  scope set.
- **Pre-commons tokens.** Honored, not rejected: the proxy maps each old scope to
  the matching commons scope and records the old per-project grant, and the
  middleware keeps such a token inside Trips/Floor Planner. Calls to any later
  project return "Reconnect your agent once…". Refresh keeps old scopes; FastMCP
  caps each refresh family at 30 days after the original approval (Supabase sends
  no refresh lifetime), so all pre-commons connections end within 30 days of
  their approval. No scope widening: a `trips:read`-only token still cannot edit
  or reach Floor Planner. Old DCR clients may request commons scopes on
  reconnect, and authorization requests naming old scopes are granted the
  commons equivalents (the approval page shows those).
- **Who reconnects, and when.** Nobody at deploy. Existing connections keep their
  Trips/Floor Planner tools until their refresh family expires (≤30 days from
  approval); then the client re-runs OAuth and gets commons scopes. Users who
  want Beli/Resy/Partiful/ESPN on `/mcp` before that reconnect once. After that
  no future project needs a reconnect.
- **Enablement.** `cc_mcp_project_settings` (`0002`, service role only, RLS,
  readiness-attested) stores explicit choices. No row: enabled when the project's
  status reports `in_use` (has trips; owns or accepted a plan), so current users
  lose nothing. `enable_project` / `disable_project` are sign-in-level tools.
- **Filtering and enforcement.** `ProjectAccessMiddleware` filters `tools/list`
  and re-checks every `tools/call` (sign-in → scope → enabled → linked). Verified
  with `stateless_http=True` in unit, SDK Streamable HTTP and real OAuth runs.
  Startup fails if a provider's declared tools differ from what it registers.
- **list_changed.** Sent on the enabling call's own response stream (stateless
  HTTP has no standalone stream). The MCP Python SDK receives it; other clients
  may only refetch on reconnect, so both tools tell the agent to refresh or
  reconnect if the tools do not appear.
- **Account links.** `AccountLink(instructions, linked, tool, url)` on the
  provider. Links live in the project's own tables keyed by Commons user ID; the
  middleware returns the link step for every project tool except the link tool.

### M3a validation evidence

- Sol review fixes: a pre-commons edit now needs that project's own read and
  edit grants (another project's translated scope can't stand in for it);
  tools/list hides tools the token can't call; unregistered or mounted tools
  are refused at startup and at call time. Regression tests in
  `tests/test_cc_mcp_tool_safety.py` fail without the fix.

- Backend, all DB/integration opt-ins (isolated `dummi_regression_501_199` +
  real PostgREST, loopback Floor Planner stack, dedicated Trips stack):
  **1903 passed, 0 skipped**. Plain `python -m pytest tests -q`: 1756 passed,
  147 skipped (the opt-in DB cases above).
- `tests/test_cc_mcp_tool_safety.py`: 42 cases over all 11 registered tools.
  Mutation check: removing the Trips membership check fails it.
- Migration `0002` applied cleanly as an upgrade on the running loopback stack
  (cc_mcp 1 → 2) and from scratch; `cc_mcp_release_readiness()` true; browser
  roles denied; revoked service grants and browser grants fail readiness.
- Frontend: 98 files, 770 tests passed; production build passed (Node 24.22.2).
- `scripts/check-cc-mcp-migration-contract.sh` now also requires RLS + browser
  revokes on every connector table and a self-attesting latest migration.
- Real OAuth (`scripts/commons-connector-local.sh test`, unattended consent):

```text
PASS synthetic local email/password sign-in
PASS Supabase OAuth authorization consent with user session
PASS list_projects
PASS whoami
PASS tools/list for a new user shows only commons tools
PASS list_projects after joining a trip
PASS default: a user who has trips gets Trips tools without enabling
PASS enable_project floor-planner
PASS notifications/tools/list_changed delivered on the stateless response stream
PASS tools/list after enable_project includes Floor Planner
PASS enabled project tool callable
PASS disable_project floor-planner
PASS tools/list after disable_project hides Floor Planner
PASS disabled project call refused with the fix
PASS get_trip_overview list
PASS get_trip_overview details
PASS add_expense dry_run
PASS get_trip_overview
PASS add_expense commit
PASS add_expense idempotent replay
PASS record_repayment dry_run
PASS get_trip_overview
PASS record_repayment commit
PASS record_repayment idempotent replay
PASS get_trip_overview
PASS real OAuth DCR + PKCE and every Trips tool, previews and replay assertions
PASS disable_project trips
PASS disabled Trips call refused although the user has trips
PASS enable_project trips
PASS Trips usable again after enable_project
PASS Supabase OAuth authorization consent with user session
PASS read-only token denied on add_expense
PASS read-only token denied on record_repayment
PASS read-only token reads Trips; writes refused; ledger unchanged
PASS pre-commons trips:* token still reads and previews Trips until it expires
PASS pre-commons token refused outside its old project with a reconnect step
```

### M3b decisions

- **Link.** Migration `0017_beli_account_owner.sql` (beli family, contract 17):
  `beli_accounts.owner_user_id` (`on delete set null`) with a partial unique
  index, `beli_agent_receipts`, and `beli_link_account(account, user)`, which in
  one transaction refuses another owner and moves the caller's earlier link.
  All service-role only; the Beli contract now also checks each service grant on
  its own (a privilege list in `has_table_privilege` means "any of").
  `link_beli_account(api_token)` (edit) reuses the legacy constant-time token
  lookup, never stores or returns the token, and allows 10 attempts per user
  per hour. No dry_run on the link: it changes only our own link row, is
  idempotent and is reversed by linking again. Beli has no web onboarding page,
  so there is no onboarding-time link; the link step points at `/beli/onboard`.
- **Tools (3).** `get_restaurant_recs` (read; `get_recs`), `save_restaurant`
  (edit; `bookmark_name`, dry_run default true, required idempotency_key) and
  the link tool. `day` is a date or lowercase weekday, `time` 24-hour `HH:MM`.
  Commits reserve the key before writing to Beli, record the result for replay,
  refuse a reused key with new details, and release the key when nothing was
  written. Review fix: the key is released only if no write request was sent; an unsettled key never writes again and is marked done once Beli's bookmarks show the place (else a same-key retry error), whatever its age.
- **Default.** Beli is on by default once linked (`in_use`). Existing accounts,
  their `ccb_` tokens, `/beli/*`, `/beli/mcp` and watcher subscriptions are
  unchanged; the `beli` catalog entry is gone from `list_projects`.
- **Local exercise.** `serve` routes the Beli client to the e2e's fake loopback
  Beli API on port 8766 with a per-process credentials key; nothing reaches Beli.

### M3b validation evidence

- Backend, all DB/integration opt-ins (fresh bootstrapped
  `dummi_regression_501_1703` + real PostgREST, loopback Floor Planner stack,
  dedicated Trips stack, analytics opt-in): **1976 passed, 0 skipped**. Plain
  `python -m pytest tests -q`: 1804 passed, 172 skipped.
- New: `tests/test_beli_agent_tools.py` (24), `tests/test_beli_owner_database.py`
  (25, real Postgres: link outcomes, unique owner, user deletion, receipts,
  browser denial, contract tampering, upgrade from the pre-0017 release with an
  existing account left unlinked and unchanged). Safety test: 66 cases over 14
  tools. Mutation check: accepting another owner's account fails both suites.
- Frontend: 98 files, 770 tests; production build passed.
- 0017 applied to the shared loopback stack for the e2e, then rolled back
  (ledger back at 16) so other worktrees on main are not blocked.
- Real OAuth e2e, Beli lines (all 56 PASS lines in the run, the M3a lines unchanged):

```text
PASS enable_project beli
PASS list_projects/enable_project show Beli unlinked with the link step
PASS unlinked get_restaurant_recs refused with the link step
PASS unlinked save_restaurant refused with the link step
PASS synthetic Beli onboarding through /beli/onboard (fake loopback Beli API)
PASS link_beli_account refused for another user's account
PASS link_beli_account refused for a wrong token
PASS link_beli_account
PASS linked account keeps its legacy ccb_ token on /beli
PASS list_projects shows Beli linked with the next step
PASS get_restaurant_recs
PASS save_restaurant dry_run
PASS save_restaurant commit
PASS save_restaurant idempotent replay
PASS save_restaurant key reuse with new details refused
PASS every Beli tool over real OAuth: link, recs, preview, commit, replay; one Beli write
PASS read-only token denied on save_restaurant
PASS read-only token reads Beli recs; saves refused; no Beli write
```

- Follow-up (not changed here): Trips readiness (`trips` 0002/0003) checks
  service grants with privilege lists, so it passes when any one is still held.

### M3c decisions

- **Tools (4 + link).** `find_resy_tables` (read; search or one venue, slots with
  listed fees in cents, optional `time` window), `list_resy_reservations` (read;
  no Resy tokens returned), `book_resy_table` and `cancel_resy_reservation`
  (edit; dry_run default true, required idempotency_key), and
  `link_resy_account`. Payment methods are not a tool: the booking preview lists
  the masked cards and `payment_method_id` must be one of them.
- **Link.** Migration `0018_beli_resy_account_owner.sql` (beli family, contract
  18) copies 0017: `resy_accounts.owner_user_id`, partial unique index,
  `resy_link_account`, 10 attempts per user per hour, no onboarding-time link (no
  Resy web onboarding page). `/resy/*`, `/resy/mcp` and `ccr_` tokens unchanged.
- **Fees and confirmation.** Previews return `terms` (deposit, cancellation fee,
  fee deadline, policy lines, masked card; `null` when Resy states nothing) and a
  `summary` sentence. A commit must pass the preview's `terms_id` (16-hex hash of
  the terms); the commit re-reads the terms and sends nothing if they differ,
  returning the new summary and `terms_id`. For a cancel, the fee deadline
  passing changes `fee_applies` and therefore the terms.
- **At most once.** `resy_agent_receipts` row (payload = request fingerprint,
  target = confirmed terms) is written immediately before the one Resy POST and
  is never deleted: service_role has no DELETE (0018 revokes the Supabase
  default grant) and the contract fails if it gains one. Lost answers keep the
  key; a same-key retry only reads Resy's reservations (booking: venue/date/
  time/party match; cancel: reservation gone) and records the outcome, else asks
  for a same-key retry later. No message suggests a new key for a retry.
- **Review fixes.** A cancel within 60s (`CANCEL_MARGIN_S`) of the fee deadline counts the fee, so a "costs nothing" preview gets new terms instead of a send; a booking receipt stores the ids the user already held at that slot (`target.held`) and settlement never matches them.
- **Cancel scope.** Only reservation ids in the linked account's own Resy list;
  not-cancellable-online and past reservations are refused.
- **Local exercise.** `serve` points `resy_client.API_BASE` at the e2e's fake
  Resy on 8767 (synthetic API key, no pacing); nothing reaches Resy.

### M3c validation evidence

- Backend, all DB/integration opt-ins (fresh bootstrapped
  `dummi_regression_501_200` + real PostgREST, loopback Floor Planner stack,
  dedicated Trips stack, analytics opt-in, rebased on main 846e122): **2064
  passed, 0 skipped**.
- New: `tests/test_resy_agent_tools.py` (27), `tests/test_resy_owner_database.py`
  (26, real Postgres: link outcomes, unique owner, user deletion, receipts not
  deletable and need a target, browser denial, contract tampering including a
  DELETE grant, upgrade from main's 0017 release (846e122, #200) with an
  existing account left unlinked). Safety test: 97 cases over 19 tools (30 Resy). Mutation checks: an
  owner-ignoring account lookup fails 5 tests; a cancel that ignores the id
  fails 1.
- Frontend: 98 files, 770 tests; production build and lint passed.
- 0017 and 0018 applied to the shared loopback stack for the e2e, then rolled
  back (ledger at 16, as before this PR's checks; the pre-0017 contract passes).
- Real OAuth e2e: 84 PASS lines, none failed; the Resy lines:

```text
PASS enable_project resy
PASS list_projects/enable_project show Resy unlinked with the link step
PASS unlinked find_resy_tables refused with the link step
PASS unlinked book_resy_table refused with the link step
PASS synthetic Resy onboarding through /resy/onboard (fake loopback Resy API)
PASS link_resy_account refused for another user's account
PASS link_resy_account refused for a wrong token
PASS link_resy_account
PASS linked account keeps its legacy ccr_ token on /resy
PASS find_resy_tables
PASS book_resy_table dry_run
PASS booking preview shows deposit, cancellation fee, policy and masked card; nothing sent
PASS book_resy_table commit without the previewed terms_id refused
PASS book_resy_table unconfirmed POST keeps its key and asks for a same-key retry
PASS book_resy_table same-key retry settles from Resy reservations
PASS book_resy_table idempotent replay
PASS book_resy_table key reuse with new details refused
PASS uncertain booking POST settled once; no duplicate reservation
PASS list_resy_reservations
PASS cancel_resy_reservation dry_run
PASS cancel_resy_reservation commit
PASS cancel_resy_reservation idempotent replay
PASS cancel_resy_reservation refused for another user's reservation
PASS every Resy tool over real OAuth: link, find, list, preview, book, cancel, replay; one booking and one cancellation sent
PASS read-only token denied on book_resy_table
PASS read-only token denied on cancel_resy_reservation
PASS read-only token finds Resy tables; bookings and cancellations refused; nothing sent
```

## M3 plan: one PR per project

Today none of the four account tables (`beli_accounts`, `resy_accounts`,
`partiful_accounts`, `espn_accounts`; beli migrations 0001/0003/0004/0006) has a
Commons user column. Each row is owned only by whoever holds its personal token
(`ccb_`/`ccr_`/…, sha256-hashed, minted once by `POST /<project>/onboard`), and
the legacy MCP servers resolve that token on every call. `beli_accounts` doubles
as the ig_logger platform identity. ESPN alone has Commons links, but for
something else: `espn_team_claims` (beli 0010) ties a Commons user to a fantasy
team per season. It does not cover credentials.

Shared approach for every project (each a small, repeatable change):

- **Migration** (beli family, next free number, never editing old files): add
  `owner_user_id uuid references auth.users(id) on delete set null` and a partial
  unique index `(owner_user_id) where owner_user_id is not null` to that project's
  account table, extend the beli readiness/contract and CI version assertion.
- **Link step.** `link_<project>_account(api_token)` tool (level `edit`): hash
  the existing token, match it, set `owner_user_id` if empty or already the
  caller, refuse if owned by someone else ("This account is linked to another
  Commons user"). Constant-time compare, the same rate limit as onboarding, and
  the token is never stored or echoed. Also link at onboarding when the request
  carries a Commons session, so new users never paste a token. Relinking another
  account replaces the link. `AccountLink.linked` reads `owner_user_id`;
  `status.in_use` = linked.
- **Tools** resolve the account from `owner_user_id` server-side and take no
  `api_token`. Writes get `dry_run` (default true) + required `idempotency_key`
  with a durable receipt table (Trips `0003` pattern). Money is integer cents.
- **Safety fixture** in `tests/test_cc_mcp_tool_safety.py`, the provider in
  `cc_mcp/registry.py`, a `CATALOG` entry removed, and the e2e extended. The old
  `/<project>/mcp` endpoints and tokens stay untouched.

### M3b Beli

- Tools (3): `get_restaurant_recs(neighborhood, day?, time?, table_size, limit)`
  (read; today's `get_recs`), `save_restaurant(name, city?, idempotency_key,
  dry_run)` (edit; today's `bookmark_restaurant`, which already has dry_run and
  never duplicates), `link_beli_account(api_token)`.
- Migration: `owner_user_id` on `beli_accounts`; receipts optional because
  bookmarking is naturally idempotent, but record the key for replay results.
- Risks: `beli_accounts` is also the ig_logger identity, so the link must not
  change watcher subscriptions; Beli credentials are decrypted per call, so keep
  the existing Fernet path and never return credentials.

### M3c Resy

- Tools (4): `find_resy_tables(query or venue_id, date, party_size, time?)`
  (read; merges `search_restaurants` + `check_availability`),
  `list_resy_reservations(scope)` (read), `book_resy_table(venue_id, date,
  party_size, slot_token or desired_time, payment_method_id?, idempotency_key,
  dry_run)` (edit), `cancel_resy_reservation(resy_token or reservation_id,
  idempotency_key, dry_run)` (edit). Plus `link_resy_account`.
- Migration: `owner_user_id` on `resy_accounts`, plus `resy_agent_receipts`.
- Risks: highest stakes. Bookings and cancellations are real-world, with deposits
  and cancellation fees. Previews must show the masked card and fees in integer
  cents, and commits must refuse if the slot or fees changed since the preview.
  Resy has no idempotency key, so use the receipt plus a "find existing
  reservation" check before any retry after an unknown outcome.

### M3d Partiful

- Tools (1–2, read only): `get_partiful_events(event_id?)`: without an ID, list
  events; with one, details (merges `list_events` + `get_event`). Plus
  `link_partiful_account`.
- Migration: `owner_user_id` on `partiful_accounts`.
- Risks: onboarding is SMS-based and the refresh token rotates; linking must not
  disturb the stored refresh token. Guest lists are other people's personal
  data, so return only what the current tools already return.

### M3e ESPN (last)

- Rebase on main after #179, #184 and #185 land or are closed; do not change
  their logic (scoreboard schedule, roster-edit outcome classification).
- Tools (15 → 5): `get_fantasy_league(view: league|standings|team|draft|
  transactions, team_id?)` (read), `get_fantasy_trends(kind: players|teams,
  limit)` (read), `get_fantasy_activity(kind: lineup_runs|roster_edits|trades,
  status?)` (read), `propose_fantasy_change(kind: lineup|roster_edit|trade, …,
  idempotency_key)` (edit; propose = dry_run preview, persists nothing external),
  `approve_fantasy_change(kind, id, idempotency_key)` (edit; the existing
  separate approval gate). Plus `link_espn_account`.
- Migration: `owner_user_id` on `espn_accounts`; reuse `espn_team_claims` to
  default `team_id` to the caller's claimed team.
- Risks: largest surface and three open PRs in the same files; one ESPN account
  may be shared by a league, so decide whether several Commons users may link
  the same league credentials (read) while only the claimant of a team may
  approve its changes. Keep `write_safety` and the propose → approve gate.

## Brief

Build the Cozy Commons universal agent connector in cozycommons/cc.

### Goal
One connector for every Cozy Commons project. A user adds one URL (https://api.cozycommons.dev/mcp) to their agent (Claude, ChatGPT, Muse, Grok, or anything with remote MCP + OAuth), signs in with Google once, and the connector itself guides them through the rest.

Today the OAuth MCP in backend/cc_mcp (docs/mcp/README.md) is live but only serves Floor Planner (backend/main.py, create_agent_app providers=(floor_planner_tools,)). Beli, Resy, Partiful and ESPN have separate MCP servers (/beli/mcp, /resy/mcp, /partiful/mcp, /espn/mcp) that take a pasted api_token on every call. Those must keep working unchanged.

Design rule: the agent does the understanding (receipts, emails, plain language). Our tools are few, strict and safe:
- exact IDs and integer cents
- dry_run preview on every write
- an idempotency_key so retries never duplicate
- errors that name the fix ("no member 'Sammy'; did you mean Sam (id …)?")

### Milestones: one PR each, in order, chained without waiting

M1: Commons guide + Trips provider
- `commons` provider (sign-in only, no extra scope):
  - whoami
  - list_projects: each project, one line on what it does, whether its tools are on this connector, the user's setup status, and the exact next step or URL if not set up.
  - Server instructions should tell agents to call list_projects first.
- `trips` provider, scopes trips:read and trips:edit. Reuse the existing Trips service layer, membership checks and revision checks (retry once on a revision conflict, then return a clear error).
  - get_trip_overview(trip_id?): with no id, the user's trips. With an id: members (ids, names, Venmo handles), balances, and the fewest-payments settle-up with Venmo pay/request links.
  - add_expense: one or several payers in cents; split even, percent or exact. dry_run defaults to true and returns the per-person result.
  - record_repayment(trip_id, from_member_id, to_member_id, amount_cents, idempotency_key, dry_run)
- Tests: each tool, scope/auth denial, cross-trip access denial, dry_run writes nothing, idempotency.

M2: "Connect your agent" page
- Frontend page (for example /connect), linked from the account menu and the Trips page.
- Copy-URL button, short steps for Claude, ChatGPT, Muse, Grok and a generic MCP client, what the consent screen looks like, and how to disconnect.
- Add docs/mcp/SKILL.md for agents to load, and update docs/mcp/README.md.
- Follow docs/crowdset/DESIGN.md and the existing Commons header styles.

M3: Beli, Resy, Partiful, then ESPN on /mcp (one PR per project, ESPN last)
- Same tools exposed through /mcp, with the user resolved from Commons sign-in instead of a pasted token.
- Find how each project's account relates to a Commons user. Where there's no link, add a one-time link step (the signed-in user proves ownership once, through a link_account tool or the project's web onboarding), with a new migration in that project's existing convention. Never edit old migrations.
- If a user isn't linked, tools return the onboarding step, and list_projects reflects it.
- Leave the old per-project endpoints and tokens untouched. ESPN has open PRs #179, #184 and #185, so rebase on main and don't change those PRs' logic.

### Rules
- Follow AGENTS.md: loopback Supabase only, no prod data or secrets committed, batch pushes per checkpoint.
- Review: one external review per M1 and M3 PR (auth and money data). Fix the findings, then auto-merge (squash). M2 needs only the executor's own check and can auto-merge.
- Done means: backend and frontend tests and the build pass, and a local end-to-end run with a real MCP client (OAuth against the loopback stack) calls every new tool on a synthetic trip.
- After M1 deploys, smoke-test the live connector: list_projects, get_trip_overview on the real trip, add_expense with dry_run only. No real writes.
- "Grokbot" and "Dots" are unidentified agents. Target any remote MCP + OAuth client, and note in the docs if one needs something else.
