# Dice production migration gate

Backend code and database schema are deployed in separate systems. A backend
deploy must never start querying a column that has not already been applied to
the hosted Supabase database.

The checked-in `backend/migrations/PRODUCTION_SCHEMA_VERSION` identifies the
historical baseline. Existing databases must have reconciled migration receipts;
the runner never creates a baseline receipt from the existence of one table.
The incoming backend image runs `python -m release`, applying both Dice and
Commons migrations before starting HTTP. Each migration and its history record
are committed in one transaction. A database advisory lock serializes releases,
and both families' histories are checked before pending migrations are applied.

The release reads `SUPABASE_DB_URL` from the backend's Coolify environment.
It accepts either a pooler URL or a Supabase Direct URL. Because GitHub-hosted
runners do not have an IPv6 route to Supabase Direct hosts, the workflow converts
a Direct URL to its configured IPv4-capable session pooler host. Hosted targets
also require a matching `EXPECTED_SUPABASE_PROJECT`. See `deployment.md` for
the environment, health check, CI and maintenance configuration.

Required order for a schema change:

1. Add and locally verify the numbered migration and compatible application
   code.
2. Merge through the protected path to `main`; the incoming image's migrations
   must succeed before its backend can accept traffic. Verify Coolify's actual
   CI gating separately: this repository's CI does not trigger deployments.
3. Verify the API schema and the affected production workflow.

For additive non-null columns, include a safe default so existing rows remain
valid. Never bypass the gate. If a migration fails, use a forward repair
migration.
