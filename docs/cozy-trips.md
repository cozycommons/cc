# Cozy Trips

Cozy Commons project at `/trips`, with its authenticated API under `/trips`.

## First delivery

Friends share a trip ledger: add named members, invite each friend to claim their
place using the existing Supabase login, add/edit/delete expenses, split equally
among selected people or by exact amounts, see balances and suggested repayments,
and record or undo repayments. A trip uses one currency with two decimal places.
Use the existing Wabi tokens and shared sign-in session. All members can manage
expenses; the trip creator manages member invitations. Recorded repayments do
not initiate payments.

No exchange rates, receipt OCR, payment processing, notifications, or separate
agent credential system in this increment. The UI uses native labeled controls;
the same authenticated HTTP API is documented by FastAPI OpenAPI.

## Implementation decisions

- Work locally in Ubuntu-24.04 at `~/repo/cozy-trips`, branch `feat/cozy-trips`.
- One JSON ledger per small trip in Supabase Postgres, atomically updated with a
  revision check. Concurrent edits return 409 rather than overwrite each other.
- Integer minor units for all money; deterministic remainder distribution and
  zero-sum balances. Server validates every participant and exact split.
- RLS permits members to read only their trips. Client writes are revoked;
  authenticated API commands authorize membership before using the server client.
- Invitations use one-use random secrets hashed at rest, sent in link fragments.
- Use a dedicated local Supabase project and ports; never reset the shared stack.
- Local synthetic sign-ins use real Supabase sessions and exist only in the local
  development entry point. Production continues to use shared Google sign-in.

## Run locally

Requirements: Node 22, Python 3.12, Docker, and `psql`. Use Ubuntu/WSL for all
commands. Install the repository's locked dependencies and a backend virtual
environment, then:

```bash
cd ~/repo/cozy-trips
backend/.venv/bin/python scripts/trips-dev.py setup
backend/.venv/bin/python scripts/trips-dev.py run
```

`setup` starts the dedicated `cozy-trips-local` Supabase project, applies only
the Trips migration family, and creates missing synthetic Matt/Alex/Jamie users.
It preserves existing ledger data. It never resets the Dice project. Keys are
read from CLI status into process memory, not committed or written to dotenv.
The Docker network publishes only to 127.0.0.1, and the runner verifies that.

- UI: `http://localhost:8815/trips`
- API/OpenAPI: `http://localhost:8011/docs`
- Supabase API/database: loopback ports 55321/55322
- Private phone preview: `https://desktop-r5cm15p.tail9170c8.ts.net:8451/trips`

Use the local account buttons to exercise actual Supabase sessions. Google OAuth
continues to use the existing shared client in the normal app; it is deliberately
not offered by the isolated local demo, whose OAuth provider is not configured.
The local config cannot build in production mode. The normal production build
does not contain synthetic account credentials or demo controls.

The phone preview uses Windows Tailscale Serve on the existing tailnet, port
8451, proxying the WSL frontend at port 8815. Other Serve routes were compared
before/after and preserved. The preview server must remain running. To remove
only this forwarding later, use `tailscale serve --https=8451 off` on its host.

## Agent API

Use `Authorization: Bearer <existing Supabase access token>`. All endpoints below
are relative to the backend `/trips` prefix. The UI uses these same commands.

| Endpoint | Operation |
| --- | --- |
| GET /groups | List the caller's trips |
| POST /groups | Create: UUID id, name, currency, display_name |
| GET /groups/{id} | Full trip, integer balances, suggested transfers, revision |
| POST /groups/{id}/members | Creator adds a named person; returns a one-use invite |
| POST /groups/{id}/members/{member}/invite | Creator rotates that person's invite |
| POST /groups/{id}/join | Claim an invitation with invite_token |
| POST /groups/{id}/expenses | Create an expense |
| PUT /groups/{id}/expenses/{expense} | Edit an expense |
| DELETE /groups/{id}/expenses/{expense} | Remove an expense |
| POST /groups/{id}/repayments | Record an outside repayment |
| DELETE /groups/{id}/repayments/{repayment} | Undo a repayment record |

Every mutation to an existing trip except joining includes its latest `revision`.
409 means reload and review; never blindly retry or overwrite another edit.
Expense/repayment IDs are client-generated UUIDs so a lost response can be
reconciled by re-reading the trip. Date fields use YYYY-MM-DD.

Expense input: id, revision, description, amount_minor, paid_by (member UUID),
split_mode (`equal` or `exact`), participants (member UUIDs), shares (member UUID
to nonnegative integer minor units, for exact splits), date, category, notes.
Equal splits distribute remainder pennies in displayed member order. Repayment
input: id, revision, from_member, to_member, amount_minor, date, notes.
Positive balances mean owed; negative balances mean owing.

## Verification and handoff

2026-10-22: implemented locally on `feat/cozy-trips`; no remote push or production
database change. Uses the shared Wabi tokens, raised keys, typography and shelf
link. Dice loads lazily so entering Trips does not load Dice's full module graph.
No additional model provider was configured; Claude was unavailable in the shells.

Focused verification:

- 19 frontend checks: routing/shared provider, penny input, and accessible form
  labels plus exact-split error/draft preservation.
- 18 backend checks passed, including real local Supabase sessions, persistence,
  one-use invitations, member authorization, direct Data API RLS, denied browser
  writes, malformed money, concurrent-write conflict, edits, deletes, repayments,
  undo, shared migration-runner wiring and the existing shared startup guards.
  One pre-existing full Dice/Commons DB
  integration check is skipped because that separate test database is not owned.
- Supabase security advisors: no issues. Production Vite build passes; synthetic
  demo account credentials are excluded from the production output.
- Computer use in Chrome through the private URL: create Cabin weekend, add Alex
  and Jamie, split $120.01 equally with the extra penny assigned correctly, add
  a $90 exact split, reject an incorrect split while keeping its draft, edit the
  cabin to $150, reload and retain the $240 ledger and $70 balance, sign out and
  claim Alex's invitation, edit as Alex, record Jamie's $70 repayment, and verify
  all three balances become zero. Removal confirmation/cancellation also checked;
  destructive command behavior is verified by the real API tests.
- Desktop and 390x844 phone layouts inspected. Page and dialog have no horizontal
  overflow; expense cancellation leaves the persisted ledger unchanged.

The synthetic Cabin weekend remains available to explore with Matt or Alex.
The local server and dedicated Supabase instance are left running for the user.
Live Google OAuth and a production rollout remain outside this local delivery.

Main changed files: `backend/trips/`, `frontend/src/trips/`, the shared backend
and frontend route wiring, the Commons shelf, the shared migration runner,
`scripts/trips-dev.py`, and `supabase/trips-local.toml`. Focused tests live beside
the frontend and in `backend/tests/test_trips.py`.

Next concrete step: open the private preview, choose Continue as Matt, and
explore the synthetic Cabin weekend or create a new trip. No release work is
pending within this local increment.
