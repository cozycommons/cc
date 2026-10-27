# Cozy Commons deployment

Cozy Commons has a shared static frontend and FastAPI backend deployed from this
monorepo, plus separate services where projects need them. The Coolify resource
instructions below cover the shared pair; Crowdset's separate application is
documented in [its deployment instructions](crowdset/README.md#hosted-test-configuration).
Dice remains available at `/dice`. The existing `jasonkeung.com/dice` deployment
remains separate during migration.

## Project placement policy

New projects use the shared frontend and API unless their workload, state,
dependencies or release needs justify a separate runtime. Background work can
be separated independently. Creating a separate service should follow a standard,
repeatable workflow.

This is the default for future project decisions, not a migration plan for
existing deployments. In particular, it does not require consolidating Crowdset
or changing its current routing, frontend packaging, storage or worker setup.

### Choosing a runtime

| Project needs | Default placement |
| --- | --- |
| Pages and ordinary database/API operations | Shared React frontend and FastAPI API |
| Slow or intensive background jobs | Shared frontend/API with a separate worker |
| Incompatible or substantial dependencies, persistent local state with exclusive ownership, special hardware, or a different process lifecycle | Separate the runtime that needs those properties |
| Independent releases because shared deployments cause actual disruption | Consider extracting the affected API or worker |

Project count alone is not a reason to split services. Keep project routes,
modules, data ownership and tests distinct even when they share a process. Reuse
common authentication and infrastructure without making unrelated projects
depend on each other's implementation. Frontend, API and worker placement are
independent: a separate worker or API does not require a separate frontend build.

Shared services minimize setup and ongoing maintenance, but share dependencies,
startup and releases. Separate services allow independent deployments, rollback
and resource limits, at the cost of more configuration, monitoring, backups and
dependency maintenance. Containers on the same VM still share host availability
and capacity. Record the concrete reason for a split and these tradeoffs in the
project's existing technical or operational docs.

### Keeping separate services easy to operate

When a separate runtime is warranted, reuse existing deployment patterns and
automate repeated setup. The target workflow should provide:

- A standard service template for startup, health checks, logs, resource limits
  and graceful shutdown.
- A small checked-in deployment definition describing routing, port, build file,
  required secret names and persistent storage. Secret values stay outside Git.
- A repeatable provisioning workflow that applies those settings to Coolify.
- Deployment selection based on each service's code and shared dependencies, so
  shared changes deploy the affected services without deploying unrelated ones.
- Clear responsibility for backups, dependency updates and deployment failures.

These are requirements for future deployment tooling, not a claim that a unified
provisioning workflow already exists. Avoid a new bespoke setup for every project,
but do not keep an unsuitable workload in the shared API solely to avoid resource
creation. Provisioning, consolidation and deployment changes remain separate
implementation work within an explicitly scoped task.

## Coolify resources

Create both applications from the `cozycommons/cc` GitHub repository and the
`main` branch.

### Backend

- Build pack: `Dockerfile`
- Base directory: `/`
- Dockerfile location: `/backend/Dockerfile`
- Exposed port: `8000`
- Health endpoint: `/ready` (defined in the Dockerfile); `/health` is liveness only
- Startup command: keep the image default, `python -m release`

Runtime-only environment variables:

```dotenv
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_KEY=your-secret-or-service-role-key
SUPABASE_DB_URL=postgresql://postgres.your-project-ref:your-db-password@your-session-pooler.supabase.com:5432/postgres?sslmode=require
EXPECTED_SUPABASE_PROJECT=your-project-ref
# Only needed when SUPABASE_DB_URL uses db.your-project-ref.supabase.co:5432.
SUPABASE_DB_POOLER_HOST=your-session-pooler.supabase.com
CORS_EXTRA_ORIGINS=https://your-frontend-hostname
SITE_URL=https://your-frontend-hostname
ENABLE_SCHEDULER=false
READINESS_TIMEOUT_SECONDS=2
```

`SITE_URL` is the public origin for Cozy Commons, without an app path or
trailing slash. The backend appends `/dice` when it creates links to Dice
pages, allowing the same origin setting to be reused by other projects.

`SUPABASE_SERVICE_KEY` is privileged. Store it only in the backend resource;
never add it to the repository, frontend resource, or frontend build.

### Frontend

- Build pack: `Dockerfile`
- Base directory: `/`
- Dockerfile location: `/frontend/Dockerfile`
- Exposed port: `80`
- Health endpoint: `/healthz` (defined in the Dockerfile)

Build-time environment variables:

```dotenv
PORT=80
VITE_API_URL=https://your-backend-hostname
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_ANON_KEY=your-publishable-key
```

The publishable/anon key is intentionally browser-visible. Supabase row-level
security remains the authorization boundary. Do not substitute a secret or
service-role key.

Deploy the backend first. Use its generated HTTPS hostname for `VITE_API_URL`,
then deploy the frontend. Finally, put the frontend's exact origin (without a
trailing slash) in `CORS_EXTRA_ORIGINS` and redeploy the backend.

