# Dice match edit/delete failure — 2026-09-03

## Summary

An administrator attempted to change a Dice game with a 1–4 score from
unranked to ranked, then delete it. The UI reported the generic validation
message (“all 4 players are distinct and scores don't tie”) for the save, and
the delete also failed. The affected record was initially assumed to be a
manually logged game, but log correlation showed it was a materialized
live-referee result.

Production log correlation identified the affected game as
`665d97ba-c20b-4bff-be86-f003093fc411`.

## Impact

The game could not be corrected or removed through the product. The generic
message obscured whether the failure was validation, authorization, or a
database mutation error. No evidence in the repository indicates that the
game was counted as ranked; production cleanup must be confirmed by querying
the affected game id before and after release.

## Findings

### Confirmed production cause

The failed PUT and DELETE for the affected game both returned HTTP 400. In
the request sequence immediately before those responses, the backend queried
`dice_games.source_live_match_id` for this exact game. That is the live-result
ownership check: the row is a materialized result of the append-only live
referee ledger, not an ordinary manually logged game. The generic game editor
was therefore the wrong mutation path, and the UI translated the intentional
live-result rejection into the unrelated distinct-player/score message.

The correct correction path is the referee/live-result workflow. The live
ledger must not be deleted as part of cleaning up the materialized result.

The home view also made five independent requests and converted the first
transient failure of each into an empty list, with no retry. This could render
a blank set of cards until the browser was refreshed.

The logs also show a separate route bug: `GET /dice/profiles/search?q=&limit=100`
was routed as `/dice/profiles/{user_id}`, producing a PostgreSQL UUID parsing
error for `search?q=&limit=100`. This can break the match-entry picker, but it
is not the cause of the failed game PUT/DELETE.

The game endpoint replaces `dice_game_players` after updating `dice_games`, but
the writes were not checked and deletion relied on the parent FK cascade. The
recent player-schema/live-result migrations made those assumptions unsafe on a
partially upgraded production database. The frontend also discarded the API's
actual error detail.

## Remediation

The Dice repository now:

- verifies the target game before mutation and verifies mutation responses;
- explicitly removes owned comments and player rows before deleting a game;
- explicitly replaces player rows during edits, including the newer
  `counts_for_group_stage` and `sinks` fields; and
- returns server error detail to the edit and delete flows; and
- rejects live-materialized rows from generic CRUD with a stable `409` error
  directing operators to the referee correction workflow.
- allows authorized users to change a live match's ranked setting through a
  dedicated settings endpoint while leaving the append-only event ledger
  untouched and recomputing profile aggregates.
- retries each home-page preview request before showing an empty-state card and
  ignores late responses after navigation/unmount.

The regression matrix covers both 1v1 and 2v2 games, both initial ranked
states, both updated ranked states, score/team changes, and deletion.
The frontend browser suite also covers the exact 1–4 ranked-toggle/save and
delete attempt against a live-materialized row, plus recovery from a transient
home-page request failure.
The live referee UI now exposes the ranked setting and links failed legacy
CRUD attempts directly to the referee correction view.

## Production cleanup/runbook

1. Identify the exact game id from the authenticated admin game list/logs by
   creator/player and score `(1, 4)`; do not delete by score alone.
2. Record the row, player rows, comments, and any `source_live_match_id`.
3. If it is a manual game, use `DELETE /dice/games/{id}` after the fixed API is
   deployed, then verify GET returns 404 and player/comment rows are gone.
4. If it has a live source, do not delete the live ledger; verify whether the
   official materialization should be reopened through the referee workflow.
5. Recompute/verify affected profiles and confirm the game is absent from the
   public history and leaderboard.

No production mutation was performed while the game id and authoritative
production log entry were unavailable in this workspace.

## Prevention

Keep the CRUD matrix in the Dice integration suite and the Playwright browser
regressions as release gates. CI runs the browser suite on frontend changes;
the backend test job runs the CRUD matrix and the live-materialization guard.
Run the matrix against the local Supabase stack plus the production schema
attestation before deploying data-model changes. Preserve the exact backend
error in client-side telemetry and display it in admin/debug contexts.
