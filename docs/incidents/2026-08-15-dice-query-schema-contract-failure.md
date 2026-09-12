# Incident: Dice query and schema contracts — 2026-08-15

## Impact

Shared official-game reads returned HTTP 400 in production, affecting history,
recent games, profiles, head-to-head, and individual games. The feature-access
path also found production claiming migration `0042` without the expected
`dice_feature_access` table. Exact duration and request count are unknown.

## Root cause

The repository used `not.is.reopened`, but PostgREST's `is` operator does not
accept `reopened`. Our in-memory Supabase fake accepted it, and a source-string
test required it, so tests certified our fake rather than the production wire
contract. Separately, migration bootstrap treated a recorded baseline number as
proof that its schema objects existed. Clean local databases could not expose
that production drift.

This repeated the PostgREST/NULL testing weakness documented in the
[2026-08-08 incident](2026-08-08-dice-tournament-detail-outage.md); prose had not
been converted into a real-client regression test.

## Evidence and fix

- [Invalid filter](https://github.com/jasonkeung/dummi/blob/b5d9ae1ee673e27c643575f9508555a56b965447/backend/dice/repository.py#L57-L58)
- [Correct explicit NULL/official filter](https://github.com/jasonkeung/dummi/commit/8757726ba45abe64c132cff35c8a89ea523bdd41#diff-1196400cae3ef14b8dda5e980384b1649911997caa6cd7f1b1c44b804b5fd71c)
- [Production schema reconciliation, PR #213](https://github.com/jasonkeung/dummi/pull/213)
- [Real PostgREST serialization regression, PR #214](https://github.com/jasonkeung/dummi/pull/214)

## Generalizable lesson

Fakes test domain behavior, not external query syntax. Nontrivial PostgREST
filters need a real-client serialization test, and a migration number is not
proof that required schema objects exist.
