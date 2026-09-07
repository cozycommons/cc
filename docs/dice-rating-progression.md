# Dice rating progression contract

`GET /dice/profiles/{user_id}/rating-progress` is the authoritative v1
progress contract. It derives history only from official game-player Elo
snapshots and returns the current competition rank/tie state, placement state,
personal best, last rating delta, last rank movement, and chronological points.
Clients display this response and do not replay Elo themselves.

Rank movement uses the currently visible, established leaderboard field. A
present-day privacy change can therefore change historical rank context; the
response labels this scope explicitly instead of pretending visibility history
was recorded when it was not.

Competition ranking is `1, 2, 2, 4`. A tied rank is explicit. Provisional
players have no rank until three completed ranked games. Corrections remain
safe because the repository rebuilds the response from corrected official
snapshots.

The endpoint reads profiles, games, and player snapshots through one SQL RPC
statement, giving each response a single PostgreSQL MVCC snapshot even during
concurrent corrections. The response fails closed if the snapshot does not
reproduce the profile's stored rating and ranked-game count.
