# Cozy Trips feature map and verification ledger

Updated 2026-10-23. This is the living acceptance record for the delivered goal:
deliver Cozy Trips at `/trips` inside Cozy Commons, merge the PR, and pass CI
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
| CC-01 | Group list and trip ledger | Enter `/trips` from Commons; deep links/reload work | passed on hosted Commons after both releases; Dice → Commons → Trips retains the shared account |
| AUTH-01 | Account sign-in | Existing Commons Google login and canonical user ID across Dice/Trips | passed fresh hosted Google OAuth; existing Dice profile and canonical ID reused |
| AUTH-02 | Session continuity | Refresh, navigation, expiry, sign-out and pending invitation return | hosted reload/navigation/shared sign-out and real Google invitation return passed; real local JS SDK refreshed an expired access token and rejected an invalid refresh token |
| PEOPLE-01 | Group members | Stable trip identities; existing Dice name/avatar where available | passed real local Supabase tests and canonical Matt identity in built Dice/Trips; no Dice profile created on Trips entry |
| PEOPLE-02 | Invite people | One-use claim preserves all historical shares; outsider denied | local browser claim/retry and unrelated-user denial passed; real API/RLS tests pass |
| EXP-01 | Add/edit/delete expense | Description, amount, payer, date, category, note; draft retained on error | passed desktop/phone browser, reload, validation and real API |
| SPLIT-01 | Equal split with selected people | Integer cents, deterministic rounding, subset selection | passed local browser: two-person odd-cent split and single-person subset |
| SPLIT-02 | Unequal amounts | Exact shares sum to cost; preserve source penny allocation | passed local browser validation/correction and exact source reconciliation |
| SPLIT-03 | Percentages and share weights | Integer share weights with exact penny allocation; percentages deferred | shares implemented: backend/frontend allocation parity tests, local browser 2:1:1 split |
| BAL-01 | Group balances | Exact per-person net balances and simplified transfer suggestions | passed source reconciliation, browser edits/repayments and conservation tests |
| PAY-01 | Settle up | Record outside payment and undo; never initiate money transfers | passed local browser and real API; both balances clear, then restore on undo |
| ACT-01 | Expense provenance / updates | Who changed what and when, readable expense details | passed local activity inspection; import activity plus retained source IDs/digest/original balances in API; notes persist after phone edit |
| IMPORT-01 | Printable/export trip history | Preview source, map people explicitly, preserve source IDs/shares | passed hosted preview/save under the real Commons identity; read-only field-level source hash matches all 14 expenses and all six members |
| IMPORT-02 | Repeat import | Same snapshot adds nothing; identical distinct expenses remain distinct | passed hosted phone repeat import: same trip at revision 1; concurrent Supabase import tests pass; changed snapshots fail 409 |
| IMPORT-03 | Source balance check | All people/currencies reconcile exactly; fail on unsupported data | 14 actual expenses and all six USD balances reconcile exactly; capture/date/unsupported-data tests pass |
| AGENT-01 | Form controls and actions | Stable native labels, predictable errors, same authenticated HTTP API | passed native hosted forms, Google flow, import/repeat and synthetic mutations; API scenarios pass locally/CI |
| UI-01 | Commons project conventions | Reuse Commons navigation/design components; desktop and phone | passed built app desktop and 390x844, shared account identity and native dialogs; page 375/375 and dialog 335/335 widths |
| UI-02 | Compact working interface | Keep the palette, remove decorative copy, show expenses sooner | passed local desktop/phone and hosted account/list/ledger after PR #87 deployment |
| PAY-02 | Venmo request composition | Optional own profile username; prepare person/amount/note and review | implemented: own save/clear/reload and outsider/validation API tests on real local Supabase; Pay/Request direction, encoding, USD gating, missing-handle fallback, zero writes on open and single record on retry covered in tests and local browser; link lands on Venmo's payment-link page with the same details |
| UI-03 | Mobile navigation and entry | Bottom tabs, reachable add/save, chips for payer/people/category | local 390px run: tab bar pinned, add button clear of it, sheet actions in view, no horizontal overflow |
| IMPORT-04 | Broader Splitwise content | Import the intended real sources without synthetic filler | pending account/scope clarification; connected account's dashboard/All expenses shows one group and 14 entries |
| DB-01 | Durable ledger | Forward migrations, fresh/upgrade/retry, receipts, schema attestation | passed locally and hosted: receipts 1/2 and readiness; `test_trips_migrations.py`, `test_migration_runner.py` |
| SEC-01 | Trip privacy | RLS member reads; API authorization; no browser writes/service keys | passed real local API/RLS/drift tests and hosted catalog/owner/outsider/anonymous checks |
| SHIP-01 | Normal Commons release | Backend migrates before listening; `/ready` checks Trips; route served | PR #85 merged/deployed by existing webhooks; hosted migrations 1/2, readiness, maintenance, grants and RLS passed |
| CI-01 | Reviewable release | Required DB tests run in CI; frontend/backend build, tests and lint pass | all five jobs pass for PR #85, its main run 39930286938, PR #86 run 39933511499, and merged follow-up run 39934493875 |
| SHIP-02 | Document cache after deployment | Revalidate SPA HTML so new routes and bundle references load | passed local and hosted: all six document routes on HEAD 200 and ETag 304 send Cache-Control: no-cache; normal shared navigation passed |

