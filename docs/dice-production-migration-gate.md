# Dice production migration gate

Backend code and database schema are deployed in separate systems. A backend
deploy must never start querying a column that has not already been applied to
the hosted Supabase database.

The checked-in `backend/migrations/PRODUCTION_SCHEMA_VERSION` is the production
baseline used to initialize migration history. On a `main` push,
`deploy-backend.yml` applies each migration newer than that baseline before the
backend deploy. Each migration and its history record are committed in one
database transaction, and concurrent backend workflows are queued so migrations
cannot overlap.

The migration job reads `SUPABASE_DB_URL` from the repository Actions secrets.
It accepts either a pooler URL or a Supabase Direct URL. Because GitHub-hosted
runners do not have an IPv6 route to Supabase Direct hosts, the workflow converts
a Direct URL to its configured IPv4-capable session pooler host. Non-Supabase
and already-pooled URLs are left unchanged.

Required order for a schema change:

1. Add and locally verify the numbered migration and compatible application
   code.
2. Merge through the protected path to `main`; the production migration job
   must succeed before the backend image can deploy.
3. Verify the API schema and the affected production workflow.

For additive non-null columns, include a safe default so existing rows remain
valid. Never bypass the gate. If a migration fails, use a forward repair
migration.