Keep automatic deployments disabled until the first manual deployment and
smoke test succeed. When enabled, use Coolify watch paths so frontend-only
changes do not rebuild the backend and vice versa:

- Backend: `backend/**`, `.dockerignore`
- Frontend: `frontend/**`, `design/**`

## GitHub Actions

The checked-in workflow runs frontend and backend tests. It does not deploy and
does not require production credentials. It also checks frontend lint, both
container builds, migration family ownership, duplicate migration versions, and
the migration runners' fresh and existing-database behavior.

The incoming backend image runs the Dice, Commons, Beli, and Trips migration
families before starting HTTP. The retired Commons room migration family remains
for compatibility with historical Dice readiness checks; the room API and assets
are no longer shipped:

```bash
python -m release
```

Keep this Docker command in Coolify. Remove any old Commons-only migration hook:
it cannot replace running the incoming image's SQL. The runner uses a database
advisory lock, verifies recorded checksums and schema contracts, and exits before
HTTP starts on failure. All four migration families belong to this
release. The backend needs the database URL at runtime; keep it in Coolify's
secret configuration. `EXPECTED_SUPABASE_PROJECT` must match the intended hosted
database, preventing an accidental deployment against another project.

CI exercises fresh PostgreSQL and PostgREST, requires the database tests to run,
starts the built release image, runs maintenance, checks readiness failure when
the database API is unavailable, and rejects a release with a corrupted migration
receipt. A separate `trips` job requires real Supabase Auth/API integration tests,
and the frontend container checks `/trips` and its deep links. Trips migrations
live under `backend/trips/migrations/`; its schema marker and readiness function
must advance together when the schema contract changes. `/ready` checks both
the existing Dice/Commons attestation and the Trips attestation.

CI does not itself trigger Coolify. Verify the actual auto-deploy trigger
and required-check gating in Coolify before enabling it; a push webhook alone
does not establish that tests passed.

Read-only inspection on 2026-10-23 confirmed both existing applications use
`cozycommons/cc`, branch `main`, commit `HEAD`, source `coolify-cc`, and **Deploy on
push (webhooks)**. Their saved watch paths match the lists above and cover the
Trips frontend/backend changes. The backend retains an empty pre-deploy command
and `python -m dice_maintenance --rebuild` after deployment. No hosting setting
was changed. The gate is GitHub's required PR checks before updating `main`;
Coolify itself is configured to react to the resulting push, not wait on a CI
workflow. PR #85 subsequently deployed through those webhooks on 2026-10-23;
real Google/Trips smoke tests passed. See `cozy-trips-tests.md` for the evidence.

The SPA document must send `Cache-Control: no-cache`, including route fallbacks
and conditional 304 responses. Otherwise browser heuristic freshness can retain
old shelf navigation and bundle references across a deployment. CI checks that
header on Commons, Dice and Trips document/deep-link routes. Content-hashed Vite
scripts, styles, fonts and images under `/assets/` send
`Cache-Control: public, max-age=31536000, immutable`; HTML, manifests and unhashed
files revalidate. Missing hashes return 404 rather than the SPA document. A failed
lazy chunk import triggers at most one full reload per build, guarded in
`sessionStorage`; a persistent failure shows an error instead of looping.
The stock nginx image supports
gzip (level 6 for scripts and styles), but has no Brotli module.

The initial Trips release used commit
`efbaf35c91e61f59bba1f6777d16370ccc199c4f` for both resources:

- Backend deployment `dti4jw82cqqa8lhb52bov4o0`, running image identity
  `sha256:daf2ba7296d034c7b5122083a0f96db7fd27e9565bd5789f6d05e851f0776dd0`.
- Frontend deployment `acup61c55ypmn2sroc9nmzys`, running image identity
  `sha256:2cdb394d0bae63d27b70ead89e91f436e3181eb3c6673ed471013adc7e7a127b`.

