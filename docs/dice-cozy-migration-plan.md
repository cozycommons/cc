# Dice to Cozy Commons: bulk migration feasibility and plan

Assessed September 9, 2026 (America/New_York). Status: **bulk code migration is feasible; production cutover is not yet proven safe**. This document is an assessment and execution design, not a record of a completed migration.

## Decision and scope

Use one integrated Dice snapshot, not a sequence of old PRs or worktree cherry-picks. Bring the current Dice feature implementation, its tests and verification recipes into the new Commons repository, then reconcile the few shared integration points. Preserve Commons home, its data, the new Coolify topology, dependency manifests and routing conventions. Retaining the old optional/legacy Dice UX is not a requirement.

The immediate next delivery is one local migration candidate with a passing synthetic upgrade rehearsal and CI changes. Stop before hosted data writes, deployment, cutover or deleting any source. The later cutover design below constrains that candidate; it is not authorization to operate production.

## Frozen evidence

- Destination: `cozycommons/cc` at `83c9bafe2759cef0728a1446245fe2e46bead56c`.
- Old main: `jasonkeung/dummi` at `3e7369afc7afabbcd08dfe20b4be6d7e32ec4cfe`.
- Integrated source: `335cdff294ae921d0b4b2c66131c7194ce9190ed`, branch `feat/dice-referee-outcomes-log` in `~/repo/dummi-referee-outcomes`. Exactly one additional committed change above old main; clean checkout when inspected.
- Reconstructed import baseline: old commit `1e0dc083` (September 3). All 65 common Dice frontend files and all 35 common migration-directory files in the initial Commons import match this commit byte-for-byte. 19 of 20 backend Dice files match; notifications intentionally changed to `SITE_URL`.
- The repositories have no Git merge base. The baseline above is established from file contents, not shared ancestry.
- A non-mutating `git apply --check` of the baseline-to-source delta scoped to `frontend/src/dice`, `backend/dice`, Dice backend test files and Dice fixtures reports only `frontend/src/dice/App.jsx` as a conflict. This does not prove a build or runtime pass.
- Comparison to the integrated source: Dice frontend has 38 changed, 25 source-only, four target-only and 23 identical files. Backend Dice has 11 changed, two source-only and nine identical files.
- Full scoped blob inventory: [dice-migration-inventory.json](dice-migration-inventory.json).

## Infrastructure facts and remaining uncertainty

Public deployed frontend configuration and Supabase project metadata establish two different projects:

| | Existing Dice | Cozy Commons |
|---|---|---|
| Project ref | `yllwleldhtjyqjgdfrpn` | `dhjnrnhjghsulbevfhno` |
| Region | us-east-2 | us-west-2 |
| PostgreSQL | 17.4.1.054 | 17.6.1.166 |
| Public API hostname | api.jasonkeung.com | api.cozycommons.dev |

Both project metadata responses report ACTIVE_HEALTHY. New API `/health` and `/ready` return HTTP 200. `/ready` only selects `dice_profiles.user_id`; it does not attest the full Dice or Commons schema. The public frontend project ref does not independently prove the backend points to the same database.

No hosted SQL, row exports, Storage inventory or identity inventory was performed. Still unverified: each backend's actual project binding; applied custom and Supabase migration histories; deployed function definitions; existing destination users/games/photos/Commons data; whether both sites accept writes; backup restoreability; actual Coolify pre-deploy commands, CI gating, worker schedules and source commit/image digests. Treat the destination as populated until evidence establishes otherwise.

## Bulk feature import boundary

