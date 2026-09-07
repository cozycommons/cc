# Dice live-game event and projection contract

This contract defines the durable facts needed for shared live refereeing. It
is the input to the schema and projector, not a UI specification.

## Why this shape

The event log is an append-only ledger. A correction removes a mistaken entry
or replaces it in its original logical position; it never records a new
physical throw. A retoss records a table decision and then a new physical
throw. A checkpoint records the known score when part of the game was not
observed. These are different operations and must remain different in storage.

The design evolves in layers: normative contract and examples, append-only
database/API, one pure server projector, then small UI actions over that
projector. Clients may change without redefining match history.

## Saved match and command acceptance

A match atomically saves:

- its roster and two teams;
- `contract_version`, `ruleset_version`, and `scoring_version`;
- target score and win-by;
- normalized call policy.

Changing a saved rule starts a new match.

Every event retains `recorded_by`; that is separate from player attribution.
A client command has a stable identity of
`(match_id, recorded_by, client_command_id)` and an expected match version.
The server canonicalizes and compares the complete payload. An exact retry
returns the stored acceptance receipt without appending or rematerializing
anything. Reusing an identity for a different payload conflicts.

Command payloads are strict and kind-specific. Fields that are irrelevant to
the named command are rejected rather than ignored, and validation failures
use `dice_live.invalid_command` with the offending field identified. This
keeps canonical retry comparison meaningful and prevents a client typo from
silently changing intent.

Expected-version checks serialize accepted commands. They do not merge
arbitrary histories created independently by offline clients. A stale client
must reload the authoritative log before submitting another command. When
physical play continued while recording was unavailable, recover with a
partial or unknown checkpoint instead of inventing throws.

An accepted command produces either:

- one ordinary event, including a `retoss_decision`; or
- one atomic `correction` plus replacement pair.

The server assigns contiguous command indexes and match sequences. A later
physical retoss is always a separate command.

## Observation

An observation records one resolved physical throw:

- `thrower_id`;
- server-derived `throwing_team_id`;
- one closed `outcome`;
- server-derived `[team_1, team_2]` `score_delta`;
- outcome-specific fields.

The outcomes and scoring are:

| Outcome | Meaning | Score |
| --- | --- | --- |
| `miss` | Legal throw with no table result | none |
| `caught` | The throw hit the table and was caught | none |
| `point` | Ordinary point | throwing team +1 |
| `sink` | Thrower sank the die | throwing team +1 |
| `self_sink` | Thrower caused a self-sink | opposing team +2 |
| `fifa` | Receiving team completed a FIFA play | opposing team +1 |
| `invalid` | Short, low, or both | none |

`table` is not a separate outcome: a table hit that does not score is
`caught`. `short` and `low` always make the throw `invalid`; neither may be
attached to any other outcome. An invalid observation has a nonempty
`characteristics` set containing only `short`, `low`, or both.

The server derives and validates team and score from the saved roster and
outcome. A client cannot override either. Scoring semantics are frozen by the
saved `scoring_version`.

### Off-roof termination

An `off_roof` event is a strict attributed terminal event with
`responsible_player_id` and server-derived `losing_team_id`. It carries no
client score and is not an observation. The responsible player must be in the
saved roster, and the losing team must be that player's team. Projection
immediately sets the absolute score to 0–5 in saved team order, records
`termination_reason=off_roof`, and becomes `completed`; prior observed
statistics and coverage remain unchanged. A retoss cannot target an off-roof
event, and off-roof is rejected while a replay decision is pending.

### Attribution

`self_sink` is a negative statistic attributed to the thrower. The opponents
receive two team points, but no opponent player receives a throw statistic.

FIFA has three valid finishes:

- `kick_catch`: `kicker_id` and a distinct `catcher_id`, both on the receiving
  team, gives that team one point;
- `goal`: `kicker_id` on the receiving team, gives that team one point;
- `goal_saved`: `kicker_id` on the receiving team and `saver_id` on the
  throwing team, gives no point and play continues.

These participant facts are retained even if the first UI only shows the
result. Derived player analytics can be added without changing match history.

## Corrections

A correction has a prior `target_event_id` and reason:
`mistaken_entry`, `changed_ruling`, or `other`. A hard correction may remove a
mistaken observation, replay, or retoss decision without a replacement. A
changed ruling also records the nonempty `disputed_calls` set and decision
basis.

Changing an observation rather than removing it replaces the complete
observation as one atomic command. Calls such as `short` and `low` are context
for the decision, not independently mutable tags. This prevents impossible
half-edits. For example:

- `point` may become `invalid` with both `short` and `low`;
- `sink` may become `self_sink`;
- an invalid throw may become a legal result.

The replacement occupies the target's logical slot. It is appended for audit
but never acts as a later physical throw. Another change targets the active
replacement.

