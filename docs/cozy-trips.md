# Cozy Trips

Cozy Commons project at `/trips`, with its authenticated API under `/trips`.

## Proposed integration plan — 2026-10-23

Status: active goal, authorized 2026-10-23. Deliver the core functionality,
complete end-to-end verification, database migrations, and a PR with passing CI
for the existing release path. Track live feature/test status in
[`cozy-trips-tests.md`](cozy-trips-tests.md). The existing implementation is a
locally verified Commons integration. A captured Splitwise trip reconciles exactly
in local Supabase, and shared account/profile reuse passes real local Auth/API and
browser checks. Actual Commons Google OAuth and the hosted rollout remain pending.
This plan supersedes the prototype's completion claim below.

### Outcome and stopping point

Matt and the friends on one existing Splitwise trip can open Cozy Trips from
Cozy Commons, use the existing Commons login, recognize their profiles, and see
the trip's actual expenses and balances. They can add or edit an expense and
record an outside repayment. An agent can operate the same labeled controls or
authenticated API. Stop when that one trip reconciles and the acceptance checks
below pass; further features stay parked.

Cozy Trips belongs to the `cozycommons/cc` monorepo, its normal React app at
`/trips`, shared FastAPI backend, and existing Supabase identity system. Use the
normal Commons build and release path. The local checkout's directory name does
not define a separate product, repository, deployment, or account system.

### Immediate delivery unit: one imported trip in Commons

1. **Establish the real source and a reconciliation target.** Inspect the
   existing authorized Splitwise session and look for an available export before
   asking Matt for data. Prior account work references `NITEHARTS 26`; verify its
   current contents and suitability rather than importing old conversation
   totals. Capture one trip read-only using an export, supplemented by visible
   account data if needed. Record members, currencies, expenses, payer amounts,
   individual shares, repayments, available source IDs, and current net balances.
   Keep raw personal data and identity mappings in ignored local storage. Commit
   only synthetic fixtures. Dismiss optional Pro prompts; stop at a genuine
   paid-feature restriction without subscribing or bypassing it.

2. **Integrate with the existing Commons session and profiles.** Use the shared
   Supabase singleton, Google login, canonical `auth.users.id`, and normal backend
   authentication. Preserve the requested trip or invitation through login and
   reload. Resolve display name/avatar from an existing Dice profile when
   available, then authenticated display metadata, with a guest label for an
   unclaimed trip member. Profile reads expose only needed display fields to
   authorized users. Do not create Dice game records as a side effect of opening
   Trips. Explicitly map Splitwise member IDs to known Commons user IDs; matching
   names alone never links accounts or grants access. Friends without Commons
   accounts remain distinct trip members and can claim their place by invitation.

3. **Import with a preview and exact accounting.** Show the source trip, people
   mapping, expenses, repayments, and any unsupported records before saving.
   Preserve available source IDs and import provenance. Re-importing the same
   snapshot adds nothing; distinct identical-looking expenses remain distinct.
   If an export omits stable IDs, retain a snapshot manifest and row identities
   rather than silently merging rows by description or amount. Validate and save
   the import atomically. Keep integer minor-unit accounting and revision checks.
   Retain the existing ledger structure unless the observed source requires a
   small extension, such as multiple payers. Do not silently approximate splits,
   currencies, settlements, or missing history. Require exact per-person net
   balance reconciliation for each currency before declaring the import complete.

4. **Fit the existing Commons interface.** Use the shared Commons navigation and
   `/design` components, spacing, typography, controls, dialogs, and avatar
   conventions. Compare the actual Commons and Dice screens before changing the
   Trips layout. Make the trip ledger and add-expense action the primary content;
   reduce the prototype's oversized introduction and decorative postcard. Reuse
   components where they fit, with mobile access and stable accessible names for
   computer use. Avoid a platform-wide design or profile-system rewrite.

5. **Verify the complete trip workflow.** Run focused import, identity,
   authorization, accounting, and conflict checks, plus the normal frontend
   build. Through computer use, enter Trips from Commons, authenticate, open the
   imported trip, inspect participants and balances, edit an expense, reload,
   record and undo a repayment, and return to Commons/Dice with the session
   intact. Use a local working copy for changes to imported financial records;
   preserve the captured source snapshot. Verify the same route on desktop and
   phone through the private Tailscale preview. Leave a concise reconciliation
   report and record which checks used synthetic versus actual accounts.

