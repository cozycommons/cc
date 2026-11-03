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


## Together and apart

6. Use pairs with at least five ranked, official 2v2 games and complete stored
   individual pregame Elo snapshots. Confirm the comparison card appears above
   the Elo grid: **Better together** uses wins over expected and **Better apart**
   uses wins under expected, rounded to one decimal. A pair's record is shown
   together; each member's nonempty record with other partners appears below.
7. The synthetic seed includes **Golf Guard + India In** (positive) and
   **India In + Juliet Jump** (negative). India and Juliet each win with other
   partners. Open both pairs, reload, and check the card at 390px and 320px.
   Below five games or with missing historical ratings, the card is absent.
8. In **Stats → Duos**, confirm **Best chemistry** and **Better apart** each
   contain up to three eligible pairs and link to the matching duo detail.
   The first list orders positive wins above expected descending; the second
   orders negative values ascending. Names and descriptions stay inside cards.
9. Open India's player profile while signed in. **Best partner** links to the
   positive pair and shows the positive comparison. Profiles without a positive
   eligible pairing have no partner row. There is no negative partner callout.
10. **Big moments** is absent until ten completed, ranked live-refereed games
    together have a timeline and positive attributed swing. When present, both
    names and one-decimal percentages accompany a neutral split bar. Corrections
    and retosses must not award swing to removed throws. No ranking terms appear.

Synergy and partner endpoints use the same authenticated registered-profile
boundary as the duo ladder; they do not add data to public profile responses.
The retired feature preference remains true-only, as on the rest of Dice.
