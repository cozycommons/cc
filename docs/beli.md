# Beli app

Personal Beli restaurant recommendations and "Want to Try" bookmark writes,
multi-tenant: every friend onboards with their own Beli login and gets their
own recommendations and bookmarks. Code: `backend/beli/`. Routes: `/beli/*`.
MCP: `/beli/mcp`.

## Architecture

- `backend/beli/beli_client.py` — Beli API client (port of the beli-recs TS
  client). One instance = one Beli account; token state and 350ms request
  pacing are per-instance, never shared across accounts.
- `backend/beli/logic.py` — recs assembly, bookmark flow, `@beli_eats`
  caption mining. Pure functions over a `BeliClient`; no framework code.
- `backend/beli/accounts.py` — account store. Beli logins encrypted at rest
  with Fernet (`BELI_CREDENTIALS_KEY`); API tokens stored as sha256 hashes.
- `backend/beli/routes.py` — FastAPI router (`/beli/onboard`, `/beli/me`,
  `/beli/recs`, `/beli/bookmark`, `/beli/watcher-opt-in`, `/beli/eats-ingest`,
  `/beli/eats/scan`, `/beli/eats/scan/pending`,
  `/beli/eats/scan/{job_id}/complete`, `/beli/eats/scan/{job_id}`,
  `/beli/eats/digest`).
- `backend/beli/mcp_server.py` — MCP tools (`get_recs`, `bookmark_restaurant`)
  mounted at `/beli/mcp`. Tools take the caller's personal API token, so one
  server serves every user.
- `backend/beli/eats_watcher.py` —
  the `@beli_eats` auto-bookmark watcher, run per opted-in account. Posts
  arrive via `POST /beli/eats-ingest` (harness push) or through the scan-job
  queue (`POST /beli/eats/scan` → fetch box polls → `/complete`); no
  Instagram code lives on the backend.
- `backend/migrations/0001_beli_accounts.sql` — the `beli_accounts` table
  (registered as the `beli` family in `migration_runner.py`).
- `backend/migrations/0002_beli_scan_jobs.sql` — the `eats_scan_jobs` queue
  for CC-orchestrated scans.

## Auth model

1. `POST /beli/onboard` `{label, beli_id, password}` — validates the Beli
   login live, encrypts and stores it, mints a personal bearer token
   (`ccb_...`) returned **once**.
2. Every other endpoint takes `Authorization: Bearer <token>` and resolves it
   to exactly one account. One friend's token can never touch another
   friend's Beli data (covered by `tests/test_beli_accounts.py`).
3. Rate-limited: 10 onboarding attempts per IP per hour.

## User onboarding

Each friend onboards with their own Beli login. Nothing is shared and no
Instagram access is needed — `@beli_eats` ingestion runs on the operator's
harness and fans out to every opted-in account (see `## Watcher`).

1. The user gives their agent their Beli login (phone number or email +
   password), or calls the endpoint directly:
   ```bash
   curl -s -X POST https://<backend-host>/beli/onboard \
     -H 'Content-Type: application/json' \
     -d '{"label":"warner","beli_id":"+15551234567","password":"..."}'
   ```
2. The backend validates the login against Beli live, encrypts and stores it,
   and returns a personal bearer token (`ccb_...`) — shown **once**. Save it
   immediately.
