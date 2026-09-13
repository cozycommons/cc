# Prediction and Virtual Dice

## Sub-features

Compact live probability, Stats/Pulse details, pregame fixed-odds picks, bankroll, settlement, correction compensation, and standings.

## How to get to it (user POV)

Open any live game for probability. For Virtual Dice, enroll in an event, open its Virtual Dice page, and choose an open match-winner market.

## Driving it with Browser

1. Record score-changing observations and confirm the compact probability moves without obscuring referee controls.
2. Open Stats and confirm richer probability and recorded-play context agree with the same canonical game version.
3. Simulate prediction failure and confirm scoring remains usable.
4. When a synthetic tournament fixture exists, grant a bankroll, open a pregame market, place one pick, and verify it locks immediately with the quoted total return.
5. Finish, reopen, and refinish with the other winner; verify settlement, reversal/refund, and corrected payout remain exact and idempotent.
6. Simulate standings failure and confirm bankroll and open markets remain usable.

## Gotchas

- Probability must never regress to an older game version after a slow response.
- Virtual Dice is tournament-scoped for the first event; live referee and prediction are not.
- Current picks are fixed-odds and pregame, not a live market maker.
- Enrichment failures must not reject or hide accepted scoring.
