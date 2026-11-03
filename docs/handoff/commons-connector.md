# Cozy Commons universal agent connector

## Status

- M1: implementation and both local verification gates complete on 2026-11-03.
  The external auth/money review reported no code bugs; its database and real
  OAuth gates are now satisfied. PR #197 remains open; do not merge in this task.
- M2: not started.
- M3: not started.
- Loopback Supabase and the configured shared MCP API are left running. Generated
  OAuth client credentials and signing/encryption keys live only in ignored
  `.dice-dev/commons-mcp.json` (0600). No production connection was used.

### Validation evidence

- Full backend suite: **1854 passed, 0 skipped** with the isolated disposable
  database, real REST fixture, analytics, Floor Planner and dedicated Trips
  integration opt-ins enabled. This runs **147 database/integration cases** that
  were previously skipped or newly added: the prior **145 skipped** plus **2 new
  receipt cases**. The earlier source-only result was 1707 passed / 145 skipped.
- `tests/test_trips_migrations.py`: **19 passed, 0 skipped** (previously 17 skipped).
  Eight concurrent identical requests produce exactly one actual ledger UPDATE
  and one receipt; different users can reuse a key independently; reuse by the
  same user on another trip returns an idempotency conflict without leaking the
  earlier receipt; forced receipt-insert failure rolls back ledger data/revision.
  Real database role checks confirm 0003 receipt RLS is enabled and both browser
  roles lack table/RPC access. Live Trips and cc_mcp readiness return true.
- Fixed the existing CI release assertion to expect Trips migration 3 rather than
  2; the old assertion caused the previous backend CI failure. Verified migration
  version/readiness against loopback. Historical migrations are unchanged.
- Frontend on Node 22: **96 files, 754 tests passed**; `npm run build` passed with
  loopback URLs and a nonfunctional local publishable-key placeholder.
- cc_mcp and historical Commons migration contract scripts, Bash 3.2 parsing,
  script help/compile checks and `git diff --check` passed.
- Real OAuth via `scripts/commons-connector-local.sh test`: synthetic local
  email/password sign-in, proxy consent, Supabase user-session consent, MCP SDK
  DCR, PKCE token exchange and real Streamable HTTP. All M1 tools, both overview
  forms, both previews/commits/replays, revision assertions and a separate
  read-only grant's write denial passed. `--interactive` retains browser consent;
  the successful run used unattended consent. Local setup is documented in
  `docs/mcp/README.md`.

Full backend command after bootstrapping the disposable database and starting
CI's loopback REST adapter (the test JWT comes from its synthetic local signer):

```bash
cd backend
source .venv/bin/activate
DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/dummi_regression_501_197 \
DICE_TEST_DATABASE=1 DICE_REQUIRE_DATABASE_TESTS=1 RUN_ANALYTICS_DB_TESTS=1 \
FLOOR_PLANNER_INTEGRATION=1 TRIPS_INTEGRATION=1 \
API_URL=http://127.0.0.1:55431 DICE_TEST_REST_URL=http://127.0.0.1:55431 \
python -m pytest tests -q
```

Captured unattended OAuth PASS output:

```text
PASS synthetic local email/password sign-in
PASS Supabase OAuth authorization consent with user session
PASS list_projects
PASS whoami
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
PASS real OAuth DCR + PKCE and all M1 tools, previews and replay assertions
PASS Supabase OAuth authorization consent with user session
PASS token without trips:edit denied on write; ledger unchanged
```

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
