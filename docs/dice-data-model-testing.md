# Dice data-model testing contract

Use this contract for every Dice schema change. The goal is to prove that a
new database can be created and that an existing database can be upgraded
without losing or silently changing valid data.

## Safety boundary

All migration development and testing happens against the local Supabase stack.
The reset script rejects any API or database URL other than the expected
loopback endpoints. Do not bypass those checks, link this workflow to a hosted
project, or copy production user data into fixtures.

The local seed is synthetic. Add the smallest representative fixture needed to
exercise a new invariant; do not turn it into a production snapshot.

## Migration contract

1. Add a new, monotonically numbered migration named
   `backend/migrations/NNNN_dice_description.sql`.
2. Never edit or rename a migration that may already have run in production.
   Correct it with a later forward migration.
3. Keep `_dice_` in the filename. `scripts/reset-local-dice-db.sh` intentionally
   discovers only that explicit Dice migration family.
4. Keep collection, scoring, and other application rules out of a migration
   unless the database must enforce the invariant for every writer.
5. For destructive or irreversible operations, explain why they are necessary,
   what data is affected, and how a forward repair would work.

## Required verification

### 1. Fresh database

Run:

```bash
scripts/dice-dev.sh reset
```

This must apply the full Dice migration family, load the synthetic seed, and
finish without SQL errors. Verify that the seed still represents valid rows
under the new schema.

### 2. Incremental upgrade

Start from the base branch's local schema and insert representative existing
rows before applying only the new migration to the local database. Verify:

- existing primary keys and relationships remain intact;
- existing values are preserved or transformed exactly as documented;
- new non-null columns have a safe value for existing rows;
- defaults apply to newly inserted rows;
- constraints accept valid boundary cases and reject invalid ones;
- indexes and functions exist with the intended signatures;
- rerunning application reads does not require a clean reseed.

Migrations are not required to be rerunnable. They are required to succeed once
against the previous schema.

### 3. Authorization

Check new tables, views, functions, and storage paths using the least privileged
role that should access them:

- anonymous access only when the product explicitly requires it;
- authenticated access only for the intended operations;
- service-role access for backend operations;
- RLS policies that reject another user's unauthorized writes.

Do not treat a service-role-only test as evidence that browser-facing RLS is
correct.

### 4. Application behavior

Run focused backend tests for repositories and routes that consume the changed
shape. Run focused frontend tests when serialized API data changes. For a
user-visible workflow, perform one browser smoke test against the local stack
and reload once to prove persistence.

## Pull request evidence

Include:

- the migration's purpose and affected relations;
- fresh-reset result;
- incremental-upgrade scenario and preservation assertions;
- authorization roles tested;
- focused automated tests and browser check, when applicable;
- irreversible operations and forward-recovery plan, or state that there are
  none.

Production backup, rollout, and smoke-test procedures are deployment concerns
and must be reviewed separately. Passing this local contract does not authorize
running a migration against production.
