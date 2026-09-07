# Dice independent prediction contract

## Leakage-safe dataset

`dice-prediction-dataset/v1` emits one chronological row per eligible official
ranked game. Every feature is calculated before the row's outcome updates
player state:

- Bayesian-smoothed prior win rate for each team and their difference;
- prior games and log-scaled experience difference;
- days since each team's last recorded game and recency difference;
- the pregame v1 Elo probability as an evaluation baseline only;
- game time, roster, team size, target score, and the eventual binary outcome.

Appending a future game cannot change earlier rows. Duplicate games, duplicate
players, incomplete teams, and mixed dataset versions fail closed.

Run the read-only production evaluation from `backend/`:

```bash
PYTHONPATH=. SUPABASE_URL=... SUPABASE_ANON_KEY=... \
  python scripts/dice_prediction_report.py
```

Promotion requires at least 40 total games, at least 10 chronological held-out
games, and Brier score strictly better than neutral across 50%, 60%, 70%, and
80% expanding chronological train splits. Smaller samples report
`insufficient_data`; models that miss the quality bar report `rejected` and are
not served.

## Accepted pregame model v1.0.0

The accepted model uses only the difference between team-average,
Bayesian-smoothed prior ranked win rates. It deliberately has no intercept, so
equal evidence remains 50/50 and a historical team-side imbalance cannot become
a permanent advantage. It is independent from social Elo writes.

On the 2026-08-29 2v2 production chronology it trained on 35 games and evaluated
on the next 15. Its held-out Brier score was 0.2383 versus 0.2500 neutral; log
loss was 0.6701 versus 0.6931. Existing Elo scored 0.2291/0.6509, but remains an
evaluation baseline rather than an input. Calibration is still uncertain at
this sample size, so the feature remains experimental.

The production coefficient was refit on all 50 eligible 2v2 games and is stored as
the immutable `dice-pregame-logistic` v1.0.0 artifact in code.

## Live serving and fallback

At live-match creation the server captures a nullable `prediction_snapshot`
with model ID/version, dataset version, input timestamp, team prior rates, and
pregame probability. Later social Elo changes cannot alter it. Live score
projection consumes that fixed pregame probability.

Snapshots with a missing or unknown model, invalid probability, future input
time, or capture time more than five minutes from match creation fall back to
the versioned neutral 50% prior. API responses identify both the score model and
pregame model, plus the input timestamp. New virtual markets require a valid
versioned creation snapshot; newly created matches do not quote from social Elo.

Matches created before migration 0054 retain their immutable Elo creation
snapshot until they finish. Only newly created matches use the independent
model. Deploy migration 0054 before backend code so the nullable column exists
before new live matches capture snapshots.
