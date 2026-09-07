# Dice deployment

Cozy Commons Dice is deployed from this monorepo as two Coolify applications:
one static frontend and one FastAPI backend. The existing
`jasonkeung.com/dice` deployment remains separate during migration.

## Coolify resources

Create both applications from the `cozycommons/cc` GitHub repository and the
`main` branch.

### Backend

- Build pack: `Dockerfile`
- Base directory: `/backend`
- Dockerfile location: `/Dockerfile`
- Exposed port: `8000`
- Health endpoint: `/health` (defined in the Dockerfile)

Runtime-only environment variables:

```dotenv
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_KEY=your-secret-or-service-role-key
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
- Base directory: `/frontend`
- Dockerfile location: `/Dockerfile`
- Exposed port: `80`

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

- Backend: `/backend/**`
- Frontend: `/frontend/**`

## GitHub Actions

The checked-in workflow runs frontend and backend tests. It does not deploy and
does not require production credentials. It also checks frontend lint, migration
family ownership, duplicate migration versions, and the migration runner's fresh
and existing-database behavior.

Configure `scripts/apply-dice-migrations.sh` as a protected, serialized Coolify
pre-deploy command for the backend. Give only that command `SUPABASE_DB_URL`;
runtime application secrets remain in Coolify. The command applies migrations
and verifies the checked-in schema contract before the new backend starts.

## Supabase provisioning

Before smoke testing the deployment:

1. Apply the checked-in Dice and analytics migrations to the new project using
   the production migration gate in `docs/dice-production-migration-gate.md`.
2. Create the `dice-profile-photos` and `dice-comment-photos` storage buckets
   and verify their policies.
3. Configure the frontend URL in Supabase Auth URL configuration and in any
   enabled OAuth provider.
4. Verify RLS before inviting real users or importing production data.

Production data migration, if desired, is a separate operation and must not use
production data as local fixtures.

## First-deployment checks

1. Open the backend `/health` endpoint and verify it returns `{"status":"ok"}`.
2. Open `/ready` and verify it returns `{"status":"ready"}`. Treat a `503` as
   a failed rollout: the process is alive, but Supabase or the required Dice
   schema is unavailable.
3. Open the frontend `/dice` route.
4. Verify authentication and logout.
5. Upload and display one synthetic profile or comment image.
6. Complete one synthetic game flow and confirm the leaderboard updates.
7. Review both Coolify resource logs before enabling automatic deployment.

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
