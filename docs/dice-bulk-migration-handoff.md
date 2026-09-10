# Dice bulk migration — 2026-09-10

## Delivered scope

Bulk import from integrated old Dice revision
`335cdff294ae921d0b4b2c66131c7194ce9190ed` (old main plus referee attribution)
onto Commons `83c9bafe2759cef0728a1446245fe2e46bead56c`. Includes live referee
outcomes, retries/diagnostics, canonical and duo ratings, recorded statistics,
placement/streak pages, feature gating, maintenance jobs, synthetic seed and
verification recipes. Commons home, shared routing, lazy chunks and deployment
conventions remain intact. See the earlier assessment and blob inventory for scope.

The user confirmed staging has no real users and authorized one bulk migration.
The old repository, deployment and hosted source were not modified. Application
code requires review and deployment; it is not yet running at cozycommons.dev.

## Hosted reconciliation completed

Source `yllwleldhtjyqjgdfrpn`; destination `dhjnrnhjghsulbevfhno`.

- All 17 Dice tables already contained the source records. Final per-record
  JSON comparison reconciles every table after two declared transformations:
  the existing one-account UUID mapping and verified Storage origin changes.
  No duplicate import or auth-schema replacement was needed.
- Counts: 20 profiles, 54 games, 214 game players, 20 comments, 1 tournament,
  13 enrollments, 1 feature flag, 5 live matches, 5 referees, 71 commands,
  72 events, 60 metrics, 17 rating receipts. Repair queue and all three virtual
  tables are empty. Source-only non-Dice auth accounts were not imported.
- Completed the existing identity mapping in one recorded-stats player key,
  three live projection player keys and 35 receipt projection player keys.
  Conflicting keys were rejected. Scores, events, command IDs, fingerprints
  and unrelated row fields were preserved.
- Copied and SHA-256/readback verified all 98 Storage objects (227,606,101 bytes):
  42 profile photos and 56 comment photos, including originals and compressed
  variants. The resumable copier refuses different content at an existing path.
  Updated 10 avatar URLs and 14 comment URLs after object verification; no old
  Storage origin remains in these fields. External avatar URLs remain intact.
- Nine checked-in Dice/sandbox assets already matched source bytes. Imported
  the expanded synthetic seed; hosted data was never used as local fixtures.
- Target ledger claimed Dice 0078 while actual schema was stale. Forward 0079
  reconciled functions/ACLs, three triggers, constraints/defaults, duo policies
  and indexes. Commons 0008 was applied in the same successful transaction.
  Before/after hashes proved all Dice and Commons rows unchanged by schema
  repair. Earlier failed transactions rolled back completely.
- Historical SQL, including differing target 0045/0064 variants, is unchanged.
  Unknown historical checksums remain NULL. Applied 0079 and Commons 0008 have
  file checksums; never edit these applied files.

Private object manifests/digests and pre-repair schema metadata remain outside
Git in `~/.cache/cc-dice-migration/`. No keys or hosted row exports are committed.
This is audit evidence, not a full backup. A hosted restore was not rehearsed;
the unchanged old source and all its assets remain available.

## Verification

- 395 backend tests passed, zero skipped, using owned PostgreSQL 17 and real
  PostgREST. Missing database configuration or skipped Dice tests fails CI.
- 287 frontend tests passed; lint, bundle checks and both container builds
  passed. Changed shell scripts pass ShellCheck at warning severity; shell
  entry points parse with Bash 3.2. Both migration ownership checks passed.
- Real database checks cover fresh install, rerun, populated drift repair,
  checksum corruption and ledger gaps. Service-role readiness passes; anonymous
  invocation is denied. No mocked migration execution remains.
- Built mobile frontend at 390×844: Home → ELO leaderboard → synthetic player
  profile displayed provisional 1523, one game and +23 last match. Evidence:
  `.dice-verification/20260910T0515Z/bulk-migration/` (ignored). Chrome failed
  Vite dev-module loading; built preview passed. Hosted auth/upload/live-command
  smoke tests remain deployment checks.
- The pre-existing shared Supabase sandbox was not reset, stopped or used.

## Next release step

1. Review the bulk PR and require green CI. Set Coolify backend pre-deploy to
   `bash apply-shared-migrations.sh` with the explicit staging project guard.
   See [deployment.md](deployment.md) for environment and command details.
2. Deploy backend first; require `/ready` to pass both actual schema contracts.
   Deploy frontend with staging origins; confirm Auth redirects/providers and CORS.
3. Configure serialized `python -m dice_maintenance` and run
   `python -m dice_maintenance --rebuild` once. Jobs are ported; Coolify scheduling
   was not configured during this migration.
4. Verify sign-in/logout, one synthetic image upload/game, ratings, repair queue
   and Commons scene persistence. Record image digests. Reconcile any source
   changes since inventory before retiring the old writer.

Rollback means prior application images or a forward schema repair. After new
writes begin, preserve/reconcile the destination delta before switching back.
Do not delete the old project or replay historical SQL.