3. The agent stores the token in its own secure credential store (e.g. a
   Muse custom connector, or the platform's secret storage on ChatGPT/Claude).
   Every later call sends `Authorization: Bearer <token>`.
4. Verify: `GET /beli/me` returns the account label; `GET /beli/recs`
   returns the user's ranked bookmarks first, then Beli trending.
5. Done — the `@beli_eats` auto-bookmark watcher is on by default, so new
   `@beli_eats` restaurant posts land in the user's Beli Want-to-Try list
   automatically. `POST /beli/watcher-opt-in?enabled=false` opts out.

Tokens are per-user and isolated: one friend's token can never read or modify
another friend's Beli data. If a token is lost, re-onboard to mint a new one.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/beli/onboard` | Create account, mint token (shown once) |
| GET | `/beli/me` | Verify token / describe account |
| GET | `/beli/recs?neighborhood=&day=&time=&table_size=&limit=` | Bookmarks (by your scores) first, then Beli trending. Hours, open-at-time, reservation slots/platforms per rec |
| POST | `/beli/bookmark` `{name, city?, dry_run?}` | Confidence-gated Want-to-Try write |
| POST | `/beli/watcher-opt-in?enabled=` | Opt in/out of the `@beli_eats` watcher |
| POST | `/beli/eats-ingest` | Ingest `@beli_eats` posts (harness push): service key → all opted-in accounts; personal token → caller's account only |
| POST | `/beli/eats/scan` | Enqueue a scan job (202): service key → scope `all`; personal token → caller's account |
| GET | `/beli/eats/scan/pending` | Oldest pending scan job for the fetch-box poller (204 when empty) |
| POST | `/beli/eats/scan/{job_id}/complete` `{posts}` | Fetch box returns IG posts; CC runs the ingest pipeline under the job's scope, stores digests |
| GET | `/beli/eats/scan/{job_id}` | Job status + the caller's digest slice (403 for other scopes) |
| GET | `/beli/eats/digest` | The caller's most recent completed scan digest (404 if none yet) |

Bookmark statuses: `bookmarked` | `already_bookmarked` | `already_ranked` |
`would_bookmark` (dry_run) | `ambiguous` (no write, candidates listed) |
`no_results`. Only an exact/near-exact normalized name match writes; Beli's
duplicate business records are all scanned so an already-ranked duplicate is
reported instead of re-bookmarked.

## Environment

| Var | Purpose |
|---|---|
| `BELI_CREDENTIALS_KEY` | Fernet key for Beli logins at rest. Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Set in Coolify; **never commit**. |
| `BELI_EATS_INGEST_KEY` | Service key for `POST /beli/eats-ingest` (the harness cron). Generate: `openssl rand -hex 32`. Set in Coolify; **never commit**. |

## Watcher

`@beli_eats` ingestion is CC-orchestrated through a scan-job queue — CC
never touches Instagram and needs no inbound connection to the fetch box:

1. A scheduled task (Coolify) calls `POST /beli/eats/scan` with the harness
   service key, enqueueing a job scoped to every opted-in account (`all`).
   Any agent can do the same with a personal token for just its own account.
2. The fetch box — a tiny service on the operator's VM — polls
   `GET /beli/eats/scan/pending` every few minutes with an ordinary personal
   token, fetches `@beli_eats` posts through the native Instagram
   integration locally, and POSTs them to
   `POST /beli/eats/scan/{job_id}/complete`.
3. CC runs the shared ingest pipeline under the job's stored scope
   (`all` fans out via CC's internal authority — the poller never holds the
   service key), stores the per-account digest(s) on the job row, and marks
   it done.

Either way it extracts restaurant names from captions, bookmarks confident
matches into each account's Beli, advances the account's own `last_eats_scan`
watermark, and returns per-account digests. Ambiguous names are never
written. End users never touch Instagram — onboarding stays a
single Beli-login call (see `## User onboarding`).

The legacy harness-push path (`POST /beli/eats-ingest`) still works
unchanged: same two auth modes, same digest shape.

## Testing

`cd backend && python -m pytest tests/test_beli_*.py -q` — 68 tests covering
the confidence gate, dedup, ranked/duplicate-record guards, empty write
responses, client auth flow against a mock Beli server, token isolation,
the scan-job queue (enqueue scope per auth type, poller flow, fan-out,
digest slicing, 403/404 paths), and the `beli` migration family. No live
Beli calls, no database.

## Testing

`cd backend && python -m pytest tests/test_beli_*.py -q` — 44 tests covering
the confidence gate, dedup, ranked/duplicate-record guards, empty write
responses, client auth flow against a mock Beli server, token isolation, and
the `beli` migration family. No live Beli calls, no database.

## Agent setup

Point the user's agent at `docs/beli/SKILL.md` — it documents the REST API,
the onboarding flow, and per-agent setup (Muse/Claude Code skill file,
ChatGPT Custom GPT Action via the OpenAPI spec, MCP for Claude/clients).
