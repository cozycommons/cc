# Dice production migration gate

Backend code and database schema are deployed in separate systems. A backend
deploy must never start querying a column that has not already been applied to
the hosted Supabase database.

The checked-in `backend/migrations/PRODUCTION_SCHEMA_VERSION` is the baseline
used only when adopting an existing database that already has the foundational
Dice schema. A fresh database replays every owned Dice and analytics migration;
it is never stamped at the baseline without creating that schema first. Each
migration and its history record are committed in one database transaction.

The repository's GitHub Actions workflow validates migration ownership and the
runner, but deliberately does not connect to production or deploy. Run
`scripts/apply-dice-migrations.sh` as a protected pre-deploy command in the
deployment platform before releasing backend code. Serialize backend deploys so
two migration runs cannot overlap.

The protected pre-deploy command reads `SUPABASE_DB_URL` from its deployment
environment.
It accepts either a pooler URL or a Supabase Direct URL. Environments without an
IPv6 route to Supabase Direct hosts can provide `SUPABASE_DB_POOLER_HOST`; the
runner then converts the Direct URL to that IPv4-capable session pooler host.
Non-Supabase and already-pooled URLs are left unchanged.

Required order for a schema change:

1. Add and locally verify the numbered migration and compatible application
   code.
2. Merge through the protected path to `main`; the protected pre-deploy command
   must succeed before the backend image can deploy.
3. Verify the API schema and the affected production workflow.

For additive non-null columns, include a safe default so existing rows remain
valid. Never bypass the gate. If a migration fails, use a forward repair
migration.
