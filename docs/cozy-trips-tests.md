# Cozy Trips feature map and verification ledger

Updated 2026-10-23. This is the living acceptance record for the active goal:
deliver Cozy Trips at `/trips` inside Cozy Commons, prepare the PR, and pass CI
with migrations included in the normal release path. Update this file when a
feature, test, result, or blocker changes. Do not mark the goal complete from
synthetic browser checks alone.

## Source inspection

Inspected the authorized Splitwise group UI, expanded expense details and edit
form, split chooser, and all-time printable summary on 2026-10-23. The account
contains a six-person trip with 14 current expenses. A fresh capture differs
from the previously open stale page. Exact shares and the source's own rounding
must be retained. Raw account data and visible source IDs are saved only under
ignored `.trips-dev/private/`; committed tests use synthetic fixtures. No source
expenses, membership, comments, or repayments were changed.

## Core feature map

Status terms: `pending`, `implemented` (needs current verification), `passed`
(named current evidence), and `deferred` (outside the core release).

| ID | Splitwise surface / expected behavior | Cozy Trips requirement | Status / evidence |
| --- | --- | --- | --- |
| CC-01 | Group list and trip ledger | Enter `/trips` from Commons; deep links/reload work | implemented; current E2E pending |
| AUTH-01 | Account sign-in | Existing Commons Google login and canonical user ID across Dice/Trips | pending real OAuth proof |
| AUTH-02 | Session continuity | Refresh, navigation, expiry, sign-out and pending invitation return | pending |
| PEOPLE-01 | Group members | Stable trip identities; existing Dice name/avatar where available | pending profile reuse |
| PEOPLE-02 | Invite people | One-use claim preserves all historical shares; outsider denied | implemented; automated expansion pending |
| EXP-01 | Add/edit/delete expense | Description, amount, payer, date, category, note; draft retained on error | implemented |
| SPLIT-01 | Equal split with selected people | Integer cents, deterministic rounding, subset selection | implemented |
| SPLIT-02 | Unequal amounts | Exact shares sum to cost; preserve source penny allocation | implemented |
| SPLIT-03 | Percentages and share weights | Assess as follow-up after equal/exact source trip works | deferred from first core release |
| BAL-01 | Group balances | Exact per-person net balances and simplified transfer suggestions | implemented |
| PAY-01 | Settle up | Record outside payment and undo; never initiate money transfers | implemented |
| ACT-01 | Expense provenance / updates | Who changed what and when, readable expense details | implemented; source provenance pending |
| IMPORT-01 | Printable/export trip history | Preview source, map people explicitly, preserve source IDs/shares | passed locally through desktop/phone UI and real Supabase API; real Commons identity still pending |
| IMPORT-02 | Repeat import | Same snapshot adds nothing; identical distinct expenses remain distinct | passed local browser and concurrent Supabase import tests; changed snapshots fail 409 |
| IMPORT-03 | Source balance check | All people/currencies reconcile exactly; fail on unsupported data | 14 actual expenses and all six USD balances reconcile exactly; capture/date/unsupported-data tests pass |
| AGENT-01 | Form controls and actions | Stable native labels, predictable errors, same authenticated HTTP API | implemented; complete E2E pending |
| UI-01 | Commons project conventions | Reuse Commons navigation/design components; desktop and phone | compact trip home/import UI checked locally at desktop and 390x844; profile/normal app integration pending |
| DB-01 | Durable ledger | Forward migrations, fresh/upgrade/retry, receipts, schema attestation | passed locally; `test_trips_migrations.py`, `test_migration_runner.py` |
| SEC-01 | Trip privacy | RLS member reads; API authorization; no browser writes/service keys | passed locally; real Supabase API/RLS and PostgreSQL drift tests |
| SHIP-01 | Normal Commons release | Backend migrates before listening; `/ready` checks Trips; route served | passed locally in built frontend/backend containers; hosted rollout pending |
| CI-01 | Reviewable release | Required DB tests run in CI; frontend/backend build, tests and lint pass | draft PR #85; all five jobs pass at 7b9de73; next local batch not pushed yet |

Splitwise also exposes recurring expenses, charts, comments, attachments,
multiple payers, adjustments, and other advanced splits. They are excluded from
this core release unless the captured trip requires them for exact import.
Unsupported import records must be reported, never approximated. No continuous
sync, currency conversion, payment processing, or separate Trips account system.

## Automated suite