### Acceptance evidence

- Commons opens `/trips` through its normal navigation and build; `/dice` keeps
  working. The interface uses existing Commons components and conventions.
- Existing Commons Google login opens the intended Trips destination. The same
  canonical user ID and appropriate existing profile appear across projects;
  session persistence and sign-out work across navigation and reload.
- The captured source and imported trip have matching members, expense and
  repayment counts, and exact per-person net balances for every included
  currency. Every excluded or unsupported record is explained; unresolved
  differences prevent acceptance. Re-importing the same snapshot changes no
  records or balances.
- A second member can claim the intended place without duplicating a person or
  changing their historical shares. An unrelated account cannot read or mutate
  the trip, including through the Data API.
- Add/edit and repayment/undo persist and update balances correctly. Concurrent
  changes produce a reviewable conflict. Native labels and API errors support
  agent operation without a second permission or credential system.
- Desktop and phone computer-use evidence covers the workflow above. A working
  synthetic local preview is recorded as local evidence only.

### Environment boundary

Develop, migrate, and exercise database writes against loopback Supabase, using
the repository's existing guards. Do not reset shared services or weaken those
guards. Use the normal Commons application composition for integration checks;
retain the isolated Trips harness only as a regression fixture where useful.

Actual Commons SSO and existing production identities require validation against
the existing Commons environment. Before any production-connected operation,
present the concrete reviewed diff, migration/configuration changes, target
environment, and rollback steps for explicit authorization, as required by
`AGENTS.md`. In particular, verify the intended OAuth return origin is allowed;
do not repoint the guarded local harness at production. Until that validation is
authorized and succeeds, mark real SSO acceptance pending. Local test users
cannot satisfy it. No production migration or deployment is authorized by
creating this plan.

### Outside this slice

Continuous Splitwise synchronization, all-account migration, exchange-rate
conversion, payment processing, receipt OCR, notifications, a new global profile
platform, separate agent credentials, and a separate Trips deployment.

### Recorded next workflow: draft purchases and receipt matching

Requested 2026-10-23 for later delivery. Any trip member, including through their
personal agent using that member's trip permissions, can create a placeholder
purchase before the receipt is available. It can contain free text, rough
calculations, and who picked up which items. For example: at Safeway, one person
picked up two Gatorades while four friends bought protein shakes.

Other members or their agents can enrich that same entry with trip metadata and
later link the matching receipt and receipt items to the original purchase
context. This is the "join": match the receipt evidence to an existing draft,
then review people, amounts, and the split before confirming the expense.
Preserve the original notes while matching. Draft estimates do not affect
balances; confirming the expense posts its validated amounts. Repeating a receipt
match or confirmation must not create a duplicate bill.

This direction is parked while the current import, shared identity, migration,
and release acceptance work is completed. It does not add receipt OCR or a new
agent credential platform to the current implementation slice.