Both running containers were inspected as healthy. The preceding `e3c511d`
images were retained for rollback before the merge. Backend post-deploy
maintenance ran through the existing hook.

PR #86's document-cache fix merged as
`05854ed78b4da1378589c9f10e4e332afe03cb27` after all five PR checks passed. The
existing frontend webhook completed deployment `muw2mnu9zagssclfhq04n5z2`;
running image identity
`sha256:d9c2cfbb699b8ea8a9777738fb82cc8b407d47cc5f5ff98a213a95a9fad5ff14`
was inspected as healthy. The backend remains on the healthy `efbaf35` image
above; its code/schema did not change. Hosted HEAD 200 and ETag 304 responses
send `Cache-Control: no-cache` on all six checked document routes. Health,
readiness, anonymous denial and normal Commons/Dice/Trips navigation passed.

The compact Trips UI in PR #87 merged as
`2494643121fddb3f2c9974539158c2d4b0eb1051` after all five PR checks passed. Existing
frontend webhook deployment `nzvxici8a1daozoeh1hymgxt` succeeded. Its running image
identity is
`sha256:eed90d2c861b493f11af3974838d894e9be9f096e1384396bfe7ece02a29c793`.
The frontend and unchanged `efbaf35` backend were inspected healthy; cache,
health/readiness, account/list and expense-view checks passed. This release has
no database schema change. The user separately requested synthetic-data cleanup;
only the privately backed-up empty hosted QA ledger was removed, with strict
whole-row matching and a before/after fingerprint check of the real source trip.

PR #88's reviewed Trips reliability/profile/branding changes merged as
`2679cc93749132bdd3d441370646b8aa92925fa8` after all five PR checks passed.
Both existing webhooks completed successfully, with healthy running images:

- Backend deployment `nqjtmcpu0pametu7whws1zdt`, image
  `sha256:0427e67e68155fc1fa16bb0b9d9f3334f6bb06572f1bca2273e6d59b5b22b1b0`.
- Frontend deployment `70t0go4gcp1l8r8ssyjbgkxv`, image
  `sha256:343a1618e7cec8dcc8ad18de1fedcdaf94dacd88377fc2283a6f2e8abacec9cb`.

Hosted Google session/profile, ledger, branding/dialog and cache checks passed;
health/readiness returned 200 and anonymous Trips reads returned 401. No schema
migration, source refresh or additional identity grant is part of this release.
The proposed existing-account links remain a separately confirmed data action.

GitHub's [Required Commons CI ruleset](https://github.com/cozycommons/cc/rules/23201531)
is active on `main`. It requires the GitHub Actions `frontend` and `backend`
checks against an up-to-date branch, with no bypass actors. The older disabled
`main protection` ruleset remains unchanged. Keep these check names aligned with
the workflow when changing CI.

CI selects work from the complete git diff: the PR's merge base to its head,
the before/after commits for a push, or the merge group's base/head. Renames
select both the old and new project's checks. Documentation-only changes run
only the lightweight selection checks and required-check gates.

| Changed files | Tests selected |
| --- | --- |
| `frontend/src/{dice,crowdset,trips,design}/` or matching `frontend/public/` assets | That frontend project's tests plus shared frontend tests |
| Shared frontend code, frontend dependencies/configuration, or `design/` | All frontend tests |
| `backend/{dice,commons,trips,espn,resy,partiful}/`, project test files, or project scripts | That backend project's tests plus shared migration, release, and health tests |
| `backend/ig_logger/` | Beli tests plus shared backend tests |
| `backend/crowdset/`, its requirements, or Crowdset scripts | Crowdset tests and container smoke check |
| `backend/compute/` or its requirements | Compute tests/container; runtime edits also run Crowdset compatibility checks |
| Shared backend code/dependencies, database scaffolding, or root npm dependencies | All shared-API backend projects and real Trips integration |
| CI workflow/selection code or unmapped infrastructure | Shared frontend/backend, Trips, compute, and container checks; no Crowdset media suite |