1. Apply the complete baseline-to-integrated-source delta for `frontend/src/dice/`, `backend/dice/`, `backend/tests/test_dice*.py`, Dice fixtures, Dice verification recipes and current Dice contracts/docs. Include `backend/tests/dice_test_database.py`. Do not import unrelated apps, tests or the old deployment workflows.
2. Resolve the Dice route component once: retain Commons lazy imports/Suspense, add current Dice routes and remove the retired feature gating. Keep Commons top-level home/router and `/dice` frontend/API mounting.
3. Preserve the new `backend/dice/notifications.py` origin convention (`SITE_URL` plus `/dice`). Its difference is intentional and is not part of the upstream feature delta.
4. Carry the `frontend/src/api.js` structured error change: callers need `error.status` and `error.detail` for stale/conflicting commands. Keep the new shared Supabase context; the observed difference there is whitespace. Preserve the target package manifests/lockfiles and install only dependencies proved necessary by the build. Backend external imports from the Dice package are already represented by target dependencies.
5. Bring over the Dice live scenario/fuzz/regression tools, isolated DB bootstrap/helper and focused checks, adapting them to the Commons harness rather than replacing `dice-dev.sh`, runtime policy, Dockerfiles or CORS wholesale. Add request telemetry through the new backend lifecycle so command retries remain diagnosable.
6. Restore the two Dice operational jobs (`dice_live_rating_repairs.py`, `dice_rating_rebuild.py`) and their tests. Use a narrowly scoped Coolify worker/scheduled command and a deterministic post-upgrade rebuild, with single ownership and loopback-only behavior in local tests. The new backend has no scheduler startup; setting ENABLE_SCHEDULER alone will not run these jobs. Do not import the entire old multi-app worker.
7. Record the imported source SHA and resulting path manifest. Older open PRs are not authoritative feature inventory: current old main already incorporates many overlapping changes. Keep their branches intact; separately list any proven residual feature gap instead of merging every branch.

## Schema reconciliation: blockers and intended treatment

The target Dice contract is **0064**, versus **0078** in the source. These 14 source migrations are absent:

| Versions | Purpose |
|---|---|
| 0065 | Live command metrics |
| 0066–0067 | Ranked settings and live match deletion |
| 0068–0069 | Duo replay support and server-only privileges |
| 0070–0071 | Canonical ranked mutations and concurrency |
| 0072 | Durable live-rating repair queue |
| 0073–0074 | Atomic live lifecycle and stale manual-edit protection |
| 0075 | Duo snapshot fix-forward and canonical rebuild support |
| 0076 | Live referee default-on |
| 0077 | Persisted recorded-stat snapshots |
| 0078 | Retire the live-referee rollout flag |

Two historical files, **0045 and 0064**, have different bytes between the repositories. Do not overwrite or renumber the target's historical migrations. Keep target history intact; append 0065–0078 with source hashes, and advance the contract only after proving convergence. Later SQL adds the ranked column (0066), replaces guards (0070) and the materializer (0077), but equivalent final behavior must be tested against both historical starting variants. If convergence is incomplete, add a new forward reconciliation migration rather than rewriting history.

The existing migration ledger records version/time, not content hashes. Before adopting an existing database, attest actual tables, constraints, function definitions/privileges and ledger holes. A `dice_profiles` table alone is insufficient evidence for assuming baseline 0042. Add provenance/checksum records for new execution and verified baseline adoption; never invent checksums for unknown historical executions or blindly stamp versions as applied.

These are not all additive migrations. 0075 clears individual-rating fields on duo-only evidence and requeues repairs; 0077 backfills stats from live projections; 0078 normalizes feature access to enabled. Preserve source snapshots and explicitly enumerate these expected transformations. Preserve authoritative event/command history and mutation receipts; compare/rebuild derived ratings using the correct canonical source rules. Do not make an unexplained rating difference disappear by accepting a new baseline.

### Migration ownership in the new infrastructure

Current deployment documentation tells Coolify to run `apply-commons-migrations.sh`, which explicitly excludes Dice; it says the old Dice workflow owns Dice migrations. That arrangement does not establish an owner for new Dice migrations on the separate Commons database. The backend also contains a combined runner, duplicating logic from repository scripts.

