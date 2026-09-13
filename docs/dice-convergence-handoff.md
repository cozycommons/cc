# Dice convergence: active work

Goal: make Cozy Commons the sole working home for Dice, complete the release
and data reconciliation, and deliver the remaining referee/play-log enhancements.
The user authorized this long-running implementation on 2026-09-13.

## Starting evidence

- Commons baseline: `915c1411ac4f40d1a6d4203d1d7daf6781bcdeb5`.
- Earlier candidate: `79b03345520e40e20a9429af67d9d0c816337aec`, PR #1.
- Dummi main: `41fa1ef3`, including Dice retirement `7e78148f`.
- Commons' 86 Dice frontend files, 22 backend files, both rating job modules
  and nine checked-in asset files exactly match Dummi before retirement.
- September 13 read-only comparison reconciled all 17 hosted Dice tables
  after the existing single-account UUID mapping and Storage origin changes.
  Both projects have 98 Storage objects; target avatar/comment fields contain
  no old Storage URLs. Original and compressed objects were hash-verified during
  the September 10 copy. Do not run another blind bulk import.
- Target database records Dice 0079 and Commons 0012. Current main only carries
  Dice through 0078. Preserve applied 0079 bytes from the earlier candidate.
- Main CI: 372 backend tests passed, 29 skipped. One Commons scene frontend
  test failed because it checks loaded scene text after waiting for an image
  container which is present before scene data arrives.
- Old /dice URLs return 308 to the Commons Dice homepage; old Dice API returns
  404. Retirement was done upstream, not by this migration task.

## Decisions

Use current Commons main as the base. Preserve new Commons scenes and /scene,
shared contracts, root Docker build contexts, vendor chunks and runtime smoke
tests. Bring across only missing migration/verification tooling and the accepted
referee enhancements. Supersede PR #1 once a green replacement exists.

Do not edit or replay applied migrations. Main already changed historical
0045/0064 during its import; document and test both known histories rather than
silently reverting these files. Add forward readiness coverage for Commons 0012.

Release must run migrations from the incoming release before accepting traffic.
Coolify's ordinary pre-deploy hook runs in the existing container and is not a
sufficient mechanism. Container health currently checks /health; release needs
actual database readiness. Rating modules define run_job functions but no
invocation is wired into main. Establish a verified maintenance invocation.

## Immediate delivery and stopping point

Construct a focused candidate on this branch with database-backed CI, current
schema attestation, the integration fixes and referee enhancements. Verify on an
owned isolated environment; keep the shared Supabase stack untouched. Stop this
increment when the candidate is reviewed and green, then continue toward merge
and release under the active goal.

## Access dependency

Coolify dashboard URL, team access, active deployment settings and maintenance
schedules are still unknown. GitHub and Supabase access are available. Do all
independent implementation before requesting missing release access again.

No code or hosted state has changed in this new branch yet. Next: import the
missing tooling from the earlier candidate, preserving current main's build and
Commons changes, and add forward readiness coverage without changing 0079.
