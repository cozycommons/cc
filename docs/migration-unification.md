# Unified application schema and migration history

Production and fresh databases must converge to the same application-owned
schema and use one individually recorded migration history. Preserve application
rows, existing receipt timestamps and hashes, and shipped SQL files.

## Reconciliation release

Migration `0084_dice_schema_convergence.sql` normalizes the reviewed differences
between the hosted catalog and a fresh PostgreSQL 17 database:

- Telemetry check-constraint names and the referee foreign key's delete action.
- The telemetry match/time index, retained in both environments.
- Read-only browser grants for the six public Dice tables; backend writes remain
  governed by the existing service role and application authorization.
- Browser sequence privileges and default privileges inherited from older
  Supabase defaults. New tables require explicit browser grants.
- Explicit backend grants for the original Dice tables and analytics events,
  independent of Supabase's changing defaults; service-role access to migration
  ledgers is read-only.

The migration verifies a canonical catalog fingerprint before recording any
missing historical versions. Unexpected schema or privilege changes abort and
roll back reconciliation. Its five-second lock timeout avoids waiting behind
live traffic indefinitely. The foreign key is replaced and validated in the
same transaction; no application rows are rewritten or deleted.

Receipts distinguish `recorded_via` values:

| Value | Meaning |
| --- | --- |
| `executed` | This runner executed the file and recorded its source hash |
| `reconciled` | Migration 0084 verified the equivalent final schema; historical SQL was not replayed |
| `legacy` | Receipt predates explicit provenance; existing timestamp and hash are retained |

Reconciled entries include the source hash, reconciliation version and reason.
Their deferred reference to receipt 0084 commits atomically with that receipt.
Existing records are never relabeled as executed or assigned invented dates.

## One migration history

The runner uses the same per-file receipt check for every migration, regardless
of provenance. There is no numeric skip rule, history-gap exemption, or active
`PRODUCTION_SCHEMA_VERSION` configuration. Missing early receipts block startup
before any pending SQL runs. Historical Git releases remain usable as regression
starting points.

The reconciliation release is commit `d3e5b3b520ab52c31d5f4cd0977b2c28e13870b2`
([PR #153](https://github.com/cozycommons/cc/pull/153)). Run that release
once for an old imported database before using this runner. This ordering
prevents an unreconciled database from attempting old one-time
operations against current tables. An unreconciled import must pass through the
reconciliation release once. It must never receive fabricated execution records
or replay the old migration chain against existing data.

## Schema equality

`backend/schema_catalog_v1.sql` installs a session-local catalog reader. Migration
0084 and the test harness share this versioned format. It compares application
objects in `public` and `analytics`, including the non-Dice project tables and
their permissions in the full post-release comparison.

The comparison includes columns/defaults/collations, validated constraints,
indexes, enums, views, exact function definitions/security settings, triggers,
RLS/policies, table and column privileges, schema/function/type privileges,
default privileges, and sequence definitions/ownership. Integer sequence bounds
are represented as strings to preserve precision through JSON tools.

It excludes physical column order, object IDs, sequence counters, application
rows, ownership identities, role passwords/login configuration, extension
internals, managed Auth/Storage schemas, and event-trigger helper functions.
Supabase's RLS auto-enable event trigger remains intact. These environment
details are outside the application-schema parity claim.

Catalog v1's PostgreSQL deparser format is validated on PostgreSQL 17, matching
the hosted project and CI. PostgreSQL major upgrades need an explicit compatibility
rehearsal. Do not change this catalog format after migration 0084 ships; add a
new version when extending it.

## Verification

Run `scripts/test-migration-upgrades.sh`. The synthetic imported starting state
models the reviewed hosted catalog differences and missing receipts. Tests
compare its complete resulting catalog to a fresh database, preserve data and
receipt metadata, verify role access, reject unreviewed drift, and verify retries.
CI requires these database tests. Local resets also use the production release
runner before loading synthetic seed data.

After deployment, read the hosted catalog and migration receipts, compare them
with a disposable fresh database, and check public readiness. Only schema
metadata and migration receipts are needed; account and
application data are not exported.

Production verification on 2026-10-26 after PR #153 found zero differences
across 1,084 catalog entries. All 65 pre-existing receipts retained their values;
13 missing Dice entries were recorded as reconciled by 0084. Both health and
readiness passed before the numeric skip rule was removed.