Splitwise also exposes recurring expenses, charts, comments, attachments,
multiple payers, adjustments, and other advanced splits. They are excluded from
this core release unless the captured trip requires them for exact import.
Unsupported import records must be reported, never approximated. No continuous
sync, currency conversion, payment processing, or separate Trips account system.

## Automated suite

| Layer | Required checks | Current evidence |
| --- | --- | --- |
| Money / ledger | Boundary amounts, pennies, subset/exact splits, edit/delete, repayments/undo, zero sum, transfer conservation | automated boundary/conservation tests and local native browser scenarios pass |
| Import | Valid source, malformed data, duplicates, edited snapshot, missing IDs, currencies, member mapping, reconciliation, atomicity | 33 ledger/import checks with real Supabase passed; 27 printable adapter/money/date checks passed, including year boundaries and leap day |
| Forms / auth | Native labels, validation/drafts, session changes, OAuth return, invitation return, empty/error/loading states | 35 focused frontend tests pass, including import, stale session/profile responses, account switching, query-preserving OAuth return, retained/blocked invitation storage, missing secret, normal-app login controls and retry |
| Real Supabase HTTP | Real sessions, API persistence, join/reuse, bad auth, unrelated user, denied direct writes, concurrent revisions | 44 ledger/import/profile/runtime checks pass with `TRIPS_INTEGRATION=1`, including all three real Auth/API scenarios through normal `main.app`; CI requires the Auth integrations |
| Real PostgreSQL migrations | Fresh and existing schema, repeat run, checksums/gaps, data preservation, RLS, policy/grant/index/column drift | 22 migration/release/readiness tests passed against owned Postgres 17 |
| Shared app / release | Commons/Dice/Trips routes, frontend container deep links, backend release readiness and migration failure | current normal production bundle, both containers, incoming migrations, maintenance and readiness-failure checks pass; original Dice harness guards also pass |
| Full repository regression | Frontend suite, lint, bundle budget, backend suite with isolated DB, container smoke checks, GitHub CI | 459 frontend tests and 786 backend tests pass, lint has zero errors (one pre-existing CommonsScene warning), bundle budget passes. Three real Supabase Auth cases skipped in the full PostgREST suite pass separately in the 44-check run. Both current container builds/smokes pass. See PR checks for remote CI |

## Computer-use acceptance run

- [x] Start at Commons and open Trips through normal navigation (built app, local Supabase).
- [x] Verify actual shared Google login and canonical identity/profile (fresh hosted OAuth, existing Dice account).
- [x] Preview and import the captured trip; compare every source balance (local Supabase, synthetic Matt session; real source data).
- [x] Repeat import and verify no record or balance changes (local session; same trip/14 expenses).
- [x] Add/edit/delete an expense, exercise validation, reload, verify persistence (separate synthetic acceptance trip).
- [x] Claim a second member's place and verify historical balances stay intact; repeat join is harmless (local Alex).
- [x] Verify an unrelated account cannot access the trip (local Jamie).
- [x] Record and undo an outside repayment; verify balances each time (synthetic trip).
- [x] Navigate to Commons/Dice/Trips with the same session, then sign out; Dice displays Sign in afterwards (normal production bundle, local Matt).
- [x] Inspect desktop and 390x844 phone layouts through private Tailscale; edit/reload and selected-person split passed.

