# Dice functional QA diary

This diary tracks sandbox user stories exercised against Dice, their expected
state transitions, and the observed result. Synthetic local accounts and the
isolated Supabase stack are used throughout.

## 2026-09-05 — continued play after ready-to-finish

| User story | Exercise | Observed result |
| --- | --- | --- |
| Continue before explicitly finishing | Reach 5–0, finish, rank, reopen, add an opposing point, and refinish at 5–1 | Passed; the game moved `ready_to_finish` → `completed` → `ready_to_finish` → `completed`, retained its ranked intent, and reused its official result |
| Generate the same continuation in the sandbox | Request 6–5 at target 5, win-by 1 after the score was already ready at 5–4 | **Failed in the helper:** an over-strict preflight called `ready_to_finish` terminal; fixed to follow the event contract where only completion and off-roof events are terminal |

## 2026-09-05 — mobile creation and concurrency follow-up

Environment: current local frontend on `localhost:8080`, backend on
`localhost:8001`, synthetic Supabase fixtures, and the in-app browser at
390×844 plus a second desktop tab.

| User story | Exercise | Observed result |
| --- | --- | --- |
| Resolve two referees scoring the same version | Submit opposing points from two tabs, then save the losing tab's preserved intent | Passed; one request received the expected 409, the exact intent remained reviewable, and retry converged both tabs at 2–1 |
| Keep a replay durable through reload | Correct a self-sink to a retoss, then race the replay point against Reload | Passed; the accepted replay appeared once, the temporary saved-result lock cleared after canonical refresh, and the next thrower advanced correctly |
| Create and edit a long ordinary result | Double-submit a ranked 25–23 result with a sink and self-sink, edit it to 25–22 unranked, then rank it again | Passed; create and edit each issued one mutation, optional stats survived, and individual ELO rolled back and reapplied |
| Preserve evidence and personality at 390px | Follow streak and duo rows to exact games, inspect live/recent/tournament/sink/photo sections, and open the photo viewer | Passed without horizontal overflow or a dead evidence link |
| Schedule distinct tournament players | Pick Alpha Toss in both slots of one 2v2 team and submit | **Failed:** the duplicate player persisted; fixed with shared client validation and a server-side request invariant |

## 2026-09-04 — ranked live canonical replay

