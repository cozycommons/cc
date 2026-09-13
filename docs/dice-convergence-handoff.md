# Dice convergence handoff

## Released September 13, 2026

Dice now lives in Cozy Commons at https://cozycommons.dev/dice.
PR #5 merged as `36b9472669fd0527015c3809c43b1a739d969bb7`.
Main CI run 34782070480 passed. Candidate CI passed 410 backend tests with
zero skips and 338 frontend tests, including real PostgreSQL/PostgREST,
incoming-image migration, maintenance, readiness failure and container smoke checks.
PR #1 is closed as superseded; its branch and the retired Dummi source remain
recovery material. Do not import the old candidate wholesale or replay the data copy.

## Deployment and maintenance

Coolify: https://admin.cozycommons.dev/, Root Team.
Project `myslnzrcuucdffkthj0tswam`, environment `gudimtlnyhv3mrz7bqcjkifg`.
The environment is named production; the user explicitly identifies it as staging
with no real users.

- Backend `ira6t1lrdcckadpn2jf1brdg`: deployment `qmhz6uxoa42ci6npii0x3zfj`
  succeeded at the merge commit. Root context, `/backend/Dockerfile`, port 8000.
  Incoming release applies both migration families before HTTP. Docker `/ready`
  passed; public `/health` and `/ready` returned 200.
- Frontend `rrmtxvricbf8ifbldflw2brb`: deployment `rtcnre5jrtfapjfhnnmo8ext`
  succeeded at the same commit. Root context, `/frontend/Dockerfile`, port 80.
  Watch paths include `frontend/**` and `shared/commons/scene-contract-v1.json`.
- Both resources were restored to **Deploy on push (webhooks)** after the controlled
  rollout; each setting was reloaded and verified. GitHub App `coolify-cc` targets main.
- GitHub ruleset 23201531 requires frontend/backend CI with strict freshness and
  no bypass actors. The previous disabled ruleset remains untouched.
- Old pre-deploy migration command removed. Post-deploy command is
  `python -m dice_maintenance --rebuild`. Actual deployment logs reported
  **Canonical games reconciled: 52; Pending live repairs processed: 0**.
- Enabled scheduled task `kcjwptv0vovrqgmjfwg6o3wr`, Dice rating repairs, runs
  every minute with timeout 300 seconds:
  `flock -n -E 0 /tmp/dice-maintenance.lock python -m dice_maintenance`.
  Automatic executions at 20:56 and 20:57 UTC succeeded; inspected output was
  **Pending live repairs processed: 0**.
- Runtime EXPECTED_SUPABASE_PROJECT is `dhjnrnhjghsulbevfhno`; SITE_URL is
  `https://cozycommons.dev`. Existing six environment values were preserved.
  Credentials remain in Coolify. No additional MCP/token was needed.

## Data and identity reconciliation

All 17 Dice tables reconciled against the source before release, accounting for
one existing account UUID mapping and Storage origin rewrites. The earlier copy
hash-verified all 98 objects (227,606,101 bytes), including originals, compressed
images and avatars. Nine checked-in sandbox assets match the pre-retirement source.
Target schema now records Dice 0080 and Commons 0012; applied migration 0079 was
preserved byte-for-byte. No historical migration was rewritten by this task.

Live Google login exposed NULL token fields on 19 imported accounts. The
[documented targeted normalization](dice-imported-auth-repair.md) repaired all 19,
with SQL confirming every other account field unchanged. A separate read returned
zero affected accounts. Real Google login then returned the existing Matt profile.
The read-only Supabase connector could audit but could not apply the repair;
it ran through the backend's existing database connection in Coolify Terminal.

Final counts: 20 profiles, 55 games, 218 game-player rows and 98 Storage objects.
The increase from 54/214 is exactly one unranked staging verification game with
four players: live match `76d065ec-91bb-46ce-b1e2-666cabbad05a`. It was completed
at 0-0, termination other, complete observed coverage. Preserve it as QA evidence;
do not mistake it for a source reconciliation discrepancy.

## Browser verification and continuing work

Real deployed UI verified login/profile continuity, dead table hit versus named
catch, point and append-only correction back to 0-0, FIFA thrower/kicker/saver,
per-player credits, and completed-game stats. The 320px page has no horizontal
overflow. Migrated gallery thumbnails and display images loaded from target
Storage, with the lightbox linking the original object. Local evidence lives under
`.dice-verification/20260913-release/`; it is intentionally ignored by Git.

Enhancements now ship in Commons. Use `.agents/skills/verify-dice/` and
`docs/dice-feature-map.md` for future work, on fresh branches from Commons main.
Keep `/dice`, current Commons scenes/shared contracts, incoming-release migrations
and the database CI checks. The separate local `supabase_*_dummi-dice` stack was
never reset or stopped. No access dependency remains for this release.
