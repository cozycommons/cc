# Incident: Dice tournament detail outage — 2026-08-08

## Impact

Tournament lists loaded, but opening a tournament showed “Tournament not
found.” The backend was returning HTTP 500; the frontend mislabeled every fetch
failure as a missing resource.

## Root cause

Backend code referenced live-result schema from migrations `0042`–`0045`, but
deployment did not apply or verify migrations before releasing the image.
Production therefore ran application code newer than its schema. In-memory
Supabase tests also failed to model PostgREST filtering and SQL NULL semantics,
and no smoke test exercised tournament detail.

## Evidence and fix

- Broken application deployment: `f4581a80`
- History-preserving recovery: `b185cd1`
- [Migration ordering and schema guidance](../dice-production-migration-gate.md)
- [Later recurrence and executable PostgREST guard](2026-08-15-dice-query-schema-contract-failure.md)

## Generalizable lesson

Application code must not receive production traffic until its required schema
and external query contracts are proven present. Error UIs must preserve the
difference between not-found and server failure.
