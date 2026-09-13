# Referee scoring

## Sub-features

Player identity, advisory turn order, common outcomes, compact probability, Referee/Stats switching, animated receipt, and undo.

## How to get to it (user POV)

Open an ongoing live game, join as referee, and use the Referee view.

## Driving it with Browser

1. Choose the teammate who is not currently suggested and record **Miss**.
2. Confirm the action receipt is readable, offers **Undo**, and the newly inferred order is visible to another refreshed client.
3. Record **Table hit** twice: choose **Dead** once and a receiving player once. Verify neither changes the score, only the caught throw credits a catcher, and both credit the thrower's table-hit outcome.
4. Record the next two ordinary observations, including **Point**, and verify the advisory queue follows the effective history.
5. Undo the point and confirm score, latest play, turn hint, and probability return to the corrected state.
6. Switch to Stats and back in one gesture; confirm score context remains understandable.
7. In Stats, confirm each observed throw is attributed to its thrower, the table catch is attributed to its catcher, and zero-value chips stay hidden. Finish the game and confirm the same player breakdown appears on ordinary game detail.
8. Repeat the core path at about 320px wide and check that names, avatars, queue, controls, receipt, and player-stat chips remain inside their containers.
9. For delivery recovery, interrupt one command response, reload the page, and confirm the retained result can retry with the same command ID before another result is entered.
10. Delay one command beyond the adaptive threshold. Confirm one identical hedge is sent, one canonical event appears, and a fast `4xx` response does not launch a hedge.
11. Confirm command request logs share one operation ID and distinguish `original`, `hedge`, and `retry`; confirm the client metric names the winning attempt and persists one row for the operation.
12. Confirm the compact play log distinguishes a dead table hit from a named catch and shows every FIFA participant without exposing event IDs or schema terms.

## Gotchas

- Ordering is a hint, never a validity rule or persisted lineup.
- An out-of-order throw intentionally changes the inferred teammate order.
- After an unobserved gap, ordering should be unknown until play establishes it again.
- An uncertain save blocks a second result until the referee retries or discards it. A stale-version save requires review and a new command ID.
- Command hedging learns from the device's last 20 original attempts, uses p90 after five samples, and never sends more than one duplicate.
- Validate labels and reachability, not a fixed visual arrangement.
