# Dice production migration gate

Backend code and database schema are deployed in separate systems. A backend
deploy must never start querying a column that has not already been applied to
the hosted Supabase database.

The checked-in `backend/migrations/PRODUCTION_SCHEMA_VERSION` identifies the
historical baseline. Existing databases must have reconciled migration receipts;
the runner never creates a baseline receipt from the existence of one table.
The incoming backend image runs `python -m release`, applying Dice, Commons,
Beli, Trips, and Venmo migrations before starting HTTP. Each migration and its
history record are committed in one transaction. A database advisory lock serializes releases,
and every family's history is checked before pending migrations are applied.

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

## Failed historical migration prerequisites

A later numbered migration cannot repair a dependency that prevents an earlier
migration from finishing. For this exceptional case, add a reviewed prerequisite
file at `prerequisites/<exact migration filename>` beside that family's migrations.
Do not edit the shipped migration or manufacture its receipt.

The runner executes a prerequisite only while its matching migration is pending,
inside the same transaction as the original SQL and receipt. Its separate
`prerequisite_checksum` is recorded with that receipt. Changes or removal after
application fail the cross-family history check. Old receipts with a null
prerequisite checksum remain valid and do not rerun setup.

The prerequisite for `0083_analytics_workspace.sql` prepares the legacy analytics
table and context columns that imported Dice baselines may lack. It preserves
existing rows and does not mark skipped historical migrations as applied.
Ordinary schema changes should still use a new numbered forward migration.

See [migration testing](migration-testing.md) for the automated upgrade rehearsals.