The Crowdset media suite runs only for Crowdset backend code/tests, its
requirements and runtime scripts, or shared compute runtime/dependency changes.
Workflow edits, generic scripts, and unknown infrastructure alone do not select
it. The container smoke check still runs for shared frontend changes. Media test
logs include the slowest 15 test phases for future performance work.
CI runs the media suite with two pytest workers and work-stealing scheduling.
BLAS/OpenMP thread pools are capped at one thread per worker, matching the media
worker's production limits. Worker crashes fail the run without an automatic
restart. The existing 16-GiB temporary-filesystem check remains in place.
The media job pulls a prebuilt Python 3.12/FFmpeg dependency image from
`ghcr.io/cozycommons/cc/crowdset-tests`. Its tag hashes the target architecture,
`.github/images/crowdset-tests.Dockerfile` and both requirement files. A changed
recipe or dependency file uses a new image; missing images (including forks
without package access) build locally. Tests always use the current checkout,
mounted read-only, and a writable temporary filesystem with the same 16-GiB
check. No application code, credentials, or fixtures are baked into the image.
The separate `Prebuild CI images` workflow publishes from `main` after image
input changes, then pulls the published image on a fresh runner and runs all
media tests. It can also be dispatched manually on `main` to refresh system
packages. Only that publisher has package write permission. The consumer uses
package read permission for same-repository events, with anonymous pulls for
fork PRs. The Python base image is pinned by digest; update that digest in the
Dockerfile when upgrading the base image. Trips retains its isolated Supabase
setup.
For local reproduction, run `bash scripts/crowdset-ci-image.sh prepare` followed
by `bash scripts/crowdset-ci-image.sh test` (Docker required; the CI image uses
`linux/amd64` by default). On Apple Silicon, export
`CROWDSET_CI_PLATFORM=linux/arm64` before both commands to build a native local
variant with a separate tag. Outside CI, the helper uses a temporary Docker
volume so Docker Desktop bind-mount locking behavior cannot affect spool tests;
the volume is removed afterward. CI continues to use `RUNNER_TEMP`.
The test-only dependencies are pinned in `backend/crowdset/tests/requirements.txt`;
install them alongside the Crowdset runtime requirements to reproduce the run.
The integration fixtures retain real 1080p rendering, multiwindow alignment,
publication, cache reuse, and restart assertions with shorter synthetic videos.
The dedicated codec, timing, short/long alignment, and recovery tests remain.
A serial Python 3.12 macOS comparison on 2026-10-27 kept all 275 cases passing
and reduced local suite time from 172.61s to 121.16s (29.8%); CI timing will vary.

Trips backend changes also run its real local Supabase integration job. Dice
migrations, routes, repositories, and schemas include Trips because it consumes
canonical Dice profile fields. Beli
migration-family changes cover Beli, ESPN, Resy, and Partiful together. Shared
frontend tests accompany every frontend selection; shared backend tests
accompany every backend selection. New project directories conservatively run
the full corresponding suite until assigned in `scripts/ci-selection.py`.

Frontend selections retain lint, bundle budgets, and both frontend container
builds: the shared frontend and Crowdset images both compile the complete Vite app.
Backend selections retain the shared API container and release checks because
the projects ship together. Trips and backend jobs run concurrently.

The required `frontend` and `backend` jobs are final gates. They accept a skipped
job only when selection explicitly excluded it, and fail on selection errors,
test failures, cancellation, or unexpected skips. The backend gate also enforces
selected Trips, Crowdset, and compute checks. Keep the workflow triggers unfiltered so
docs-only PRs still receive both required statuses. Superseded PR runs are
cancelled; pushes to `main` and merge-group runs are not cancelled by this policy.

Validate selection and gate behavior locally without services:

```bash
python3 -m unittest discover -s scripts -p test_ci_selection.py -v
```

## Supabase provisioning

Before smoke testing the deployment:

1. Let the incoming backend apply all checked-in migration families. For an
   existing database, reconcile its real schema and migration ledger first;
   never fabricate baseline receipts or replay historical SQL blindly.
   Every checked-in version requires its own receipt. Historical imports missing
   early Dice receipts must pass through the reconciliation release documented
   in `docs/migration-unification.md` before using the current runner.
2. Create the `dice-profile-photos` and `dice-comment-photos` storage buckets
   and verify their policies.
3. Configure the frontend URL in Supabase Auth URL configuration and in any
   enabled OAuth provider.
4. Verify RLS before inviting real users or importing production data.

Data migration is separate from release schema migration. The September 13
staging audit already reconciled all 17 Dice tables and 98 Storage objects after
the prior UUID and URL transformations. Do not repeat the bulk import. Preserve
originals, compressed images and source backups; use synthetic local fixtures.