Design: one serialized migration entry point for the new database, with explicitly owned Dice/analytics and Commons families, one tested implementation shared by CLI and container entry points, a database-held advisory lock spanning the migration session, per-file transaction plus receipt, and explicit expected project identity before writes. Apply/attest Dice and Commons before activating the new API. The old workflow continues to target only its existing project until old writes are retired; never give two independent deploy systems ownership of the same target.

Make readiness/rollout prove the release's Dice **and** Commons contracts, not just a profile-table SELECT. Preserve `/health` as liveness, but require migration attestation and readiness before traffic. Verify Coolify's actual configuration and CI-success gate; the repository workflow itself does not deploy or establish that external gate.

## CI evidence and required upgrade proof

At the assessed target SHA, GitHub run [34279399033](https://github.com/cozycommons/cc/actions/runs/34279399033) failed in the backend at `scripts/test-commons-migrations.sh`; frontend succeeded. Reproduced locally without a database:

| Check | Result |
|---|---|
| Dice migration contract | pass, contract 0064 |
| Commons migration contract | pass, contract 0008 |
| Supabase URL/runner mock tests | pass |
| Commons migration runner tests | FAIL: 0008 not recorded as applied |
| Backend pre-deployment runner tests | FAIL: same error |

Both psql mocks enumerate Commons versions only through 7. Fix mock migration discovery/recording so advancing the contract does not silently stale the fake database. Keep independent expected-version assertions so a missing migration is still detectable.

More importantly, target CI has no Postgres service or DB_URL. Transaction tests and several live-store/virtual-currency tests skip; shell runner tests use mocked psql. Restore a required isolated PostgreSQL 17 job, modeled on the old workflow but scoped to Dice plus Commons. Required DB tests must fail, rather than skip, when prerequisites are absent. Add focused PostgREST/auth/RLS coverage where SQL alone cannot prove API semantics.

The candidate must pass:

- Fresh owned schema through Dice 0078 plus Commons 0008.
- Populated target 0064 → candidate, preserving existing Commons rows and seeded Dice/auth relationships.
- Current old 0078 → candidate adoption without re-executing historical DML; rerun is a verified no-op.
- Both known historical SQL variants, interrupted migration then retry, ledger gaps/unknown drift rejected before changes, and concurrent runner serialization.
- Synthetic identity/record collisions and resumable data-import rehearsal; same IDs with different content must abort/quarantine rather than overwrite.
- Preserved user/profile/game/player/comment/tournament links, immutable live command/event IDs/order/receipts, scores, ranked state and virtual balances; expected 0075/0077/0078 transformations separately asserted.
- Canonical and duo replay, queued repair failure/retry, edit/reopen/delete and duplicate/stale command tests. Commons regression tests remain required.
- Frontend tests/lint/bundle gate, backend tests, shell compatibility, both container builds and a synthetic end-to-end Dice journey through the new shared router.

Local doctor found Docker/psql/Python available but active Node **24** rather than required **22**. Use installed Node 22 if available before installing anything. A shared `dummi-dice` Supabase stack already occupies the standard ports. Do not reset/stop/use it for migration experiments: provision a separately named test container/database with non-conflicting bindings, or use CI-owned services. No services were changed during this assessment.

## Data move and cutover design

Code import and database migration are separate release steps. Use a bulk scoped dataset transfer plus explicit conflict reconciliation, not a whole-project restore over an existing Commons project. Full restore could overwrite Commons identity/data and copy unrelated old apps. The initial rehearsal uses synthetic data only; authorized production transfers use controlled infrastructure outside the source repository.

1. **Inventory both sides read-only.** Capture schema definitions and migration ledgers, scoped table counts/IDs/content digests, auth identity relationships, Storage manifests, active matches, queued repairs and write paths. Include custom auth/storage triggers, RLS, grants, Realtime publications and relevant scheduled/edge jobs. Determine authoritative ownership of differing records before designing inserts. Never match identities by display name.
2. **Prepare and prove recovery.** Retain restorable backups of both projects and independently protected Storage objects. Establish restore procedures before destructive transformations. Record backups, release SHAs/image digests and the planned writer freeze boundary.
3. **Reconcile identity and scope.** Prefer preserving old UUIDs when there is no conflict. Existing destination users with overlapping verified identities require an explicit audited mapping covering all Dice and Commons references plus object ownership. Do not overwrite the destination auth schema or casually merge accounts by email. Expect reauthentication against the new project; provider/redirect configuration and signing keys are separate from SQL data.
4. **Prepare destination schema and import staging.** Attest/migrate destination Dice and Commons first in the tested order. Stage the source dataset, classify source-only/destination-only/identical/conflicting IDs, then transfer all dependent Dice records as one planned dataset. Preserve source-only and destination-only records; quarantine conflicting content for a deterministic decision. Maintain an import manifest and atomic progress records for resumability. Keep job/notification side effects disabled during import, and revalidate constraints before acceptance.
5. **Copy and reconcile Storage separately.** Include profile/comment buckets and any referenced media dependency; paginate/recursively inventory every object. Compare object path, content digest, size and content type, and preserve bucket policies/ownership. Reject same-path/different-content overwrite. Remap only URLs proven to refer to moved objects, including embedded JSON references; do not blanket-replace every URL string.
6. **Briefly freeze both Dice writers for final reconciliation.** Include APIs, workers, uploads and direct client writes; wait for in-flight mutations. Keep Commons available if it can be isolated safely. Capture a consistent final source/destination state, include deletes and late updates, rerun reconciliation and import the final delta. Avoid a long-running dual-write scheme for this migration.
7. **Accept by evidence.** Source and destination manifests must reconcile with zero unexplained missing/conflicting records, broken identity references or missing media; aggregate checks alone are insufficient. Check per-record canonical digests excluding only documented transformations, foreign keys/orphans, immutable event chains, command idempotency and mutation receipts, exact virtual-ledger sums, independent/duo rating replay and repair queue completion. Use exact arithmetic/declared numeric tolerances where appropriate. Preserve existing Commons data and verify its own schema and user references.
8. **Activate one writer.** Deploy migration-compatible backend/worker then frontend at frozen image digests after CI and attestation. Update the documented origin/OAuth/CORS configuration. Leave the old Dice write path disabled/redirected once new writes begin; retain the source backups and records through an agreed validation period. Do not delete the old project as part of code migration.

Rollback before enabling target writes can restore application images and retain the unchanged old writer. Once target writes exist, switching back blindly would lose them: freeze writes, capture and reconcile the target delta, then recover forward or execute a separately proved reverse transfer. Database rollback must not mean replaying old SQL over the new schema.

Supabase's [backup/restore guide](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore) treats database, migration history, auth/storage customization, Storage files and platform settings as distinct transfer concerns. Its [auth migration guide](https://supabase.com/docs/guides/troubleshooting/migrating-auth-users-between-projects) explains project-specific token validity. Adapt those procedures to two populated projects; do not execute their whole-project examples blindly.

## Handoff and acceptance boundary

Completed: cloned a dedicated assessment checkout, fetched source refs into that checkout only, established content baseline, inventoried feature/schema differences, dry-ran scoped patch application, inspected public configuration/project metadata/health, reproduced five focused checks and verified the GitHub failure. No product code, hosted SQL/data, source checkout, deployment or shared service was changed. No full frontend/backend/SQL upgrade suite was run.

Next: implement the single bulk candidate and its schema/CI rehearsal after alignment on this design. The hosted inventory is the remaining evidence needed to choose exact account/data conflict rules and release ordering; the code candidate can proceed independently. This repository's AGENTS.md requires explicit production-connected authorization before database operations. Hosted read-only attestation should be scoped to schema and aggregate/digest reconciliation, with no raw user-data export to the repository.
