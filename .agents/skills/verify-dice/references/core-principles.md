# Dice product principles

These are durable decision rules, not a snapshot of today's layout.

1. **Adoption beats completeness.** Refereeing must be faster than reconstructing the game later. Missing detail is acceptable; a chore is not.
2. **Score can continue without full stats.** Catch-up, partial history, and finish-with-gaps are supported. Never invent unobserved throws or players.
3. **One canonical history.** The append-only event ledger and pure server projector define score and official statistics. Clients submit observations; they do not derive truth.
4. **Corrections preserve meaning.** Replacing or removing a mistaken throw is different from recording a true retoss. Reopen and fix forward; off-roof remains an attributed instant 0-5 result.
5. **Concurrency fails visibly and safely.** Commands carry an expected version and stable command ID. One command wins an epoch; stale clients refresh and intentionally resubmit. Exact retries are idempotent.
6. **Turn order is advisory.** Derive the hint from effective observations, allow an intentional override, and let that override become the next hint. After an unknown gap, show uncertainty instead of fabricating order.
7. **Referee and spectator needs differ.** Referee mode optimizes one-handed, common-action speed. Score and a compact probability signal stay visible; richer pulse and statistics are one gesture away.
8. **People should look like people.** Use names, pixel avatars, and stable team colors. Do not make UUID fragments or initials the primary identity.
9. **Enrichment cannot block scoring.** Prediction, charts, markets, standings, and animation degrade independently from referee mutations.
10. **Design for the actual scale.** This is a personal event tool for at most a few concurrent users. Prefer simple polling and fix-forward recovery; add Realtime as invalidation only when polling proves inadequate.
11. **Released changes fix forward.** Live referee, expanded home, Stats, and duo ratings are the only Dice experience. Do not restore the retired profile flag or classic frontend; cached-client compatibility endpoints must remain true-only until they are removed.
12. **Verify the real surface with synthetic data.** Unit contracts protect mechanics; browser runs protect usability. Production is never the test fixture.

## Deliberately not principles

Exact copy, button position, card order, animation duration, polling interval, screenshots, and PR topology may evolve. Promote one only when repeated product decisions depend on it.