Environment: local frontend `localhost:8081`, backend `localhost:8001`, local
Supabase, `origin/main` at merge commit `5fa0fe9` (PR #277).

| User story | Exercise | Observed result |
| --- | --- | --- |
| Finish a very short ranked 2v2 | Target 1, one point, finish | Passed; HTTP 200, winner persisted, ordinary history/detail visible, `duo_only=false` |
| Finish a very short unranked 2v2 | Target 1, one point, finish | Passed; HTTP 200 and normal aggregates updated |
| Let either team win | Two ranked target-1 games with opposite winners | Passed; winner teams 1 and 2 persisted correctly |
| Play a long close game | 48 scoring commands to 25–23, then finish | Passed; all versions accepted in order and the official result persisted |
| Correct a completed result | Reopen the 25–23 game, then refinish | Passed; the same game identity was reused and canonical ratings rolled back/reapplied |
| Safely retry a command | Submit the same command ID and payload twice | Passed; identical receipt returned and state advanced once |
| Reject a conflicting retry | Reuse a command ID with a different outcome | Passed; HTTP 409 `dice_live.command_id_conflict` |
| Handle two referees racing | Submit a command with a stale expected version | Passed; HTTP 409 returned the current version and projection |
| Undo a mistaken point | Score 1–1, undo the last point | Passed; score returned to 1–0 |
| Change ranking after completion | Toggle a finished game unranked, then ranked | Passed; both requests returned 200 and canonical state replayed |
| Preserve evidence navigation | Fetch completed ranked game from list and detail APIs | Passed; listed and detail returned 200 with `duo_only=false` |
| End immediately on an off-roof call | Ranked 2v2 at 0–0, team 2 responsible | Passed; projected/persisted 5–0, team 1 winner, `off_roof` termination |
| Delete a completed ranked live game | Delete the materialized 25–23 result | Passed; detail became 404 and the creator's games/ranked games each decreased by one with Elo/RD replayed |
| Reject a stale classic-Dice opt-out | Send `enabled=false` through the retired preference API, then request live and duo APIs | Passed; compatibility state remains true and registered access is unchanged |
| Survive simultaneous referee input | Run 20 two-command races from version 0 | Passed; every race produced one 200 and one 409, persisted version 1, and exactly one point |
| Enforce referee membership server-side | Opt in a second player and submit a score without joining | Passed; HTTP 403 `dice_live.referee_not_joined` and no state advance |
| Correct a result without losing attribution | Change a point to a self-sink | Passed; correction and replacement were atomic and score changed from 1–0 to 0–2 |
| Retoss a corrected physical throw | Retoss the replacement, then record its linked replay | Passed; score rolled back to 0–0 while awaiting replay, then advanced once to 1–0 |
| Catch up after missing part of a game | Save a partial 4–3 score checkpoint | Passed; canonical score became 4–3 and detail coverage remained partial |
| Record FIFA outcomes | Record a saved FIFA followed by a FIFA goal | Passed; save preserved 4–3 and goal advanced the opponent to 4–4 |
| Opted-out creator changes ranked state | Disable the creator's flag and PUT live settings | **Failed:** HTTP 200 changed `ranked`; fixed to fail closed before match lookup and covered by regression test |
| Keep win-by games live through a tie | Reach 4–6, continue to 6–6, and try to finish | Passed; play returned to active and target-reached completion at a tie was rejected with HTTP 422 |
| Finish after a long deuce sequence | Score the 7–6 winner and finish | Passed; state moved through `ready_to_finish` to `completed`, and the ordinary game persisted 7–6 with the correct winner |
| Reject scoring after completion | Submit another throw against the completed version | Passed; HTTP 422 `dice_live.invalid_state` and the official game stayed unchanged |
| Race ranked/unranked settings | Send opposite settings changes concurrently against a completed game | **Failed:** 3 of the first 10 pairs returned HTTP 500 after 60-second rating-lock timeouts; fixed with a 2-second lock bound, retryable 409, and transactional live/canonical flag synchronization |
| Re-run ranked settings races after the fix | Send 10 opposite toggle pairs through one app process and compare both records after every pair | Passed; the process-local guard serialized all 20 requests, no 4xx/5xx surfaced, and live/canonical `ranked` values agreed after every race; a synchronized independent-connection test proves the completed-game canonical path fails within the 2-second retryable-conflict bound under contention |
| Race finish against ranking opt-in | Finish an unranked target-1 game while concurrently setting it ranked | **Failed before row locking:** 1 of 10 games ended with both records unranked despite a 200 settings response; the settings RPC now locks and inspects `official_result_id` after the canonical lock |
| Re-run finish/settings transition race | Repeat concurrent finish plus ranked opt-in for 30 fresh games | Passed; all 30 finished with both live and canonical records ranked and no request failures |

### Browser status

Computer Use is temporarily blocked because the Mac is locked. Resume visual
desktop and 390px interaction checks after the host is unlocked.

### Failure discovered

Completion and reopen commands are durable before the application performs the
canonical rating replay. A transport or database failure during that follow-up
was logged and did not make scoring appear to fail, but there was no durable
retry/outbox. The follow-up below makes this eventual consistency explicit and
observable rather than relying on a successful synchronous replay.

## 2026-09-04 — durable rating repair follow-up

| User story | Exercise | Observed result |
| --- | --- | --- |
| Recover after rating replay fails following an accepted command | Materialize a ranked result while marking its canonical replay pending | Passed; the repair row was committed with the result and remained independently queryable |
| Heal when a player revisits the match | Fetch authenticated live detail for a pending completed match | Passed; HTTP 200 returned the match and the queue row cleared only after canonical replay succeeded |
| Heal without a player revisiting | Run the scheduled repair worker with two pending matches | Passed; both canonical replays completed and both durable queue rows were acknowledged |
| Keep a transient repair failure observable | Hold the canonical database lock past the repair timeout, then release it and retry | Passed against local PostgreSQL; the first attempt recorded the timeout and stayed queued, while the later replay succeeded and cleared that exact match |

The previously open post-command durability failure is addressed by the queue,
scheduled retry, and read-repair paths above.

### Next failure hypotheses

- Live-game creation persists the match and initial referee membership in two
  requests; a failure between them may leave an orphaned lobby entry.
- Live-game deletion tombstones the match before its separate canonical delete;
  a failure between them may hide the live match while leaving its game and
  ratings active.

## 2026-09-04 — atomic live lifecycle follow-up

| User story | Exercise | Observed result |
| --- | --- | --- |
| Creation fails while joining its creator | Force the initial referee insert to raise after the match insert | Failed before the fix would leave an orphan; the new transaction rolled both writes back and the match count was unchanged |
| Create and delete a short ranked game | Create 2v2, score once, finish 1–0, then delete through the ordinary game API | Passed; creation included creator membership, deletion returned 200, the live match was tombstoned, and both game and repair row were absent |
| Create and delete a long ranked game | Submit 48 chronological scoring commands for a 25–23 result, finish, then delete | Passed; all 48 commands returned 200 with no version failures, and atomic deletion left the tombstone with no canonical game |
| Deletion loses its final tombstone race | Apply a valid canonical delete plan with a mismatched live-match identity | Passed against PostgreSQL; the RPC raised `dice_live.delete_source_changed` and the canonical game deletion rolled back |
| Retry creation after losing the response | Submit the same ranked 2v2 twice with one creation key | Passed through the real API; both responses returned the same match ID and only one match/referee pair exists |
| Reject accidental creation-key reuse | Reuse that key with a different ranked setting | Passed; HTTP 409 preserved the original match intent |
| Retry deletion after losing the response | Delete the completed result twice with one deletion key | Passed through the real API; both requests returned 200 and the game remained deleted with one live tombstone |
| Refresh after an ambiguous create/delete response | Unmount and remount the UI before retrying the identical payload | Failed with memory-only keys; fixed by keeping payload-bound pending keys in per-user session storage, recovering deletes automatically, and clearing create recovery on confirmation, observed match, cancel, or five-minute expiry |
| Score while another request deletes the match | Hold the canonical lock, tombstone the match, then let a waiting scoring transaction resume | Failed by inspection before the fix because the database trusted a stale HTTP preflight; passed after an active-match check was added under the shared lock, with zero command or game rows created |
| Replay the exact atomic live deletion | Invoke the database wrapper twice with the same mutation identity and tombstone | Passed; the second call returned the committed replay receipt and made no additional changes |

Both lifecycle hypotheses above are now closed by service-only transactional
RPCs; no frontend behavior or individual Elo formula changed.

### Next failure hypotheses

- A referee may navigate backward or refresh during a pending request and submit
  an action against a stale screen; verify every mutating control either reuses
  its command identity or produces a recoverable version conflict.
- Reopening, correcting, and refinalizing the same long ranked game repeatedly
  may expose drift between the live projection, materialized game, duo replay,
  and individual replay.

## 2026-09-04 — adversarial lifecycle batch after PR #284

The synthetic database was reset from migrations before this round after an
earlier database-only test had left a pre-duo snapshot function installed. The
clean schema exposed no canonical consistency failure.

| User story | Exercise | Observed result |
| --- | --- | --- |
| Play many differently shaped games | Complete opposite target-1 winners, a 5–0 game, a 25–23 win-by-two game, and a game with 30 scoreless throws before five points | Passed; 107 commands were accepted in the first batch and every completed game was deleted with an exact retry |
| Correct and continue after invalid input | Submit a changed ruling without disputed calls, then retry with the required evidence | Passed; the incomplete correction returned 422 without advancing state, while the corrected command completed normally |
| Exercise uncommon endings and edits | Undo a point, change a throw, reopen/refinish a result, record off-roof, and finish from a partial 4–3 checkpoint | Passed; five more games completed and ten exact delete retries returned 200 |
| Reopen and refinish repeatedly | Reopen the same ranked target-1 result ten times and refinish after each correction | Passed; every cycle reused the canonical game ID and a subsequent live create passed the rating-consistency gate |
| Converge duplicate creation | Send 20 simultaneous creates with one key and payload | Passed; all 20 returned 200 and the same match ID |
| Converge duplicate deletion | Send 20 simultaneous deletes with one key | **Failed:** 19 returned 200 and one returned 400 after losing the game between route preflight and mutation planning; the route now reconciles the committed receipt after this race |
| Re-run duplicate deletion after the fix | Send 50 simultaneous deletes with one key | Passed; all 50 returned 200 |
| Reject key reuse across games | Delete one game, then reuse its key for another game | Passed; the second game returned 409 and remained deletable with a fresh key |
| Reject resurrection by create retry | Retry the original create key after its match was completed and deleted | Passed; HTTP 409 and no live match was restored |

## 2026-09-04 — browser-driven deuce and telemetry follow-up

Environment: current frontend on the approved local-harness origin
`localhost:8080`, current backend on `localhost:8001`, and synthetic local
Supabase fixtures. The in-app browser was used because the Mac desktop remained
locked.

| User story | Exercise | Observed result |
| --- | --- | --- |
| Start a game from the visible UI | Sign in, open the live lobby, choose four distinct players in throw order, and start an unranked game | Passed; the browser entered the canonical match URL with the expected teams and 0–0 projection |
| Resume a late tied game after missed plays | Use Catch up score to set a target-5 game to 10–10, choose a thrower, and score to 12–10 | **Failed:** scoring persisted, but every pulse poll returned 422 because valid deuce checkpoints past the target were rejected by probability-history validation; fixed with domain and API regressions, then verified in the same live match with repeated pulse 200s |
| Preserve the game story through a deuce finish | Open Stats at 12–10, finish the game, reload the official result, and reopen it | Passed after the fix; win chance, recorded plays, final score, and correction-aware reopen history remained available |
| Record adaptive command telemetry | Reopen the official game and inspect the browser-triggered telemetry request | **Failed:** every command metric hit an unregistered backend route and returned 404 despite the existing request schema and database table; fixed with authenticated idempotent ingestion and verified through the browser as HTTP 202 plus a database upsert |
| Correct an earlier throw after reopening | At 390px, reopen a 12–10 result and change a pre-checkpoint point to a miss by a different thrower | **Failed, then fixed:** attribution and statistics correctly changed while the absolute checkpoint kept the score at 12–10, but the UI falsely implied that the score would change; the correction sheet now explains the checkpoint before saving and uses accurate removal copy |
| Reconcile the official score after a historical correction | From the checkpoint notice, open Catch up score directly, save a fresh 10–10 checkpoint, correct an older miss to a point, then catch the official score up to 11–10 | Passed after the fix; a new checkpoint clears the notice, the next cross-checkpoint correction restores it, the direct editor preserves explicit partial coverage, and saving the official total clears it again |
| Use checkpoint recovery on phone and desktop | Exercise the correction and direct catch-up sheets at 390×844 and 1280×720 | Passed; every control remained reachable, the mobile sheet fit without internal scrolling, and neither layout introduced horizontal overflow |

### Next failure hypotheses

- Rapidly alternate undo, change-result, and scoring controls while a previous
  request is still resolving; verify the UI never assigns a durable result to
  the wrong thrower.
- Exercise a full long game from individual visible controls, including misses,
  table hits, sinks, self-sinks, FIFA outcomes, and correction dialogs.
- Repeat creation, scoring, finish, reload, and reopen at a 390px viewport and
  check for hidden controls, overflow, or stale action state.

## 2026-09-04 — browser-driven command-state and long-game follow-up

Environment: current frontend on `localhost:8080`, backend on
`localhost:8001`, synthetic local Supabase fixtures, and the in-app browser at
390×844. The Mac desktop remained locked.

| User story | Exercise | Observed result |
| --- | --- | --- |
| Reject accidental rapid scoring | Double-click Point, then rapidly invoke Undo | Passed; each interaction produced one canonical mutation and the projected score matched event replay |
| Avoid stale edits after an accepted save | Let a scoring command succeed while its immediate canonical refresh fails | **Failed:** the optimistic score and receipt updated, but stale recent-play Fix controls briefly unlocked; fixed by keeping every mutating control locked behind a saved-result refresh state, with a direct Refresh now recovery |
| Keep a completed optimistic projection safe | Accept a command whose projection is completed while canonical refresh fails | Passed after the fix; Reopen game and ranked editing remain disabled until official history catches up |
| Resolve simultaneous referee commands | Submit Point and Miss from two 390px tabs at the same version | Passed; one command won, the ambiguous loser retried into a reviewable version conflict, Discard unsaved intent converged both tabs, and all other mutating controls stayed locked during recovery |
| Play a close mixed-outcome game from visible controls | Record points, misses, table hits, and a fully attributed FIFA goal before reaching 5–4 | Passed; every receipt, next-thrower transition, player stat, and score projection matched the selected visible action |
| Correct and reverse a completed winner | Finish ranked at 5–4, reopen, change the old winning point to a miss, catch the checkpoint up to 4–4, score 4–5, and refinish | Passed; the correction preserved append-only evidence, the winner reversed, partial coverage was disclosed, and ranked state survived both completions |
| Follow duo evidence to the exact game | Open Stats → duos → rating history → the new 4–5 loss → Correct in referee | Passed; the conservative ladder kept the 20–2 duo ahead of the 9–0 duo, the rating row linked to the exact ordinary game, and ordinary detail linked back to its live correction surface |

## 2026-09-04 — completed-game ranking and navigation races

| User story | Exercise | Observed result |
| --- | --- | --- |
| Rank a completed game without reopening it | Toggle the completed 4–5 sandbox game unranked and ranked through the live settings API | Passed canonically; the ordinary game and all four individual ELO/RD records rolled back and reapplied, but the page gave no indication that ratings changed and Reload had no progress or completion state |
| Verify the reported production backfill | Inspect the newest production game and public leaderboard without mutating production | Backfill had completed: the game was ranked with before/after rating snapshots and the four current leaderboard values matched; fixed the misleading UX by refreshing canonical detail and confirming “ratings recalculated” after the setting save |
| Return to the same match while a request resolves | Start a command or ranked save, navigate to another match and back, then resolve the original request before the returning load | **Failed by review:** the textual scope matched again and could merge into a null game; fixed with a distinct identity per route visit and regression coverage for both command and settings responses |
| Converge accepted versions across tabs | Persist versions 9 and 8 out of order, then let the version-8 tab clear what it has observed | **Failed by review:** one scalar marker could regress or delete the version-9 requirement; fixed with append-only per-version markers and clearing only through the canonical version actually loaded |
| Know whether Reload worked | Hold a manual canonical refresh open and then resolve it | Passed after the fix; Reload changes to disabled “Refreshing…” and finishes with an “Official game refreshed” receipt |
| Repeat the reported flow in a real browser | At desktop and 390×844, toggle a completed 4–5 game unranked and ranked without reopening, then use Reload | Passed against the current local backend; both rating-replay receipts and the canonical refresh receipt appeared, and the mobile controls remained reachable without horizontal overflow |
| Launch one checkout while another uses the default API port | Start this checkout with an explicit alternate backend URL through the local frontend launcher | **Failed, then fixed:** the launcher overwrote the requested URL and silently connected to an older checkout on port 8000; explicit loopback overrides now survive, and the migration preflight also runs with the macOS/Bash 3.2 toolchain used for this bug bash |

## 2026-09-05 — tournament reconciliation and completed-game edit races

Environment: freshly replayed migrations and synthetic fixtures, current
frontend on `localhost:8080`, current backend on `localhost:8001`, and the
in-app browser at 390×844 plus desktop.

| User story | Exercise | Observed result |
| --- | --- | --- |
| Finish a scheduled tournament game | Repair a malformed legacy schedule, complete both distinct teams, enter a ranked 5–4 result, and return to the tournament | Passed; the schedule reconciled into one linked result and all four standings updated |
| Edit one completed game from two devices | Open the same ranked result in desktop and mobile editors, save 6–4 on desktop, then save stale 5–3 Normal on mobile | **Failed:** the stale editor silently replaced the first correction and rolled ratings back; fixed with a transaction-level revision guard and explicit conflict recovery |
| Preserve a stale editor's intent | Repeat the race at 390×844 after the fix | Passed; the winning result remained canonical while the stale form stayed intact and the recovery card compared every team, sink, self-sink, substitute, score, ranked, and tournament field without horizontal overflow |
| Resolve a completed-game conflict deliberately | Choose “Save my changes now” after reviewing the newer result | Passed; the retained 12–6 Normal edit saved against the latest revision and canonical ratings followed the explicit choice |
| Reject retryable error semantics for a UI conflict | Exercise the first database guard through the real gateway | **Failed in the first implementation:** a serialization SQLSTATE caused automatic transport retries; changed to a non-retryable application error and reran the browser race successfully |
