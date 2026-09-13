# Dice convergence: active work

Goal: make Cozy Commons the sole working home for Dice, complete the release
and data reconciliation, and deliver the remaining referee/play-log enhancements.
The user authorized this long-running implementation on 2026-09-13.

## Starting evidence

- Commons baseline: `915c1411ac4f40d1a6d4203d1d7daf6781bcdeb5`.
- Earlier candidate: `79b03345520e40e20a9429af67d9d0c816337aec`, PR #1.
- Dummi main: `41fa1ef3`, including Dice retirement `7e78148f`.
- Commons' 86 Dice frontend files, 22 backend files, both rating job modules
  and nine checked-in asset files exactly match Dummi before retirement.
- September 13 read-only comparison reconciled all 17 hosted Dice tables
  after the existing single-account UUID mapping and Storage origin changes.
  Both projects have 98 Storage objects; target avatar/comment fields contain
  no old Storage URLs. Original and compressed objects were hash-verified during
  the September 10 copy. Do not run another blind bulk import.
- Target database records Dice 0079 and Commons 0012. Current main only carries
  Dice through 0078. Preserve applied 0079 bytes from the earlier candidate.
- Main CI: 372 backend tests passed, 29 skipped. One Commons scene frontend
  test failed because it checks loaded scene text after waiting for an image
  container which is present before scene data arrives.
- Old /dice URLs return 308 to the Commons Dice homepage; old Dice API returns
  404. Retirement was done upstream, not by this migration task.

## Decisions

Use current Commons main as the base. Preserve new Commons scenes and /scene,
shared contracts, root Docker build contexts, vendor chunks and runtime smoke
tests. Bring across only missing migration/verification tooling and the accepted
referee enhancements. Supersede PR #1 once a green replacement exists.

Do not edit or replay applied migrations. Main already changed historical
0045/0064 during its import; document and test both known histories rather than
silently reverting these files. Add forward readiness coverage for Commons 0012.

Release must run migrations from the incoming release before accepting traffic.
Coolify's ordinary pre-deploy hook runs in the existing container and is not a
sufficient mechanism. Container health currently checks /health; release needs
actual database readiness. Rating modules define run_job functions but no
invocation is wired into main. Establish a verified maintenance invocation.

## Immediate delivery and stopping point

Construct a focused candidate on this branch with database-backed CI, current
schema attestation, the integration fixes and referee enhancements. Verify on an
owned isolated environment; keep the shared Supabase stack untouched. Stop this
increment when the candidate is reviewed and green, then continue toward merge
and release under the active goal.

## Access dependency

Coolify dashboard URL, team access, active deployment settings and maintenance
schedules are still unknown. GitHub and Supabase access are available. Do all
independent implementation before requesting missing release access again.

## Candidate progress (September 13)

The working diff now carries the missing referee/play-log improvements, asset
copy and verification tooling, migration runner, readiness attestation and
maintenance CLI. Applied 0079 was copied unchanged; new 0080 advances readiness
to Dice 0080 and Commons 0012. Historical 0045/0064 remain unchanged from main.
The incoming image starts through `release.py`, applying both migration families
before HTTP, and Docker health checks `/ready`. CI now exercises real PostgreSQL
and PostgREST plus an incoming-image release/maintenance scenario. Deployment
documentation describes the required runtime database configuration and schedule.

Verification: 409 backend tests passed with zero skips against the owned
loopback database; 338 frontend tests passed. The Commons scene test now waits
for loaded data. Notification tests use the Commons origin, and virtual-currency
tests use the same isolated-database guard as the other integration tests.
`git diff --check` passed. Hosted state has not changed during this increment.

Additional checks passed: clean frontend install, lint and bundle budget; backend
image build; fresh incoming-image migration to 0080/0012; maintenance rebuild on
the empty fixture database; Docker healthy state; liveness 200/readiness 503
when PostgREST is stopped. Both histories are now checked before either family
applies pending SQL, with a real database regression covering a damaged Commons
receipt blocking pending Dice work. The focused runner tests pass.

