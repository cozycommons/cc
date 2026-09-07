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
ENABLE_SCHEDULER=false
```

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
does not require production credentials.

If production database migrations are later added to GitHub Actions, store only
the database connection string as the protected environment secret
`SUPABASE_DB_URL`. Runtime application secrets remain in Coolify.

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
2. Open the frontend `/dice` route.
3. Verify authentication and logout.
4. Upload and display one synthetic profile or comment image.
5. Complete one synthetic game flow and confirm the leaderboard updates.
6. Review both Coolify resource logs before enabling automatic deployment.