Current state: branch `feat/cozy-trips`, review-ready PR
[#85](https://github.com/cozycommons/cc/pull/85). Import, shared identity/profile
reuse, migrations, local browser acceptance, and repository regressions pass.
All five jobs pass at `cd50bcd` in CI run `39922337068`; the PR is mergeable.
See the verification ledger and PR checks for the current candidate's evidence.
No merge or hosted rollout has occurred. Raw source data stays ignored. The next
external checkpoint is authorization for the hosted Supabase/Google validation
and release; the later draft-purchase workflow remains parked.

## Prototype scope (historical)

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
- Trips and Dice use the same Supabase singleton, canonical user UUID, and normal
  shared backend. Existing Dice names/avatars are resolved only for linked trip
  members. Source names remain in the ledger; opening Trips never creates a Dice
  profile or links accounts by matching names/emails.

## Run locally

Requirements: Node 22, Python 3.12, Docker, and `psql`. Use Ubuntu/WSL for all
commands. Install the repository's locked dependencies and a backend virtual
environment, then:

```bash
cd ~/repo/cozy-trips
backend/.venv/bin/python scripts/trips-dev.py setup
backend/.venv/bin/python scripts/trips-dev.py run
```

`setup` starts the dedicated `cozy-trips-local` Supabase project, applies all
normal release migration families, and creates missing synthetic Matt/Alex/Jamie
users plus Matt's explicit sandbox Dice profile. The preview runs `main.app`,
including the normal Commons, Dice and Trips APIs. It preserves existing ledger
data and never resets another project's stack. Keys are
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

For production-bundle acceptance against the same local database, first sign in
using the development controls, stop only this runner, then run:

```bash
backend/.venv/bin/python scripts/trips-dev.py run --built
```

This builds the normal production app and serves it through the same local
proxies. The existing session persists, but synthetic sign-in controls are absent;
the local Google provider remains unconfigured. Restart without `--built` to
restore development controls. A browser filter blocks the raw `/src/dice/App.jsx`
development module on the verification machine; the built Dice route loads and
was used to verify canonical identity and cross-project sign-out.

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
| POST /imports/preview | Validate a Splitwise snapshot and preview the reconciled trip |
| POST /imports | Atomically save that snapshot, or reopen the identical existing import |
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

### Splitwise snapshot contract

Both import commands accept `{snapshot, own_member_id}`. `snapshot` uses format
`cozy-trips-splitwise-v1`: source group ID, name, currency, capture time, members
with stable source IDs, expenses with source IDs/payer/exact integer shares/date,
repayments, and every member's expected net balance. The API schema is documented
by FastAPI OpenAPI. The selected source member is linked to the authenticated
caller. Other people stay unclaimed until they accept an invitation; names alone
do not grant account access.

The preview validates the whole snapshot and exact ending balances before any
write. Saving uses one row insert. Stable IDs and a content digest make retries
and concurrent identical imports safe. A changed source snapshot or owner
mapping returns 409 for review, preserving the current ledger. Reopening an
identical import preserves subsequent Trips edits and source IDs.

For the browser-captured all-time printable summary, the local conversion tool
accepts rendered headings/tables, visible expense IDs, and an explicit member-ID
map. It cross-checks each person's paid/share amounts, group ending balances,
and group UI dates against the printable view's UTC day. It never queries
Splitwise's hidden state or sends changes to Splitwise.

```bash
PYTHONPATH=backend backend/.venv/bin/python -m trips.splitwise \
  .trips-dev/private/splitwise-printable.json \
  --expense-ids .trips-dev/private/splitwise-expense-ids.json \
  --member-ids .trips-dev/private/splitwise-member-ids.json \
  --currency USD --output .trips-dev/private/splitwise-snapshot.json
```

Select that snapshot under **Import from Splitwise**, choose your person, review
all balances, and save. The printable adapter requires complete all-time
expense history with one payer per expense and unambiguous source IDs. It stops
on incomplete/unsupported payment rows, multiple payers, refunds, or ambiguous
descriptions. The canonical snapshot API supports separately captured repayments.
Raw source files and local copies of personal trips remain ignored and are never
committed as fixtures.

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

### Preview lifetime repair (2026-10-23)

The first preview stopped when its temporary command session ended, leaving
Tailscale returning HTTP 502. The host now runs the preview through the enabled
per-user `cozy-trips-preview.service`. It starts the existing idempotent local
setup and runtime commands with Node 22, independently of agent command sessions,
and restarts the owned preview if it exits. The host's existing user lingering
setting was already enabled and was not changed. The database and Tailscale
forwarding were preserved. The host must remain awake and on the tailnet.

In this WSL host, inspect it with `systemctl --user status cozy-trips-preview`;
logs are in `journalctl --user-unit cozy-trips-preview`. The service configuration
lives in the host's user configuration, not in the shared application code.

Main changed files: `backend/trips/`, `frontend/src/trips/`, the shared backend
and frontend route wiring, the Commons shelf, the shared migration runner,
`scripts/trips-dev.py`, and `supabase/trips-local.toml`. Focused tests live beside
the frontend and in `backend/tests/test_trips.py`.

The synthetic Cabin weekend remains a regression fixture. The proposed
integration plan above defines the next delivery; this historical prototype
handoff does not establish that Cozy Trips is ready for actual Commons users.