| Layer | Required checks | Current evidence |
| --- | --- | --- |
| Money / ledger | Boundary amounts, pennies, subset/exact splits, edit/delete, repayments/undo, zero sum, transfer conservation | existing tests; expansion pending |
| Import | Valid source, malformed data, duplicates, edited snapshot, missing IDs, currencies, member mapping, reconciliation, atomicity | 33 ledger/import checks with real Supabase passed; 27 printable adapter/money/date checks passed, including year boundaries and leap day |
| Forms / auth | Native labels, validation/drafts, session changes, OAuth return, invitation return, empty/error/loading states | 17 focused frontend tests pass, including explicit import preview/save, existing import, invalid/oversized files, retained identity, and cancel; auth expansion pending |
| Real Supabase HTTP | Real sessions, API persistence, join/reuse, bad auth, unrelated user, denied direct writes, concurrent revisions | 33 focused ledger/import tests passed with `TRIPS_INTEGRATION=1`, including both real Auth/API scenarios; CI runs the dedicated suite |
| Real PostgreSQL migrations | Fresh and existing schema, repeat run, checksums/gaps, data preservation, RLS, policy/grant/index/column drift | 22 migration/release/readiness tests passed against owned Postgres 17 |
| Shared app / release | Commons/Dice/Trips routes, frontend container deep links, backend release readiness and migration failure | in progress |
| Full repository regression | Frontend suite, lint, bundle budget, backend suite with isolated DB, container smoke checks, GitHub CI | current local import batch: 441 frontend tests, 776 backend tests, lint and bundle budget pass. The two real Supabase scenarios skipped in the PostgREST run pass separately in the 33-test suite. Published foundation: both container builds, release/maintenance/readiness/route smoke checks, and all five GitHub CI jobs passed |

## Computer-use acceptance run

- [ ] Start at Commons and open Trips through normal navigation.
- [ ] Verify actual shared Google login and canonical identity/profile.
- [x] Preview and import the captured trip; compare every source balance (local Supabase, synthetic Matt session; real source data).
- [x] Repeat import and verify no record or balance changes (local session; same trip/14 expenses).
- [ ] Add/edit an expense, exercise validation, reload, verify persistence.
- [ ] Claim a second member's place and verify historical balances stay intact.
- [ ] Verify an unrelated account cannot access the trip.
- [ ] Record and undo an outside repayment; verify balances each time.
- [ ] Navigate to Commons/Dice/Trips with the same session, then sign out.
- [ ] Inspect desktop and 390x844 phone layouts through private Tailscale.

Imported trip evidence: the expense count, total, currency, and all six source
balances match; private reconciliation output retains the amounts. The adapter exposed a
printable UTC/group-local date difference, now covered by regression tests. Only
the unchanged local acceptance copy was backed up and recreated with corrected
dates; the Splitwise account was unchanged. Reload persistence passed. Desktop
and phone screenshots are outside Git under `artifacts/cozy-trips/`; page and
import dialog have no horizontal overflow. These checks use synthetic local
identity and do not satisfy actual shared Google SSO acceptance.

Save screenshots and private reconciliation output outside Git. The previous
synthetic Cabin weekend run remains historical evidence, not a completed run of
this checklist. Production-connected validation and merge/deployment remain
explicit checkpoints under repository instructions; prepare the concrete diff
and migration evidence before requesting either.

## Current handoff

Later core workflow recorded from the user: any member or their personal agent
can start a draft purchase with notes, rough calculations, and item/person
context; enrich it collaboratively; and join receipt items to it later. Drafts
stay outside balances until confirmation. Future acceptance must cover shared
editing, preserved source notes, receipt-to-draft matching, explicit final split,
and duplicate-safe confirmation. Implementation is parked until this release's
existing acceptance work is complete; see `cozy-trips.md`.

One branch/tree: `feat/cozy-trips`. Goal active. Draft PR #85 is attached; published
foundation CI is green. Current import UI/API/conversion/tests, AGENTS CI batching
rules, and later purchase-draft direction remain local for the next verified
batch. Continue with shared profile/session integration, then the remaining E2E
checks before the next PR push. A dedicated owned PostgreSQL/PostgREST test stack uses 55432/55433/55431;
the preview's Supabase remains on 55321/55322. Other projects' services are intact.

Reproduction for the real Supabase check (after the documented local setup):

```bash
TRIPS_INTEGRATION=1 PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/test_trips.py backend/tests/test_trips_import.py -q
```

The full backend run requires the repository's allowlisted disposable DB and
real PostgREST test configuration; CI provisions them explicitly. Its two
skipped tests are the separate Supabase Auth integrations, which the `trips` job
runs with the command above. The required `backend` check always runs and fails
if that job fails or is skipped. The local container release check uses a fresh
owned database scaffold, matching CI, because regression tests intentionally
exercise invalid data/schema states.
