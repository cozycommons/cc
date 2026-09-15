# Dice feature map

This is the short product contract for Dice. It says what users can rely on,
what owns truth, and whether the behavior is shipped. Detailed event mechanics
remain in [the live-event contract](dice-live-event-contract.md).

Status:

- **Main** — merged to `main`.
- **Stack** — implemented in open PRs; not shipped from `main` yet.
- **Later** — agreed direction, not implemented.

Last reconciled: 2026-09-05 against `main` plus the current rich game-stats stack.

## Feature surfaces

| Feature | User contract | Status | Executable proof |
| --- | --- | --- | --- |
| Live referee access | Live referee, expanded home, Stats, and duo ratings are the only Dice experience. Registered profiles may use private live and duo routes; the retired preference API remains true-only for cached clients during its compatibility window. | Main | [`test_dice.py`](../backend/tests/test_dice.py), [`test_dice_live_api.py`](../backend/tests/test_dice_live_api.py) |
| Private sandbox | Synthetic Dice data is isolated from production. The same setup works locally and in a private Codespace; only the frontend is exposed. | Main | [Sandbox guide](dice-sandbox.md), [`test_dice_local_harness.py`](../backend/tests/test_dice_local_harness.py) |
| Live games | Ongoing games are first-class and discoverable. A registered player may create a 2v2 game, join or leave as referee, and open it directly. New games are ranked by default, with an explicit Ranked/Unranked segmented choice. The compact roster picker searches registered players by name and preserves throwing order. Creation includes the creator as referee atomically; repeating an unclear create returns the same game. | Main | [`LiveLobby.test.jsx`](../frontend/src/dice/pages/LiveLobby.test.jsx), [`test_dice_live_api.py`](../backend/tests/test_dice_live_api.py) |
| Referee scoring | Referee mode prioritizes one-handed entry. Common actions are Point, Table hit, FIFA, and Miss; rare outcomes stay under More. The server derives team and score. A compact play log names the thrower and preserves table-hit and FIFA attribution without exposing ledger mechanics. | Main | [`LiveGame.test.jsx`](../frontend/src/dice/pages/LiveGame.test.jsx), [`test_dice_live_service.py`](../backend/tests/test_dice_live_service.py) |
| Turn hint | Order is advisory, never a stored game fact. From effective observations, each team loosely takes two throws; the teammate opposite that team's last throw is suggested next. Selection remains overridable. A score checkpoint clears the hint until a referee establishes order again. | Main | [`liveTurnOrder.test.js`](../frontend/src/dice/liveTurnOrder.test.js) |
| Referee resync | Visible live games refresh about every two seconds. Returning to the foreground triggers an immediate canonical refresh; overlapping background refreshes coalesce. Mutation conflicts still require review and intentional resubmission. | Main | [`LiveGame.test.jsx`](../frontend/src/dice/pages/LiveGame.test.jsx) |
| Referee delivery recovery | A tapped result is retained per signed-in user and game until acknowledged. Reload, reconnect, or an unclear response retries the exact command; stale or conflicting commands require review before a new action. Ambiguous create and delete requests also reuse a payload-bound identity. | Main | [`liveCommandIntent.test.js`](../frontend/src/dice/liveCommandIntent.test.js), [`LiveGame.test.jsx`](../frontend/src/dice/pages/LiveGame.test.jsx), [`test_dice_live_store.py`](../backend/tests/test_dice_live_store.py) |
| FIFA | A FIFA is a goal, teammate catch, or saved goal. Receiving-team roles and the opposing saver are retained; a save awards no point and play continues. | Main | [Attribution contract](dice-live-event-contract.md#attribution), [`test_dice_live_contract.py`](../backend/tests/test_dice_live_contract.py) |
| Mistakes and disputes | Undo removes the referee's latest active observation. A correction replaces the whole throw in its original slot. A true retoss records a decision and a later physical replay. These are never interchangeable. A catch-up checkpoint remains authoritative over earlier throw corrections; change that official score with another catch-up. | Main | [Corrections](dice-live-event-contract.md#corrections), [Retosses](dice-live-event-contract.md#retosses), golden vectors |
| Missing play | A referee may catch up to a known score or finish with partial/unknown coverage. Missing throws never become synthetic misses or player statistics. | Main | [Coverage contract](dice-live-event-contract.md#coverage-and-missing-observations), golden vectors |
| Completion | Reaching the target makes the game ready, not automatically final. Finish is explicit. Off-roof is an attributed immediate 0–5 loss. Reopen/correct/refinish preserves one official result identity. Delete removes the live and official records atomically and exact retries are safe. Concurrent edits to an ordinary completed result reject stale saves, retain the editor's full intent, and require an explicit overwrite or discard. | Main | [Completion contract](dice-live-event-contract.md#completion-and-historical-validity), [`test_dice_virtual_lifecycle.py`](../backend/tests/test_dice_virtual_lifecycle.py), [`test_dice_live_api.py`](../backend/tests/test_dice_live_api.py), [`test_dice_rating_z_canonical_only.py`](../backend/tests/test_dice_rating_z_canonical_only.py), [`LogMatch.test.jsx`](../frontend/src/dice/pages/LogMatch.test.jsx) |
| Recorded statistics | Official score may diverge from recorded-play totals after checkpoints. Only active observed throws count; corrected, removed, and retossed originals do not. A non-scoring table hit may name its catcher or record that nobody caught it; only named catches credit a catcher. FIFA roles and self-sink blame remain distinct. Finalization stores one versioned projector snapshot on the official game; game lists, completed detail, and aggregate player Stats read it without recomputing. Partial coverage is always disclosed. A completed ranked result queues canonical rating repair until replay succeeds. | Main | [`test_dice_live_contract.py`](../backend/tests/test_dice_live_contract.py), [`PlayerGameStats.test.jsx`](../frontend/src/dice/components/PlayerGameStats.test.jsx), [`test_dice_live_rating_repair_job.py`](../backend/tests/test_dice_live_rating_repair_job.py) |
| Win probability | New matches capture a versioned independent prior-win-rate model; pre-migration matches retain their saved Elo prior. Score and saved rules produce a version-matched live estimate, including tied deuce checkpoints beyond the target; invalid estimates fall back to neutral. Probability never decides or mutates score. | Main | [`test_dice_live_probability.py`](../backend/tests/test_dice_live_probability.py), [`GamePulse.jsx`](../frontend/src/dice/pages/GamePulse.jsx) |
| Rating uncertainty | Rating deviation represents confidence alongside Elo. It makes new or recently inactive ratings more responsive without changing the meaning of Elo as a win-probability estimate; canonical replay owns both values. | Main | [`test_dice_rating_deviation.py`](../backend/tests/test_dice_rating_deviation.py), [`test_dice_rating_z_canonical_only.py`](../backend/tests/test_dice_rating_z_canonical_only.py) |
| Referee and Stats views | The live game opens on the fast Referee surface. Stats is one tap away; a compact odds bar keeps the game state visible without occupying scoring space. ELO is the searchable player directory and links into profiles; old `/dice/players` links redirect there. Individual win streaks use ranked, non-duo-only games; unranked games neither count nor interrupt them. | Stack | [`LiveGame.test.jsx`](../frontend/src/dice/pages/LiveGame.test.jsx), [`Home.test.jsx`](../frontend/src/dice/pages/Home.test.jsx), [`LeaderboardNavigation.test.jsx`](../frontend/src/dice/pages/LeaderboardNavigation.test.jsx) |
| Duo ratings | Completed ranked 2v2 games replay into exact unordered pairs with separate Elo/deviation state. Three games place a duo and qualify it for the homepage. Pairs with one or two games have a visible provisional ELO but no rank. Placed duos rank by displayed Elo, equal Elo values share a rank, and every detail/streak aggregate links to source games. Deviation changes future responsiveness but not ladder order. | Main | [Browser recipe](../.agents/skills/verify-dice/features/duo-ratings.md), [`test_dice_duo_rating.py`](../backend/tests/test_dice_duo_rating.py), [`DuoDetail.test.jsx`](../frontend/src/dice/pages/DuoDetail.test.jsx) |
| Virtual Dice | Tournament-enrolled players receive virtual currency, lock one fixed-odds pregame match-winner pick, and receive correction-safe payout/refund/reversal ledger entries. It is a bookmaker MVP, not a market maker. | Main | [`test_dice_virtual_currency.py`](../backend/tests/test_dice_virtual_currency.py), [`VirtualDice.test.jsx`](../frontend/src/dice/pages/VirtualDice.test.jsx) |

## Cross-cutting invariants

- The append-only event log and pure projector own game truth; React does not
  calculate official score or statistics.
- Match version is a fencing token. One command wins each version; stale
  clients reload before proposing another command.
- `(match_id, referee, client_command_id)` makes an ambiguous retry idempotent.
- Referee commands may send one exact-envelope hedge after the device's recent
  p90 latency; the delay starts at 1.2 seconds and stays within 0.75–2.5 seconds.
  Request logs tag original, hedge, and retry attempts. A private Supabase metric
  records which attempt won and total latency without affecting game truth.
- Corrections, settlement, and reopening fix forward; they do not rewrite
  history.
- Refereeing may be incomplete. Accurate score with missing detail is better
  than invented data.
- Scoring must remain usable if prediction, pulse, standings, or market context
  fails.
- Product copy names game actions, not event-schema machinery.
- Each concept has one canonical full view. Home and other surfaces may preview
  it, but must link to that view instead of reimplementing it.
- New photo uploads keep an untouched original for download while everyday
  views use cached WebP display and thumbnail variants. Profile avatars are
  bounded WebP assets. Offscreen images load only as they approach the viewport;
  legacy photo URLs remain valid.
- Optimize for a phone, one hand, low attention, and at most five concurrent
  users—not infrastructure scale for its own sake.

## Rating-model contract

`elo_rating` is the long-term skill estimate. A rating difference must
continue to map to a calibrated probability of winning; uncertainty changes
the confidence and learning rate, not that interpretation. A later model may
also include a bounded, time-decayed `form_modifier`:

```text
current_rating = elo_rating + form_modifier
```

`rating_deviation` is a confidence value, not a second skill score:

- new or recently inactive players have higher deviation and respond faster;
- established players have lower deviation and respond more steadily;
- inactivity increases deviation but never lowers Elo by itself;
- deviation and team aggregates are derived from server history, never client input;
- live probability and virtual-odds snapshots freeze Elo, deviation, form, and
  model version at match creation.

The exact deviation floor, ceiling, inactivity clock, and movement function are
tuning parameters. Choose them by replaying representative history before
changing production ratings. Impact bonuses remain separate and bounded; they
must not be fed into deviation or form.

## Agreed but not built

- Do not add full Glicko/TrueSkill, an unbounded streak multiplier, or a second
  mutable rating system. Tune form or impact only through deterministic replay.
- Live bets, prop bets, and tournament-winner pools remain V3. Pregame fixed
  odds and correction-safe settlement are the current boundary.

## Maintenance rule

Update one existing row when behavior changes. Add a row only for a new
user-visible capability. Keep implementation details in code and edge-case
mechanics in the linked contract; this file should stay scannable.