Still pending: verify the referee journey in the browser and finish reviewing
the replacement PR. GitHub CI passes the complete container failure checks.
Do not merge or report a successful deployed release yet. Coolify access remains
necessary to inspect the actual trigger, deployed revisions, health configuration,
scheduled maintenance and post-deploy results.

Replacement draft PR: https://github.com/cozycommons/cc/pull/5. CI run
34776355374 passed both jobs for 5e85dc43, including the complete incoming-image
release/maintenance scenario. Local frontend container smoke checks also passed
for `/`, `/dice`, `/scene` and the room asset; a corrupt receipt prevented backend
startup. A subsequent fix makes the maintenance CLI fail visibly after draining
a batch containing failed repairs; five focused rating-job tests passed.
CI run 34776484434 passed both jobs for c1998efa, verifying that follow-up.

GitHub initially had no active protection on `main`; its existing ruleset was
disabled. Created and read back active ruleset 23201531, requiring `frontend`
and `backend` from GitHub Actions app 15368, strict branch freshness and no bypass
actors. The older disabled ruleset is untouched. `gh pr checks 5 --required`
now recognizes both checks. Coolify trigger configuration remains unverified.

## Coolify access verified

The user supplied https://admin.cozycommons.dev/ and browser sign-in succeeded.
Root Team has project `myslnzrcuucdffkthj0tswam`, environment
`gudimtlnyhv3mrz7bqcjkifg` (named production, but this is the user's staging app).
Backend resource: `ira6t1lrdcckadpn2jf1brdg`; frontend:
`rrmtxvricbf8ifbldflw2brb`. Both deploy on push through GitHub App `coolify-cc`.
Latest observed backend deployment `1u45onvw9gz92p7fqyfuzdl4` succeeded for
915c1411ac4f40d1a6d4203d1d7daf6781bcdeb5. No deployment was triggered here.

Backend uses root build context, `/backend/Dockerfile`, port 8000 and
https://api.cozycommons.dev. Supabase URL was verified as target
dhjnrnhjghsulbevfhno.supabase.co; service key, DB URL and pooler host variables
exist. The URL is runtime-only. Existing pre-deploy command is
`bash apply-commons-migrations.sh`; post-deploy is empty; no scheduled tasks.
Coolify's HTTP health override is disabled and its UI detects the image's custom
health check. Keep the image check when the PR switches it to `/ready`.

Frontend uses root context, `/frontend/Dockerfile`, port 80 and
https://cozycommons.dev. Watch paths currently contain only `frontend/**`, so add
the shared scene contract when configuring the cutover. Backend watch paths are
empty. Both resources still run main; PR #5 is not merged.

Next configuration work: verify DB URL/pooler scope, add
EXPECTED_SUPABASE_PROJECT and SITE_URL, remove the old migration hook at cutover,
wire post-deploy rebuild and serialized maintenance, then verify real execution.
The individual variable form failed to persist changes; browser logs show an
Alpine syntax error containing an uncompiled @js expression. The bulk editor
worked: production EXPECTED_SUPABASE_PROJECT=dhjnrnhjghsulbevfhno and
SITE_URL=https://cozycommons.dev are now saved. Reload and readback verified both
values and exact preservation of all six pre-existing production values. The
new non-secret variables use the bulk editor's default build/runtime scopes.
DB URL targets db.dhjnrnhjghsulbevfhno.supabase.co and has a pooler host configured.
No deployment or hook change has been made yet. Coolify access is no longer a
blocker; the authenticated Chrome tab is retained.

Main advanced to 74a57514 (PR #7, CI async hardening and merge_group trigger).
Merged it into this candidate without conflicts. Re-run CI before rollout.
The user explicitly identified this hosted app as staging with no real users,
so final browser verification can run on the staged deployment without touching
the unrelated local sandbox. Complete the controlled rollout and user journey
before claiming the goal is achieved.

Browser QA launcher currently reports the Commons sandbox stopped. A separate
`dummi-dice` Supabase stack occupies 54321/54322. Do not stop/reset it or change
its project identity. An ownership question is pending with the user about using
that synthetic sandbox for QA. No browser verification has been claimed.
