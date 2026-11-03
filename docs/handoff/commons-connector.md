# Cozy Commons universal agent connector

## Status

- M1: PR opened for review from `commons-connector-m1`; implementation and source validation complete. External auth/money review and the blocked real OAuth exercise remain for the orchestrator; do not merge yet.
- M2: not started.
- M3: not started.
- Local OAuth e2e blocked: `scripts/dice-dev.sh setup` fails with `Missing required command: docker`. No live Supabase, DCR, PKCE, consent or Streamable HTTP e2e success is claimed. Reusable exercise: `scripts/commons-connector-e2e.py`.

### Validation evidence

- Backend: `python -m pytest tests -v` — 1707 passed, 145 skipped. Database-backed tests (including receipt concurrency/grants) skipped because no isolated database is available.
- New provider tests: 31 passed, including the MCP SDK over in-process Streamable HTTP with a proxy-issued token, synthetic storage and a test upstream verifier. Covered all five tools, overview both forms, both previews/commits and both idempotent replays. This bypasses DCR/browser OAuth and does not replace the required real OAuth run.
- Frontend: Node 22, `npm test -- --run` — 96 files, 754 tests passed. `npm run build` passed with loopback URLs and a nonfunctional local placeholder publishable key. No frontend source changes.
- Migration SQL parsed with pglast; Commons historical migration contract and `git diff --check` passed. Historical migrations were not changed.
- `scripts/dice-dev.sh setup`: `Missing required command: docker`. `scripts/dice-dev.sh local`: local Supabase is not running. No production operations or live connector smoke test were attempted.
- Reusable OAuth exercise script help/import/compile checked; real OAuth consent and live ledger persistence remain unverified locally.

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
