# Duo ratings

Use the clean synthetic sandbox and sign in as `referee@dice.local`.

1. Open `/dice`, confirm **Top duos** appears, and open its first duo.
   A pair belongs here after three completed ranked 2v2 games.
2. Confirm both players are identifiable, the rating/record fit at 390px, and
   rating history links to source matches.
3. Open one source match, then return to **Stats → Duos**.
4. Confirm ranked and provisional pairs are distinct. Confirm placed duos are
   ordered by their displayed Elo, first place is a highlighted row, and equal Elo values show T ranks. Home includes every duo tied at its third-row cutoff. Provisional pairs share a single row list with muted Elo and no View all link.
5. Reload the duo detail page and confirm the same rating, record, rank, and
   evidence remain.

Also check at 320px that names truncate without pushing ratings or links
outside their cards. The expected API source is the authenticated
`/dice/stats/duos` route; a feature-disabled user must not see this surface.


## Together and apart

6. Use pairs with at least five counted ranked, official 2v2 games. Duo-only
   games count in both together and apart records. Missing individual pregame
   Elo uses each player's latest Elo after a strictly earlier ranked game, or
   starting 1500. Confirm the comparison card appears above the Elo grid.
   **Better together** / **Better apart** is a small label above two
   percentages: **Won together** with the counted together record, and
   **Expected** from each game's individual pregame Elo. Rates round half up to
   whole percents. When both display the same value the label is **Right on
   expected**; the label never disagrees with the shown numbers.
7. The synthetic seed includes **Golf Guard + India In** (positive) and
   **India In + Juliet Jump** (negative). India and Juliet each win with other
   partners. Open both pairs, reload, and check the card at 390px, 320px, and
   desktop. The nonempty apart records share one line, wrap cleanly, and shorten
   long names to first names. The Record tile shows the pair's overall record.
8. In **Stats → Duos**, the ladder stays first. Below Ranked duos and above
   Provisional, one card contains **Best chemistry** and **Better apart**: two
   columns on desktop, stacked on mobile. Each list links up to three pairs,
   with a 34px avatar stack, names, the counted together record, and an aligned
   together win rate over its expected rate. Check that names truncate and
   numbers stay inside their rows at 320px. Lists rank by the displayed rate gap,
   not the win count, so a short perfect run can outrank a long strong one.
9. Open India's player profile while signed in. **Best partner** sits directly
   above Head to head, with a 34px partner avatar and an arrow. Its link shows
   the counted together record, then the together and expected win rates. The
   partner is chosen by the largest positive rate gap. Profiles without a
   positive eligible pair have no partner row.
10. **Big moments** is absent until ten completed, ranked live-refereed games
    together have a timeline and positive attributed swing. At most the latest
    30 such matches are considered; their ledger events are fetched in ordered
    batches. When present, **Share of big swings** accompanies both names,
    whole percentages summing to 100, and two equal-weight team tones.
    Corrections and retosses must not award swing to removed throws.

Synergy and partner endpoints use the same authenticated registered-profile
boundary as the duo ladder; they do not add data to public profile responses.
The retired feature preference remains true-only, as on the rest of Dice.

11. Fail a duo ladder read: it retries once automatically. After two failures,
    Home retains Top duos with **Couldn't load duos · Retry**; Stats has the same
    recovery row. Retry restores the actual ladder after the service recovers.