## Post-deploy maintenance

Run the following once in the successfully deployed backend container, using
that resource's environment, and retain its exit status and output:

```bash
python -m dice_maintenance --rebuild
```

Configure one serialized scheduled task in Coolify to run
`python -m dice_maintenance` every minute. Avoid overlapping invocations and do
not enable another scheduler for the same job. Verify a successful scheduled
execution in Coolify after configuration; importing the rating modules does not
schedule them. Neither this schedule nor a hosted post-deploy run is confirmed
until deployment access is available.

## First-deployment checks

1. Open the backend `/health` endpoint and verify it returns `{"status":"ok"}`.
2. Open `/ready` and verify it returns `{"status":"ready"}`. Treat a `503` as
   a failed rollout: the process is alive, but Supabase or a required application
   schema is unavailable.
3. Open the frontend `/healthz` endpoint, `/dice`, `/trips`, and a Trips deep link.
4. Verify authentication and logout.
5. Upload and display one synthetic profile or comment image.
6. Complete one synthetic game flow and confirm the leaderboard updates.
7. Review both Coolify resource logs before enabling automatic deployment.

## VM startup, logs, and recovery

Keep Docker enabled at VM boot. Coolify, its proxy, and both applications need
Docker restart policies so they return after a reboot. Use Coolify's Start,
Stop, Restart, and Redeploy actions to control the applications remotely; do
not add separate systemd units that also start the same containers. After
changing boot or restart settings, verify them with a planned VM reboot.

Both application images write runtime output to Docker's standard streams. Set
bounded Docker log rotation on the VM to avoid filling its disk. Coolify's
Runtime Logs page shows the current containers' output; it is not durable
history across container replacement or VM loss. For retained logs, configure
a server-level Coolify log drain to an external destination, enable Drain Logs
on each application, restart them, and verify a new event at the destination.
Deployment/build logs remain in Coolify and are not included in the workload
log drain.

Back up the Coolify instance database on a schedule with retention limits and
an off-VM copy. Save `/data/coolify/source/.env` (especially `APP_KEY`) securely
outside the VM; the database backup alone cannot restore encrypted settings.
Coolify instance backups do not include application or hosted Supabase data.
Test a restore on a separate machine before relying on the backup for recovery.

After a reboot, confirm Coolify and the proxy are reachable, both application
containers are healthy, `/ready` returns 200, and `/healthz` returns 200 on the
frontend. A stopped application can be started from Coolify while the VM and
Coolify are reachable; a failed VM must first be recovered through OVH.

## Release and rollback

Record the deployed Git commit and immutable image digest for both resources on
each release. Keep the immediately previous images available so an application
rollback does not require rebuilding source.

Database migrations are forward-only. Write schema changes using an
expand-and-contract sequence: deploy additive schema first, keep the previous
application compatible with it, deploy the new application, and remove old
schema only in a later release. Before a destructive or high-volume migration,
verify the hosted Supabase project's backup or point-in-time recovery status.

If a rollout fails:

1. Stop further deployments and preserve the failing release logs.
2. If `/health` fails, roll back the affected application image.
3. If `/ready` fails, correct the database/configuration issue before routing
   traffic; do not mark the deployment healthy based on liveness alone.
4. Never reverse a production migration by editing migration history. Restore
   application compatibility or add a new forward migration.
5. Repeat the readiness and smoke checks before resuming automatic deployment.

### Venmo previews

Venmo previews persist only public display fields in migration
`0081_venmo_profiles.sql`. The release migration runner applies the `venmo`
family automatically. Outbound requests share a process bucket (default one per
second, burst five; `VENMO_REQUEST_RATE` / `VENMO_REQUEST_BURST`) and a ten-minute
breaker after five failures. Thumbnail signatures use `VENMO_PHOTO_SIGNING_KEY`
(or the backend service key); keep that key consistent across replicas. Run one API worker for a deployment-wide limit;
multiple workers each have their own bucket and breaker. Hits expire in about
24 hours and misses in about one hour, with 10% jitter. Durable previews serve
immediately while one background revalidation runs per handle. Thumbnail bytes
are authenticated, bounded, and privately cached for one day.

Friend obligations live alongside their host ledger and are saved in the same
compare-and-swap revision. Trips supplies its existing settle-up suggestions to
the generic Venmo obligation module; an explicit settle writes the existing
repayment command, and Undo removes that repayment. Opening links never settles.
