# Commons roles implementation

## Context

At main 9e21252, `backend/admin/routes.py` trusts `commons_admin` Auth metadata,
Dice and Fantasy use an email allowlist, Trips imports that allowlist, and hosted
Crowdset trusts `crowdset_admin`. Dice's browser duplicates the email list.
See PRODUCT.md for the approved replacement behavior.

## Changes

- Add a forward migration in the existing shared/Dice release family. Do not
  change historical migrations or the retired Commons room migration family.
- `public.commons_user_roles` links Auth UUIDs to member/admin, with actor and
  update time. Missing rows mean member. RLS permits authenticated users to read
  only their own role; only the trusted service can write. History is server-only.
- A server-only role lookup RPC joins verified, non-anonymous Auth users and is
  uncached, including when used through Dice's cached Supabase wrapper.
- Server-only directory and history operations expose bounded account fields.
  Role mutation RPC serializes all changes with a transaction advisory lock,
  rechecks the acting admin under that lock, checks the expected old role and
  verified target, and enforces at least one remaining verified admin. The role
  write and audit insert commit together. Functions use invoker privileges and
  revoke the default PUBLIC execution grant.
- Seed verified legacy email/metadata admins once with migration audit records.
  No runtime email or metadata fallback. Future recovery uses a trusted database
  operation documented in README.md.
- `/admin/users` lists/searches accounts, `/admin/users/{id}/role` changes roles,
  and `/admin/role-history` returns recent audit entries. All use live Auth plus
  the Commons role check. Responses are private and uncached.
- Dice auth reads roles through the uncached RPC; `/dice/me` exposes `is_admin`
  for the browser. Trips shares that lookup. Crowdset uses its verified bearer
  token and public key to read its own role through the RLS-protected table;
  it needs no new secret or deployment environment variable.
- Reuse the admin layout with Analytics/Users navigation, account search, paging,
  explicit role-change confirmation, and recent history. Clear privileged UI
  after session changes and denied requests.

## Validation

API tests cover signed-out/member/unverified denial, live role revocation,
validation and safe error handling. Real loopback PostgreSQL tests cover RLS,
service-only RPC grants, migration seeding, audit atomicity, stale edits, and
concurrent last-admin demotions. Frontend tests cover account search, explicit
confirmation, cancellation, stale edit errors, and access loss. Existing Dice,
Trips, Fantasy, and Crowdset tests cover shared authorization. Build/lint and a
synthetic browser journey verify layout and the promotion/revocation flow.
