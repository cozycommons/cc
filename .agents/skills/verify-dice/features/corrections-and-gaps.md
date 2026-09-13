# Corrections and gaps

## Sub-features

Undo, whole-throw replacement/removal, true retoss, catch-up score, partial coverage, finish-with-gaps, reopen, and off-roof.

## How to get to it (user POV)

Open a live game, record at least one observation, then use its correction affordance or **Game options**.

## Driving it with Browser

1. Record a point, replace the whole throw with an invalid result, and verify the point and original attribution disappear.
2. Mark a throw for true retoss, record the replay, and verify only the replay contributes once.
3. Use catch-up score to move the score without claiming missing player statistics; verify coverage is partial or unknown, the turn hint becomes unknown, and manually choosing a thrower re-establishes play.
4. Finish despite incomplete statistics, verify the official score remains authoritative, then reopen and correct forward.
5. In a separate synthetic game, record off-roof and verify the attributed instant 0-5 result.

## Gotchas

- Hard correction changes the original logical throw; retoss records a later physical throw.
- Removed and retossed originals contribute no official statistics.
- Checkpoints and unknown gaps never synthesize players or observations.
- Off-roof is terminal attribution, not a normal throw statistic.
