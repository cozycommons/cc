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
  `/beli/recs`, `/beli/bookmark`, `/beli/watcher-opt-in`, `/beli/eats-ingest`).
- `backend/beli/mcp_server.py` — MCP tools (`get_recs`, `bookmark_restaurant`)
  mounted at `/beli/mcp`. Tools take the caller's personal API token, so one
  server serves every user.
- `backend/beli/eats_watcher.py` —
  the `@beli_eats` auto-bookmark watcher, run per opted-in account. Posts
  arrive via `POST /beli/eats-ingest` from the operator's harness (native
  Instagram integration); no Instagram code lives on the backend.
- `backend/migrations/0001_beli_accounts.sql` — the `beli_accounts` table
  (registered as the `beli` family in `migration_runner.py`).

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
| POST | `/beli/eats-ingest` | Ingest `@beli_eats` posts: service key → all opted-in accounts; personal token → caller's account only |

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

`@beli_eats` ingestion runs on the operator's harness, not on the backend:
a daily scheduled job pulls recent posts through the native Instagram
integration and POSTs them to `POST /beli/eats-ingest`. The endpoint accepts
two auth modes: the harness service key (runs the pipeline for every account
with `watcher_opt_in=true`) or a personal `ccb_...` API token (runs it for the
caller's account only — this is how a user's own scheduled job triggers
ingestion without holding the shared service key). Either way it extracts
restaurant names from captions, bookmarks confident matches into that
account's Beli, advances the account's own `last_eats_scan` watermark, and
returns per-account digests. Ambiguous names are never written. End users never touch Instagram — onboarding stays a
single Beli-login call (see `## User onboarding`).

## Testing

`cd backend && python -m pytest tests/test_beli_*.py -q` — 44 tests covering
the confidence gate, dedup, ranked/duplicate-record guards, empty write
responses, client auth flow against a mock Beli server, token isolation, and
the `beli` migration family. No live Beli calls, no database.

## Agent setup

Point the user's agent at `docs/beli/SKILL.md` — it documents the REST API,
the onboarding flow, and per-agent setup (Muse/Claude Code skill file,
ChatGPT Custom GPT Action via the OpenAPI spec, MCP for Claude/clients).
