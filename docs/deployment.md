# Cozy Commons deployment

Cozy Commons is deployed from this monorepo as two Coolify applications: one
static frontend and one FastAPI backend. Dice remains available at `/dice`, but
the home page and its persistent scene state belong to Commons. The existing
`jasonkeung.com/dice` deployment remains separate during migration.

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

- Backend: `/backend/**`, `/shared/commons/scene-contract-v1.json`
- Frontend: `/frontend/**`, `/shared/commons/scene-contract-v1.json`

## GitHub Actions

The checked-in workflow runs frontend and backend tests. It does not deploy and
does not require production credentials. It also checks frontend lint, both
container builds, migration family ownership, duplicate migration versions, and
the migration runners' fresh and existing-database behavior.

The incoming backend image runs both migration families before starting HTTP:

```bash
python -m release
```

Keep this Docker command in Coolify. Remove any old Commons-only migration hook:
it cannot replace running the incoming image's SQL. The runner uses a database
advisory lock, verifies recorded checksums and schema contracts, and exits before
HTTP starts on failure. Both Dice and Commons migrations now belong to this
release. The backend needs the database URL at runtime; keep it in Coolify's
secret configuration. `EXPECTED_SUPABASE_PROJECT` must match the intended hosted
database, preventing an accidental deployment against another project.

CI exercises fresh PostgreSQL and PostgREST, requires the database tests to run,
starts the built release image, runs maintenance, checks readiness failure when
the database API is unavailable, and rejects a release with a corrupted migration
receipt. CI does not itself trigger Coolify. Verify the actual auto-deploy trigger
and required-check gating in Coolify before enabling it; a push webhook alone
does not establish that tests passed.

GitHub's [Required Commons CI ruleset](https://github.com/cozycommons/cc/rules/23201531)
is active on `main`. It requires the GitHub Actions `frontend` and `backend`
checks against an up-to-date branch, with no bypass actors. The older disabled
`main protection` ruleset remains unchanged. Keep these check names aligned with
the workflow when changing CI.

## Supabase provisioning

Before smoke testing the deployment:

1. Let the incoming backend apply both checked-in migration families. For an
   existing database, reconcile its real schema and migration ledger first;
   never fabricate baseline receipts or replay historical SQL blindly.
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
   a failed rollout: the process is alive, but Supabase or the required Dice
   schema is unavailable.
3. Open the frontend `/healthz` endpoint and `/dice` route.
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
