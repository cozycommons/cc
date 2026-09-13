# Live game lifecycle

## Sub-features

Released experience access, live lobby, 2v2 game creation, join/leave referee, completion, and reopen.

## How to get to it (user POV)

Sign in and open **Live games**. The live referee experience is the only Dice experience and cannot be disabled from the profile. Start or open an ongoing game and join as referee.

## Driving it with Browser

1. Confirm the profile has no experience preference and the released home, Stats, and live surfaces are available. If testing cached-client compatibility, send a legacy preference update with `enabled: false` and confirm the API still returns effective and opted-in access as true without hiding any surface.
2. Start a uniquely named 2v2 game. Confirm Ranked is selected by default, search for four synthetic profiles by name, and verify the selected throwing order before creation.
3. Confirm it appears in the live lobby with a 0-0 score and recognizable player identities. In a separate synthetic game, choose Unranked and confirm that choice persists.
4. Open it, join as referee, leave, and rejoin.
5. Finish the game, verify the official result, reopen it, and verify scoring becomes available again.

## Gotchas

- A tournament is not required for live referee or prediction.
- Lobby freshness may depend on polling; do not assume another client's state is present without a refresh.
- Never use a real event game for verification.
