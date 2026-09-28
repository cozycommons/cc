# Partiful app

Read-only Partiful event access, multi-tenant: every friend onboards with
their own phone number (Firebase SMS OTP) and reads their own hosted, RSVP'd,
and invited events. Code: `backend/partiful/`. Routes: `/partiful/*`.
MCP: `/partiful/mcp`.

Partiful has no public API; this integration uses the reverse-engineered
Firebase Cloud Functions (`POST https://api.partiful.com/<functionName>`),
documented in `backend/partiful/partiful_client.py`. If Partiful changes its
API, the client is the only file that needs updating.

## Architecture

- `backend/partiful/partiful_client.py` — Partiful API client. One instance =
  one Partiful account; a short-lived JWT is minted per instance from the
  stored Firebase refresh token (rotated tokens persist back to the account
  row), with one refresh-and-retry on 401/403. 250ms request pacing.
- `backend/partiful/logic.py` — event assembly across scopes
  (`all | hosted | rsvps | invited`), date-range filtering, dedupe. Pure
  functions over a `PartifulClient`; no framework code.
- `backend/partiful/accounts.py` — account store. Firebase refresh tokens
  encrypted at rest with Fernet (`PARTIFUL_CREDENTIALS_KEY`); API tokens
  stored as sha256 hashes.
- `backend/partiful/routes.py` — FastAPI router (`/partiful/onboard/start`,
  `/partiful/onboard/verify`, `/partiful/me`, `/partiful/events`,
  `/partiful/events/{event_id}`).
- `backend/partiful/mcp_server.py` — MCP tools (`list_events`, `get_event`)
  mounted at `/partiful/mcp`. Tools take the caller's personal API token, so
  one server serves every user.
- `backend/migrations/0003_beli_partiful_accounts.sql` — the
  `partiful_accounts` table (registered in the shared app-schema "beli"
  family in `migration_runner.py`; contract version bumped to 3).

## Auth model

1. `POST /partiful/onboard/start` `{phone}` — sends the SMS code. The user
   must read the code off their own phone.
2. `POST /partiful/onboard/verify` `{phone, code, label?}` — verifies the
   code against Partiful live, encrypts and stores the Firebase refresh
   token, and returns a personal Bearer token (`ccp_...`) — shown **once**.
3. Every other endpoint takes `Authorization: Bearer <token>` and resolves it
   to exactly one account. One friend's token can never touch another
   friend's Partiful data (covered by `tests/test_partiful_accounts.py`).
4. Rate-limited: 10 onboarding attempts per IP per hour.

## User onboarding

Each friend onboards with their own phone number:

```bash
curl -s -X POST https://<backend-host>/partiful/onboard/start \
  -H 'Content-Type: application/json' \
  -d '{"phone":"8185551234"}'
# -> {"status":"code_sent","phone":"+18185551234"}; read the SMS code...

curl -s -X POST https://<backend-host>/partiful/onboard/verify \
  -H 'Content-Type: application/json' \
  -d '{"phone":"8185551234","code":"123456","label":"warner"}'
# -> {"id":"...","label":"warner","token":"ccp_..."} — save the token now
```

Then read events (e.g. this past weekend):

```bash
curl -s 'https://<backend-host>/partiful/events?scope=all&start=2026-09-26&end=2026-09-27' \
  -H "Authorization: Bearer <token>"
```

## Ops

- `PARTIFUL_CREDENTIALS_KEY` must be set (Fernet key; generate like the Beli
  one in `.env.example`). Without it, onboarding fails closed with a clear
  error; already-stored tokens become undecryptable if the key changes.
- Read-only by design: there are no write endpoints or MCP tools. Adding
  writes (RSVP, invites) would need new Cloud Function mappings plus the
  approval gate — out of scope for v1.
