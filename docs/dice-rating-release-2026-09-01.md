# Dice canonical rating release — 2026-09-01

This log records the production effect of replacing the retired Elo formula
with the canonical Elo plus rating-deviation system. It is a release record,
not a claim that a player's skill changed on the release date.

## Production snapshot

- Captured at: `2026-09-02T05:41:28Z`
- Profiles: 17
- Official games: 52
- Eligible ranked games: 51
- Ranked player-game updates: 202
- Source digest: `767e36e365ba1adf556d1ca56fa95324ac3d86355984a1e1c8e7b138e7a0f7e6`
- Canonical output digest: `b00daa7e90e0f5668a7ff6f3ad2545ebfae30df08d3ebe51630c69a8a1fafcde`

The retired comparison replays the same ordered production history from 1500
using the former K-factor and score-margin formula. The canonical comparison
adds bounded rating deviation, normalizes placement learning, and caps one-game
movement at the player's effective K. A positive delta means the canonical
system gives the player more Elo than the retired formula did.

Leaderboard ranks include visible players with at least three ranked games and
use competition ranking. A dash means the player was still provisional.

## Largest effects

- Largest beneficiary: **Alan Liu**, +15 Elo and three rank positions (13 → 10).
- Largest reduction: **Aaron Lee**, −14 Elo with no rank change (5 → 5).
- Largest downward rank move: **Andre Wang**, two positions (10 → 12) and −8 Elo.
- Ben Kim: −3 Elo with no rank change (3 → 3).
- Pool total: 25,485 retired versus 25,484 canonical. The one-point difference
  is not meaningful inflation or deflation. Varying per-player effective K
  values and integer rounding mean the pool total is not strictly conserved.

## Complete movement

| Player | Retired Elo | Canonical Elo | Delta | Retired rank | Canonical rank | Rank move |
|---|---:|---:|---:|---:|---:|---:|
| Alan Liu | 1456 | 1471 | +15 | 13 | 10 | +3 |
| Jason Keung | 1484 | 1495 | +11 | 9 | 9 | 0 |
| Shrey Shah | 1386 | 1396 | +10 | 16 | 15 | +1 |
| Jaycee | 1399 | 1408 | +9 | 14 | 14 | 0 |
| Alan Li | 1514 | 1522 | +8 | 7 | 6 | +1 |
| Josh Lee | 1568 | 1570 | +2 | 4 | 4 | 0 |
| Oscar Hu | 1497 | 1499 | +2 | 8 | 8 | 0 |
| Warner Tsang | 1598 | 1598 | 0 | 2 | 1 | +1 |
| ashley sung | 1478 | 1478 | 0 | — | — | — |
| Andrew S | 1398 | 1395 | −3 | 15 | 16 | −1 |
| Ben Kim | 1596 | 1593 | −3 | 3 | 3 | 0 |
| William Wu | 1474 | 1471 | −3 | 11 | 10 | +1 |
| Justin Sung | 1465 | 1459 | −6 | 12 | 13 | −1 |
| Andre Wang | 1477 | 1469 | −8 | 10 | 12 | −2 |
| Aziz Rahman | 1607 | 1598 | −9 | 1 | 1 | 0 |
| Matt Ho | 1523 | 1511 | −12 | 6 | 7 | −1 |
| Aaron Lee | 1565 | 1551 | −14 | 5 | 5 | 0 |

Warner's zero-Elo rank gain comes from joining Aziz in a tie at rank 1.
William's rank gain despite losing three Elo is similarly relative: other
players moved around him. Rank movement should therefore always be read beside
Elo movement.

## Archived methodology

This table was generated during the cutover by replaying the identified source
snapshot through both formulas and verifying that the canonical replay matched
persisted production ratings exactly. The source and output digests above bind
the result to that release dataset.

The one-time comparison generator was removed after verification. Keeping a
retired rating formula executable in production would create a second rating
system and an unnecessary maintenance obligation; this dated record preserves
the post-mortem evidence instead.