A checkpoint or completion cannot simply disappear. Its correction and
replacement are atomic. A checkpoint becomes a checkpoint. A completion
becomes either another completion or a checkpoint that reopens play.
An active off-roof may be hard-corrected to reopen the match; the event remains
in the ledger, but its terminal effect and 0–5 score are removed when earlier
slots are reprojected.

## Retosses

A `retoss_decision` means the original attempt does not count competitively.
It may target a recorded observation or stand alone when no honest original
ruling could be recorded. It retains the thrower, throwing team, decision
basis, disputed calls, and any known short/low characteristics.

When it targets an observation, that observation contributes no official
score or statistics. It remains in the ledger for future analysis of physical
attempts and adjudication. This is deliberate: a successful retoss can later
support “ball don't lie” analysis without corrupting official totals.

The next physical observation links to the decision when `record_throw` carries
`replay_of`. The reference must be a nonempty event ID naming an active,
unfulfilled `retoss_decision` in the same append-only match prefix; malformed,
irrelevant, inactive, and already fulfilled targets are rejected with
`dice_live.invalid_replay`. Until a replay is linked, projection status is
`awaiting_replay`, and unrelated score-bearing play is rejected. A retoss may
itself receive another retoss decision.

If the retoss happened but was not recorded, the next checkpoint or completion
resolves it as `unobserved` with partial or unknown coverage. If it never
happened, the boundary resolves it as `cancelled`. Neither path invents an
observation.

All links target earlier events in the same match. A retoss target is an
observation. A replay is an observation, is a later command, and is not also a
replacement.

## Completion and historical validity

An active completion or off-roof event is terminal. It must be the final active
score-bearing logical slot. `target_reached` must satisfy the saved target and
win-by; other termination reasons explicitly authorize an early final score.
When an active nonterminal projection satisfies target plus win-by, it derives
`ready_to_finish` without inventing a completion or termination reason.

Earlier slots may still be corrected. A score-changing correction or retoss
after completion must first atomically replace the completion with a
checkpoint. Later reopening cannot legalize a command that was invalid when
accepted. The projector validates the log at every complete command boundary,
including periods awaiting a retoss.

Every completed projection publishes one shared game result. The result keeps
the same identity across reopen and later completion. Reopening marks that
materialization `reopened`, so shared game detail, history, aggregates, and
statistics recomputation exclude it while the append-only live ledger remains
available for audit. A later completion republishes the same result as
`official` with the latest score, termination reason, and coverage.

An authorized early finish may be tied. It is an official draw with
`winner_team=null`: games played and the final score are retained, but neither
team receives a win or loss and Elo is not changed. The server derives the
winner from the score; a client-supplied winner field is unsupported and is
rejected as `dice_live.invalid_command`.

## Coverage and missing observations

Every active checkpoint or completion names the prior root coverage boundary
with `coverage_after` and labels its interval:

- `complete`: every observable action was recorded;
- `partial`: at least one action is known to be missing;
- `unknown`: completeness was not established.

Boundaries form one unbroken chain. For a complete interval, the absolute
boundary score must equal the prior boundary plus its active observations as
of that boundary's server sequence. A partial or unknown boundary is
authoritative even when observations cannot explain its score.

Missing observations are absence, never synthetic misses. Official statistics
count only active observations. Score gaps and coverage labels do not create
attempts, catches, misses, or player statistics.

## Referee actions and UI vocabulary

The live-referee UI exposes these server-backed actions:

- Record throw
- Change throw
- Retoss
- Fix score
- Finish game
- Record an off-roof loss
- Undo the referee's latest active observation
- Reopen a completed game

It should not expose event kinds, replacement links, command indexes, or
coverage-chain mechanics. During a dispute it should pause rather than publish
a provisional score. Scoring requires the user to join as a referee, and the
live-referee routes must not read game data unless that user's effective
feature gate is enabled.

Exact possession, attempt number, and next thrower are advisory in contract
v1. Partial coverage can omit the facts needed to reconstruct them. The UI may
suggest the next player, but must permit an override and fall back to unknown
after a gap or checkpoint.

## Deterministic projection

Given the saved match and complete event log, the server:

1. validates saved rules, command groups, links, and every complete command
   prefix;
2. resolves correction chains into original logical slots;
3. removes observations voided by retoss decisions;
4. replays active logical slots in order, with checkpoints and completion
   replacing the score absolutely;
5. validates complete coverage intervals and completion rules;
6. counts official statistics from active observations only; and
7. derives coverage, nullable termination reason, and `active`,
   `awaiting_replay`, `ready_to_finish`, or `completed` status.

The executable golden vectors in
`backend/tests/fixtures/dice_live_projection_vectors.json` are normative for
edge cases. They use abbreviated envelopes for readability. Production events
also require immutable server ID, match ID, version, command metadata,
recorder, timestamp, and nonnegative match-relative time.
