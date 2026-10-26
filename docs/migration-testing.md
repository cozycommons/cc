# Migration testing

Migration SQL must execute against both a fresh database and representative
previous schemas before merge. Listing pending files does not prove an upgrade
will succeed. These checks use the same runner as the deployed release.

## Run locally

Start the existing local Supabase stack, fetch the base branch, and run:

```bash
git fetch origin main
scripts/test-migration-upgrades.sh
```

Use `BACKEND_VENV_DIR=/absolute/path/to/venv` for another prepared backend
environment. `MIGRATION_BASE_REF` selects a different previous Git release;
the default is `origin/main`. Its history must be available locally.
The command creates and drops only its own disposable databases beside the
exact loopback stack. It ignores ambient deployment database URLs and requires
the database tests to run. It does not reset the shared sandbox or load hosted data.

## CI coverage

The shared backend suite includes `test_migration_runner.py`,
`test_migration_upgrades.py`, and `test_migration_convergence.py`. CI fetches history and uses the PR base, merge-group
base, or push's previous commit as `MIGRATION_BASE_REF`. Unexpectedly skipped
migration tests fail the required backend gate.

The scenarios cover:

- Fresh install, retry without reapplication, corrupt checksums and history gaps.
- Previous Git release to candidate, preserving representative analytics rows.
- Adopted Dice baseline without old analytics tables or their receipts.
- Legacy analytics with and without context columns, preserving original values.
- Existing `0083` receipts from before prerequisite support.
- Prerequisite checksum changes/removal rejected before pending migrations run.
- Failure after prerequisite SQL rolling back its schema and receipt together.
- Readiness, service-role ingestion, and denial of browser-role table reads.
- Fresh/imported schema convergence, including exact function definitions,
  columns, constraints, indexes, views, policies, RLS, sequences, table/column/type/
  function/schema grants, and schema/global default privileges.
- Unreviewed structural or permission drift preventing history reconciliation.

`tests/migration_harness.py` provides `checkout_release`, `MigrationDatabase`,
and the `migration_database` fixture. Add an upgrade case by checking out a prior
release, applying it to that fixture, inserting synthetic rows or modeling a
known imported schema, running the candidate release, and asserting preservation
and intended changes. The fixed pre-analytics starting release prevents this
incident from disappearing when the PR base advances.

Tests that deliberately corrupt receipts or alter candidate SQL do so only in
their owned databases and temporary release trees. Historical repository SQL
remains unchanged. The existing container smoke test also checks release startup,
maintenance, readiness failure, and rejection of corrupted history.

## Further options

| Option | What it adds | Limits |
| --- | --- | --- |
| Synthetic upgrade scenarios (implemented) | Fast deterministic coverage of known starting states and representative rows; no hosted credentials | Cannot detect unknown hosted schema drift or realistic lock duration |
| Schema-only hosted rehearsal (recommended next) | Restore actual DDL and migration receipts into a disposable database, then run the candidate | Requires an explicitly authorized read-only export, reviewed/sanitized schema and role setup, and refresh discipline; synthetic rows are still needed for data-dependent failures |
| Hosted Supabase preview/staging environment | Exercises managed Auth, roles, extensions, API behavior, and deployment together | Extra environment setup/cost and credentials; must explicitly run our custom migration runner |

For a schema rehearsal, schema-only exports omit migration receipt rows, so
export those separately. Roles are cluster objects and require separate handling;
include required managed-schema dependencies without copying account data.
[PostgreSQL pg_dump reference](https://www.postgresql.org/docs/current/app-pgdump.html)
and [Supabase dump reference](https://supabase.com/docs/reference/cli/supabase-db-dump).

Supabase's `db push --dry-run` lists migrations without executing them, and uses
its own migration ledger. It would not catch this missing-table failure in our
runner. Running SQL and rolling back on the live database would still acquire
locks and execute statements; use a disposable rehearsal instead.
[Supabase CLI reference](https://supabase.com/docs/reference/cli/supabase-db-push).

Preview branches support a custom migration workflow after branch provisioning.
They can improve managed-service fidelity, but rebuilding from migrations alone
still needs adopted-schema scenarios to cover imports and drift.
[Supabase branch workflows](https://supabase.com/docs/guides/deployment/branching/working-with-branches).
