# Dice feature map

This is the short product contract for Dice. It says what users can rely on,
what owns truth, and whether the behavior is shipped. Detailed event mechanics
remain in [the live-event contract](dice-live-event-contract.md).

Status:

- **Main** — merged to `main`.
- **Stack** — implemented in open PRs; not shipped from `main` yet.
- **Later** — agreed direction, not implemented.

Last reconciled: 2026-08-27 at the head of PR #236.

## Feature surfaces

| Feature | User contract | Status | Executable proof |
| --- | --- | --- | --- |
| Beta access | Any registered player may opt in for themselves. Profile access is the sole rollout boundary; disabled routes fail closed. | Main | [`PlayerProfile.features.test.jsx`](../frontend/src/dice/pages/PlayerProfile.features.test.jsx), [`useDiceAuth.features.test.jsx`](../frontend/src/dice/useDiceAuth.features.test.jsx) |
| Private sandbox | Synthetic Dice data is isolated from production. The same setup works locally and in a private Codespace; only the frontend is exposed. | Main | [Sandbox guide](dice-sandbox.md), [`test_dice_local_harness.py`](../backend/tests/test_dice_local_harness.py) |
| Live games | Ongoing games are first-class and discoverable. A registered, enabled player may create a 2v2 game, join or leave as referee, and open it directly. | Main; setup polish in [#231](https://github.com/jasonkeung/dummi/pull/231) | [`LiveLobby.test.jsx`](../frontend/src/dice/pages/LiveLobby.test.jsx) |
| Referee scoring | Referee mode prioritizes one-handed entry. Common actions are Point, Table hit, FIFA, and Miss; rare outcomes stay under More. The server derives team and score. | Main; mobile hierarchy in #231 | [`LiveGame.test.jsx`](../frontend/src/dice/pages/LiveGame.test.jsx), [`test_dice_live_service.py`](../backend/tests/test_dice_live_service.py) |
| Turn hint | Order is advisory, never a stored game fact. From effective observations, each team loosely takes two throws; the teammate opposite that team's last throw is suggested next. Selection remains overridable. `A → B → A` suggests `B`. | [#231](https://github.com/jasonkeung/dummi/pull/231) | [`liveTurnOrder.test.js`](../frontend/src/dice/liveTurnOrder.test.js) |
| FIFA | A FIFA is a goal, teammate catch, or saved goal. Receiving-team roles and the opposing saver are retained; a save awards no point and play continues. | Main; streamlined UI in #231 | [Attribution contract](dice-live-event-contract.md#attribution), [`test_dice_live_contract.py`](../backend/tests/test_dice_live_contract.py) |
| Mistakes and disputes | Undo removes the referee's latest active observation. A correction replaces the whole throw in its original slot. A true retoss records a decision and a later physical replay. These are never interchangeable. | Main; clearer recovery UI in #231 | [Corrections](dice-live-event-contract.md#corrections), [Retosses](dice-live-event-contract.md#retosses), golden vectors |
| Missing play | A referee may catch up to a known score or finish with partial/unknown coverage. Missing throws never become synthetic misses or player statistics. | Main | [Coverage contract](dice-live-event-contract.md#coverage-and-missing-observations), golden vectors |
| Completion | Reaching the target makes the game ready, not automatically final. Finish is explicit. Off-roof is an attributed immediate 0–5 loss. Reopen/correct/refinish preserves one official result identity. | Main | [Completion contract](dice-live-event-contract.md#completion-and-historical-validity), [`test_dice_virtual_lifecycle.py`](../backend/tests/test_dice_virtual_lifecycle.py) |
| Recorded statistics | Official score may diverge from recorded-play totals after checkpoints. Only active observed throws count; corrected, removed, and retossed originals do not. Player FIFA roles and self-sink blame remain distinct. | Main | [`test_dice_live_contract.py`](../backend/tests/test_dice_live_contract.py), [`LiveGame.test.jsx`](../frontend/src/dice/pages/LiveGame.test.jsx) |
| Win probability | New matches capture a versioned independent prior-win-rate model; pre-migration matches retain their saved Elo prior. Score and saved rules produce a version-matched live estimate; invalid estimates fall back to neutral. Probability never decides or mutates score. | Main; independent model in the current PR stack | [`test_dice_live_probability.py`](../backend/tests/test_dice_live_probability.py), [`GamePulse.jsx`](../frontend/src/dice/pages/GamePulse.jsx) |
| Rating uncertainty | A rating deviation will represent confidence alongside Elo. It makes new or recently inactive ratings more responsive without changing the meaning of Elo as a win-probability estimate. | Later | Planned rating-model contract below |
| Referee and Stats views | The live game opens on the fast Referee surface. Stats is one tap away; a compact odds bar keeps the game state visible without occupying scoring space. | [#230](https://github.com/jasonkeung/dummi/pull/230) and #231 | [`LiveGame.test.jsx`](../frontend/src/dice/pages/LiveGame.test.jsx) |
| Virtual Dice | Tournament-enrolled players receive virtual currency, lock one fixed-odds pregame match-winner pick, and receive correction-safe payout/refund/reversal ledger entries. It is a bookmaker MVP, not a market maker. | Main; standings in [#228](https://github.com/jasonkeung/dummi/pull/228), game story in #229 | [`test_dice_virtual_currency.py`](../backend/tests/test_dice_virtual_currency.py), [`VirtualDice.test.jsx`](../frontend/src/dice/pages/VirtualDice.test.jsx) |

## Cross-cutting invariants

- The append-only event log and pure projector own game truth; React does not
  calculate official score or statistics.
- Match version is a fencing token. One command wins each version; stale
  clients reload before proposing another command.
- `(match_id, referee, client_command_id)` makes an ambiguous retry idempotent.
- Corrections, settlement, and reopening fix forward; they do not rewrite
  history.
- Refereeing may be incomplete. Accurate score with missing detail is better
  than invented data.
- Scoring must remain usable if prediction, pulse, standings, or market context
  fails.
- Product copy names game actions, not event-schema machinery.
- New photo uploads keep an untouched original for download while everyday
  views use cached WebP display and thumbnail variants. Profile avatars are
  bounded WebP assets. Offscreen images load only as they approach the viewport;
  legacy photo URLs remain valid.
- Optimize for a phone, one hand, low attention, and at most five concurrent
  users—not infrastructure scale for its own sake.

## Planned rating-model extension

`elo_rating` remains the long-term skill estimate. A rating difference must
continue to map to a calibrated probability of winning; uncertainty changes
the confidence and learning rate, not that interpretation. A future snapshot
may also include a bounded, time-decayed `form_modifier`:

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

- Replace the current 15-second active-game refresh with roughly two-second
  visible polling plus immediate focus/reconnect refresh. If that becomes
  meaningfully slow or expensive, use Supabase Realtime only as a version
  invalidation signal and retain recovery polling.
- Add a Glicko-inspired `rating_deviation` without replacing Elo. Prove that
  high-deviation players move more, inactivity increases uncertainty without
  changing skill, rating differences remain probability-calibrated, and
  corrections replay deterministically. Do not add full Glicko/TrueSkill, a
  streak multiplier, or a new rating table in the first cut.
- Persist an in-flight command ID and payload on the phone until acknowledged,
  so suspension after submission can retry the exact command safely.
- After a partial/unknown checkpoint, explicitly show turn order as unknown
  until a referee establishes it again. Do not infer missing throws.
- Live bets, prop bets, and tournament-winner pools remain V3. Pregame fixed
  odds and correction-safe settlement are the current boundary.

## Maintenance rule

Update one existing row when behavior changes. Add a row only for a new
user-visible capability. Keep implementation details in code and edge-case
mechanics in the linked contract; this file should stay scannable.
