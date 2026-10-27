# Floor Planner technical design

## Application

The React editor lives in `frontend/src/floor-planner/` and reuses the copied
editor geometry, apartment scene, canvas, and styling. `frontend/src/App.jsx`
mounts it under the existing Supabase auth provider. `CozyWabiLanding.jsx`
links to `/floor-planner`. The Vite proxy only forwards the feature's
`/api/floor-planner` requests through the local API proxy; sandbox host and
port guards remain in place. This copies source code and assets only: it does
not import dummi plan records or change the dummi project.

The library and editor use the shared Supabase session. The API validates the
access token with Supabase Auth and treats `email_confirmed_at` as the verified
email signal. On a request, the service claims matching pending invitations
for that verified address. An invitation therefore works for a person who
creates their account later. No mail provider or automatic delivery is
configured; the owner copies the plan URL and communicates it separately.

## Storage and authorization

The feature owns its migration family under
`backend/floor_planner/migrations/`, separate from retired Commons room
migrations. Migration `0001_floor_planner_documents.sql` creates
`floor_plan_documents`, `floor_plan_invitations`, and the readiness attestation.
The migration runner and `scripts/check-floor-planner-migration-contract.sh`
enforce the family and contract. Do not edit historical Commons migrations.

Browser roles receive column-scoped SELECT grants and RLS policies for public
plans, owners, and accepted invitees. Invitation rows expose only the minimum
columns needed for self-access checks; the email column and all writes are
unavailable to browser roles. The backend uses the service-role client after
checking the user and plan access. Owner-only metadata and invite operations
stay on the API. Plan responses set `Cache-Control: private, no-store`.

Scene updates go through the service-only `floor_planner_update_document`
function. The caller supplies the expected revision; the function rechecks
ownership or an active invitation and advances the revision atomically. A
stale revision returns a conflict, while a revoked editor is denied at save
time even if their browser has not polled yet. Scene payloads are size- and
shape-validated before storage so malformed geometry cannot break the shared
renderer.

## Sync and recovery

The editor saves after a short idle period and serializes in-flight saves.
Local recovery records are keyed by user ID and plan ID. Conflicts and failed
saves retain the draft; access failures disable editing without deleting it.
The editor polls the authorized plan endpoint every six seconds for revision
and access changes. It does not use Realtime channels or publish personal
presence data. Read-only pan and zoom remain in memory and are not saved.

## Validation

`backend/tests/test_floor_planner.py` covers scene and input validation. The
opt-in `backend/tests/test_floor_planner_integration.py` runs against the
loopback Supabase stack and exercises verified-email invitations, private and
public RLS, browser-role grants, owner restrictions, revision conflicts,
revocation, and migration replay. Frontend tests cover retained editor behavior,
plan-specific drafts, and serialized autosave. Library and sharing flows were
also checked manually in the local browser.
