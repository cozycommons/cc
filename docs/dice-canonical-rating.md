# Canonical Dice Elo with rating deviation

Dice has one canonical rating system. The model version is written as the semantic version `1.1.0`; runtime and database APIs do not call it “v11” or maintain a second rating.

Release impact and the retired-formula comparison are recorded in
[`dice-rating-release-2026-09-01.md`](dice-rating-release-2026-09-01.md).
That file is immutable release history; retired-formula code is not part of the
runtime. A future formula change must ship as a dedicated, reviewed migration
with its own dated impact record and remove its temporary migration tooling
afterward.

## Maintenance principles

- Runtime code imports one canonical model-version constant. Duplicating the
  version string across writers and snapshots risks producing mixed state.
- Canonical profile RD and model version are database invariants, not API
  fallbacks. Missing state must fail visibly instead of being hidden by a
  serializer default.
- There is no rating activation flag, dirty marker, scheduled repair, backfill,
  or reconciliation loop. The database schema itself is canonical.
- Tied players display the same plain competition-rank number. For example,
  two leaders both display `1`; tie metadata remains available for accessible
  labels and consumers, without adding a noisy `T-` prefix.

Elo remains the long-term skill estimate. A rating difference maps to the usual expected-score probability. Rating deviation (RD) controls how quickly the estimate learns and gives the product a confidence signal without changing Elo’s meaning.

## Rating contract

- New players start at Elo 1500 and RD 350.
- RD is bounded to 50–350.
- Inactivity adds 50 RD per 30 days, capped at 350, immediately before the next ranked game.
- A ranked result retains 85% of current RD.
- The learning multiplier ranges from 0.75× at RD 50 to 1.50× at RD 350.
- Provisional players keep the established placement behavior without stacking uncertainty into an excessive swing.
- Score margin remains part of the Elo update, but one result cannot move a player by more than their effective K.
- Team Elo uses an arithmetic mean; team RD uses an RMS mean.
- Corrections replay the complete official history ordered by played time, creation time, and game id.
- Leaderboards use competition ranking: `1, 2, 2, 4`.

Persisted RD is the state immediately after a player’s last ranked game. A future “current confidence” display must inflate it to an explicit as-of time rather than presenting stored RD as real-time confidence.

## Persistence and transactions

Manual game create, update, and delete operations send a complete projected generation to the canonical database mutation RPC. That RPC locks the canonical generation, rechecks the source, applies the game mutation, verifies the expected post-mutation source, writes all player/profile rating state, and records an idempotency receipt in one transaction.

Live-result materialization is a separate durable transaction and is always
unranked. It atomically updates the official game, player rows, and ordinary
game/win/loss aggregates, so it cannot change Elo or RD. If ranked live games
are introduced later, they must use the canonical game-and-rating mutation
transaction instead of adding a repair loop. Live and manual mutations share
one advisory lock to prevent lock-order inversion, and live-materialized game
rows reject manual update or deletion.

New profiles are inserted with canonical defaults (Elo 1500, RD 350, zero
ranked games). Dropped responses from manual mutations are recovered through
their idempotency receipts; stale sources are replanned before another atomic
attempt. There is no normal production operation that requires replaying all
history after the schema migration is installed.

The cleanup migration requires the completed cutover generation to be active
and clean before it removes the old control row. Deploy it with game writes
paused; a dirty or inactive production state fails closed instead of discarding
repair evidence. Empty databases may install the canonical schema directly.

## Prediction boundary

The prediction model is independent of Elo. It may consume its own versioned features and evaluation datasets. Historical live matches retain their immutable rating snapshots, including older `1.0.0` labels; newly created rating snapshots are labeled `1.1.0`.

## Acceptance criteria

- The same ordered history produces byte-for-byte equivalent canonical state.
- Inactivity changes RD, never Elo by itself.
- Invalid or incomplete generations fail atomically.
- Anonymous and authenticated clients cannot execute rating mutation/operator RPCs.
- A concurrent manual source change cannot partially apply rating state.
- API responses expose only canonical Elo, RD, and canonical historical snapshots.
- The independent prediction pipeline remains operational.
