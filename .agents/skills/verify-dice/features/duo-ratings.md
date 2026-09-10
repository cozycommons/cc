# Duo ratings

Use the clean synthetic sandbox and sign in as `referee@dice.local`.

1. Open `/dice`, confirm **Top duos** appears, and open its first duo.
   A pair belongs here after three completed ranked 2v2 games.
2. Confirm both players are identifiable, the rating/record fit at 390px, and
   rating history links to source matches.
3. Open one source match, then return to **Stats → Duos**.
4. Confirm ranked and provisional pairs are distinct. Confirm placed duos are
   ordered by their displayed Elo and equal Elo values share a rank.
5. Reload the duo detail page and confirm the same rating, record, rank, and
   evidence remain.

Also check at 320px that names truncate without pushing ratings or links
outside their cards. The expected API source is the authenticated
`/dice/stats/duos` route; a feature-disabled user must not see this surface.