Imported trip evidence: the expense count, total, currency, and all six source
balances match; private reconciliation output retains the amounts. The adapter exposed a
printable UTC/group-local date difference, now covered by regression tests. Only
the unchanged local acceptance copy was backed up and recreated with corrected
dates; the Splitwise account was unchanged. Reload persistence passed. Desktop
and phone screenshots are outside Git under `artifacts/cozy-trips/`; page and
import dialog have no horizontal overflow. These checks use synthetic local
identity and do not satisfy actual shared Google SSO acceptance.

## Hosted acceptance — 2026-10-23

The user approved the hosted audit, merge, deployment and real-account import.
PR #85 merged as `efbaf35c91e61f59bba1f6777d16370ccc199c4f`. All five main CI
jobs passed in [run 39930286938](https://github.com/cozycommons/cc/actions/runs/39930286938).
Both existing Coolify webhooks deployed that commit successfully; backend first,
then frontend. Public `/ready` returned ready, `/health` returned ok, and an
anonymous Trips API request returned 401.

- Pre-merge read-only audit: all Dice/Commons/Beli migration manifests matched
  the reviewed candidate, with no history gaps or checksum conflicts; Trips was
  absent. Post-release: Trips receipts 1/2, both readiness functions true, RLS
  enabled on both Trips tables, anonymous reads denied, authenticated ledger
  reads allowed and writes revoked, and readiness RPC denied to browser roles.
  The Supabase connector lacked project access, so the audit used the existing
  backend connection with PostgreSQL read-only enforcement; credentials stayed
  in Coolify. Catalog checks are scoped evidence, not a claimed advisor run.
- Fresh Google OAuth returned to Trips with the existing canonical Dice identity
  and display profile. Dice/Trips navigation retained it. Signing out in Trips
  made Dice show Sign in. A real Google round trip preserved a QA invitation;
  an already joined owner returned without claiming a second place. Real second
  account claiming remains covered by local Supabase/browser and required CI.
- The captured trip imported under the real account. Counts, every balance and
  a field-level financial/source projection match the private snapshot. Repeat
  import opened the same row at revision 1, with 14 expenses, six members and
  five unclaimed friends. No source expense or real trip record was edited for QA.
- A separate synthetic hosted trip passed equal pennies, exact mismatch/draft
  retention and correction, save/edit/reload, outside repayment, undo and delete.
  It was initially retained as an empty QA ledger, then privately backed up and
  removed under the user's later synthetic-data cleanup request (see follow-up).
- Hosted desktop and 390x844 screenshots are outside Git in
  `artifacts/cozy-trips/hosted-trip-desktop.png` and `hosted-trip-phone.png`.
  The phone page is 375/375 and the import dialog 335/335 (client/scroll widths).
- A real local Supabase JS SDK check forced an expired access token, refreshed it
  using its real refresh session, and reached the shared Trips API with the new
  token. An invalid refresh left no session; cleanup revoked only that test session.

Hosted browser testing twice exposed old Commons HTML being reused after deploy,
which hid the new shelf link until reload. Response headers confirmed no cache
policy. The follow-up adds `Cache-Control: no-cache` to the SPA document, including
internal route fallbacks, and adds CI container checks. The fixed local container
passes HEAD/200 and ETag/304 revalidation for `/`, `/index.html`, `/dice`, `/trips`
and trip/join deep links. Existing open tabs may need one reload; subsequent
documents receive the revalidation policy. PR #86 merged as
`05854ed78b4da1378589c9f10e4e332afe03cb27`; all five PR checks passed. The existing
frontend webhook deployed it successfully. Hosted verification passed for all
six routes on HEAD 200 and ETag 304, health/readiness, anonymous denial, and
Commons → Trips / Dice → Commons → Trips with the canonical profile. The
imported trip still has 14 expenses. Both running containers are healthy; see
`deployment.md` for immutable image identities. Backend remains on `efbaf35`.
All five merged follow-up CI jobs passed in
[run 39934493875](https://github.com/cozycommons/cc/actions/runs/39934493875).

Save screenshots and private reconciliation output outside Git. The previous
synthetic Cabin weekend run remains historical evidence, not a completed run of
this checklist. Production-connected validation and merge/deployment remain
explicit checkpoints under repository instructions; prepare the concrete diff
and migration evidence before requesting either.

## Current handoff

### Mobile profile, form and calculation clarity

The user requested their name/photo in the header, closer Dice styling, a
mobile form repair and an explanation of a missing direct creditor payment.
The header's mobile CSS had hidden the entire identity; it now retains the
name/photo and uses Dice's existing PlayerAvatar, with account-metadata fallback
while the shared profile loads. On the private local demo only, the existing
Matt test profile's display fields reuse the user's requested hosted name/photo.
The previous display fields are privately backed up; canonical account IDs and
the complete imported trip row stayed unchanged. LOCAL remains visible.

Native browser inspection reproduced unequal 134/164-pixel form columns caused
by the date control's intrinsic minimum. Phone forms now stack fields, use
consistent 44-pixel controls and keep Save/Cancel reachable. At the verified
390x844 viewport all five main controls are 288 pixels wide, the dialog is
320/320 pixels (client/scroll), and all exact-split rows are 256/256. Filling the
last note field, switching split modes and canceling saved no financial data.
The attempted narrower override did not apply; do not claim a 320-pixel browser
run or Safari device test.

The imported source and a fresh local ledger read agree: group-net suggestions
combine debts involving multiple people, rather than preserving every original
creditor. The Balances tab now explains this and offers a native expandable
breakdown of paid/share/repayment totals plus direct relationships. The group
algorithm, expense splits and repayment logic are unchanged. Private source
numbers remain out of Git. Three synthetic regression cases cover canceled
direct debts, both repayment directions, and payers outside the split; their
direct totals reconcile with the overall net. A header regression covers the
photo/name while the shared profile is loading. All 45 Trips frontend checks,
lint (zero errors; one existing CommonsScene warning), the production build and
bundle budget pass. Screenshots remain outside Git in
`artifacts/cozy-trips/mobile-form-fixed.png` and `mobile-balance-breakdown.png`.
These changes are on the private preview branch, with no new public deployment.

### Icons and Tailscale demo follow-up

Branch `feat/trips-preview-icons` adds functional icons to all four section tabs,
section headings, summary labels, invitation/repayment/delete/sign-out actions,
activity markers and trip rows. Text labels and the compact layout remain.
All 41 Trips frontend checks pass; lint has zero errors and its one existing
CommonsScene warning. The production build and bundle budget pass. Native
browser checks exercised all four tabs, the trip list, and dialog open/cancel.
At 390x844 the page is 375/375 pixels and the dialog 320/320 (client/scroll),
with no trip-row overflow. Screenshots remain outside Git in
`artifacts/cozy-trips/icons-preview-desktop.png` and `icons-preview-phone.png`.
No financial mutations or hosting changes were made.

The existing Tailscale service still runs `scripts/trips-dev.py run` against its
dedicated local Supabase, with synthetic sign-ins. The user's question about
hosted accounts/data is being clarified; no live-data switch is authorized by
an unanswered choice. Connecting the preview to the hosted project needs a
separate explicit frontend configuration and an allowed OAuth return URL for
the private origin. Keep the sandbox's loopback guards unchanged and never
bring a hosted service-role key into a frontend. The Supabase dashboard's URL
configuration page currently requires sign-in, so its existing redirect allow
list has not been verified. Next step: resolve the user's data-mode choice,
then inspect/prepare the exact private callback configuration before changing it.

### Venmo seed follow-up

The user supplied and confirmed all six username mappings, then explicitly
requested seeding. The existing hosted Supabase Auth accounts now contain
`user_metadata.venmo_username` and `venmo_username_provenance`; see
`cozy-trips.md` for the field contract. The seed used the supported Admin API,
verified canonical Google-backed identities, stopped on existing conflicting
values, and saved a mode-0600 metadata backup before updates. Six fresh account
reads verified exact values and preservation of every other metadata field,
application permissions and login identities. Dice display profiles and the
complete imported trip row remained identical. No schema, code deployment,
expense/repayment or trip membership changed. Private backup and receipt:
`/root/cozy-trips-venmo-seed-20261023.json` and
`/root/cozy-trips-venmo-seed-20261023-receipt.json`. The ignored local proposal
now records the completed action. Username ownership is not independently
verified in Venmo. The next increment is profile editing/display and prepared
Pay/Request details; the UI does not expose these seeded fields yet.

### Profile and review follow-up

Branch `fix/trips-profiles-polish` follows PR #87. The user requested existing
Supabase account matching, more compact branding/icons and subtle animation,
then explicitly requested three high-effort Sol reviews in parallel.

All three reviews completed read-only. Five distinct P2 findings were reproduced
and fixed locally: storage getters outside invitation error handling; missing
Auth metadata fallback for linked people without Dice profiles; concurrent trip
creation reporting a duplicate-key error; pending-save dialog dismissal losing
a later draft; and repeated descriptions having indistinguishable expense
action names. The reviewers rechecked their fixes with no remaining findings
in those bounded diffs. Root also reproduced a late save displaying the wrong
trip after navigation; workspaces now remount per account and route, with a
regression test. Dialog padding clicks stay inside the dialog.

Current evidence: 47 real local Supabase/API/profile/runtime/create checks pass.
The full account fallback is covered before a Dice profile exists, then after
one is explicitly created. A deterministic two-request barrier reproduces the
create race. Deferred-submit tests cover every modal dismissal path and route
navigation; repeated descriptions are selected by amount, payer and full date.
All 465 frontend tests pass across 69 files; lint has zero errors and its one
existing CommonsScene warning. The production build and bundle budget pass.
Native desktop and 390x844 browser checks confirm the branding/icons, centered
expense dialog, padding preserving an unsaved draft, and normal close/cancel.
The phone page is 375/375 pixels (client/scroll width); its dialog is 320/320.
No financial entries were saved during these checks. Browser testing also
reproduced the existing top-left dialog placement caused by reset CSS; the
dialog now explicitly centers within its viewport. Screenshots remain outside
Git in `artifacts/cozy-trips/profiles-trip-desktop.png` and
`profiles-trip-phone.png`.

PR #88 passed all five checks in run `39961318193` and merged as
`2679cc93749132bdd3d441370646b8aa92925fa8`. Both existing webhooks deployed that
commit successfully: backend `nqjtmcpu0pametu7whws1zdt`, frontend
`70t0go4gcp1l8r8ssyjbgkxv`. Both resulting containers were inspected healthy.
Hosted Google session/profile, all 14 expense actions, branding, centered
dialog, padding preserving an unsaved draft and cancellation passed. Six
document routes passed HEAD 200/ETag 304 cache checks; health/readiness and
anonymous denial passed. Hosted desktop proof is
`artifacts/cozy-trips/profiles-hosted-desktop.png`. The phone override did not
apply to the hosted tab, so phone evidence is explicitly local. All five
merged-main checks passed in run `39962370964`. This release adds no schema
migration and does not refresh the
Chrome-captured 14-expense/six-person source snapshot.

Five existing Google-backed accounts were identified read-only for the imported
people, including one Auth-only identity without a Dice profile. Exact UUIDs and
the proposed mapping stay in ignored `.trips-dev/private/profile-link-proposal.json`.
The file is a proposal, not authorization. An explicit action-time confirmation
is pending before adding those accounts to `member_user_ids`; that grants access
to private trip data and editing. No hosted account links have been applied.
Use the current human confirmation, preserve all financial/member/source IDs,
and record a revision/activity event if applying the confirmed data correction.

The visual change restores compact Commons branding, a Trips mark, small
functional category icons and restrained dialog/hover/refresh motion. Reduced
motion disables animations. It does not restore the earlier decorative hero.

### Compact UI follow-up

Branch `fix/trips-compact-ui` follows the delivered core release. The user asked
for less decorative copy and a compact Dice-like interface using the same
palette, cleanup of synthetic data, broader real Splitwise content, and clearer
agent use plus easier Venmo request composition.

- Compact trip rows, smaller title/summary, direct section names, readable
  owes/is-owed balances and reduced phone duplication are implemented.
- All 459 frontend tests pass, including the 35 existing Trips checks; lint has zero errors and its one
  existing CommonsScene warning; the production build and bundle budget pass.
- Native browser checks passed on desktop and 390x844: the expense ledger is
  visible much sooner, labeled expense fields remain available, cancel preserves
  the source copy, and page/dialog widths are 375/375 and 320/320 respectively.
  Screenshots are outside Git in `artifacts/cozy-trips/compact-trip-desktop.png`
  and `compact-trip-phone.png`.
- Two known local synthetic ledgers were removed with a private recoverable
  backup. The 14-expense source copy is byte-for-byte unchanged. The empty hosted
  `Release check · synthetic` ledger was also backed up and removed under the
  user's cleanup request. Whole-row equality guarded the delete, the real source
  row fingerprint stayed unchanged, and the hosted list now contains only the
  real import. The host backup is mode 0600 at
  `/root/cozy-trips-qa-backup-25ab7c46-20261023.json`.
- PR #87 passed all five checks in run `39955419844`, merged as
  `2494643121fddb3f2c9974539158c2d4b0eb1051`, and deployed via the existing frontend
  webhook (`nzvxici8a1daozoeh1hymgxt`). The running frontend and unchanged backend
  were inspected healthy. Hosted account/list/expense view, all six document
  cache checks, health/readiness and anonymous denial passed. All five merged
  CI jobs passed in `39956079287`. Hosted desktop proof is
  `artifacts/cozy-trips/compact-hosted-desktop.png`; phone evidence above is from
  the identical UI against local data, not a claimed hosted phone session.
- The connected Splitwise account's dashboard/All expenses screen shows only
  the existing group and its 14 entries. Another account/source and the desired
  import scope need clarification before broader import.
- (Superseded 2026-10-23: the Venmo workflow was agreed and is implemented; see
  "UI rework and Venmo" below.)

### Delivered core release

Later core workflow recorded from the user: any member or their personal agent
can start a draft purchase with notes, rough calculations, and item/person
context; enrich it collaboratively; and join receipt items to it later. Drafts
stay outside balances until confirmation. Future acceptance must cover shared
editing, preserved source notes, receipt-to-draft matching, explicit final split,
and duplicate-safe confirmation. Implementation remains parked for a separate
increment; see `cozy-trips.md`.

One branch/tree: `fix/trips-document-cache`, continuing from merged PR #85.
PRs #85 and #86 are merged and their webhook deployments are verified. Google
SSO, hosted source reconciliation, privacy, core mutation acceptance and the
cache fix have passed. Both merged commits' CI runs are fully green. The goal's
core delivery and acceptance work is complete; no release action remains queued.
The required Trips job ran 42
checks with real local Supabase Auth and no skips. Previously local-only CI and
handoff records were included with the functional fix as one verified batch.
This final evidence-only update is backed up on the closed feature branch;
no further open-PR CI run is needed just to record its completed deployment.
Both Coolify applications use source
`cozycommons/cc`, `main`/`HEAD`, Deploy on push (webhooks), and watch paths covering
Trips. The active GitHub ruleset requires fresh frontend/backend checks before
merge, with no bypass actors. The approved incoming release applied the additive
Trips schema and the authorized source import; no unrelated hosting setting,
legacy Dice deployment or service changed. No messages were sent to friends.

The normal production bundle was used for Dice/Trips session continuity because
a local browser filter blocks the raw Dice development module. `run --built`
reproduces that test against local data. The persistent private preview returns
to development controls for phone testing. Current proof is outside Git in
`artifacts/cozy-trips/shared-app-desktop.jpg` and `shared-app-phone.jpg`.
A dedicated owned PostgreSQL/PostgREST test stack uses 55432/55433/55431; the
preview's Supabase remains on 55321/55322. Other projects' services are intact.

Reproduction for the real Supabase check (after the documented local setup):

```bash
TRIPS_INTEGRATION=1 PYTHONPATH=backend backend/.venv/bin/python -m pytest backend/tests/test_trips.py backend/tests/test_trips_import.py backend/tests/test_trips_profiles.py backend/tests/test_trips_runtime.py -q
```

The full backend run requires the repository's allowlisted disposable DB and
real PostgREST test configuration; CI provisions them explicitly. Its three
skipped tests are the separate Supabase Auth integrations, which the `trips` job
runs with the command above. The required `backend` check always runs and fails
if that job fails or is skipped. The local container release check uses a fresh
owned database scaffold, matching CI, because regression tests intentionally
exercise invalid data/schema states.
