# Dice prediction evaluation — 2026-08-29

Production source: 50 eligible official ranked 2v2 games. Time split: first 35
train, next 15 holdout.

Dataset digest: `a07d9f417d0bff4346628d629911fb2f7d80fbd587e2f4d7b60a9ccb27adef84`.
Chronology: first `fb685797-4f0a-4479-9ac6-744476602089`, train cutoff
`51eee5be-e5a7-4dae-b081-c330440295ee`, holdout start
`1e36ee5d-8381-4106-ac09-a466b3dc70e2`, last
`ca5245b0-4d57-4c9d-8e27-14bd8eedb2a8`.

| Baseline | Brier (lower is better) | Log loss (lower is better) |
| --- | ---: | ---: |
| Independent prior-win-rate model | **0.2383** | **0.6701** |
| Neutral 50% | 0.2500 | 0.6931 |
| Existing social Elo (comparison only) | 0.2291 | 0.6509 |

The independent model clears its narrow promotion rule by improving on neutral.
It does not outperform social Elo, and 15 holdout games are too few for a claim
of general superiority. Full-data refit: coefficient `1.93085824`, model
`dice-pregame-logistic` v1.0.0, dataset `dice-prediction-dataset/v1`.

Calibration buckets on the holdout:

- 8 predictions below 50%: mean 44.3%, observed 25.0%;
- 7 predictions at or above 50%: mean 53.7%, observed 85.7%.

The wide bucket gaps are an explicit small-sample warning. Re-run the read-only
report as games accumulate and replace the artifact only through a new model
version and a fresh chronological evaluation.

The improvement over neutral also held at four expanding chronological splits:

| Train / test | Independent Brier | Neutral Brier |
| --- | ---: | ---: |
| 25 / 25 | 0.2444 | 0.2500 |
| 30 / 20 | 0.2402 | 0.2500 |
| 35 / 15 | 0.2383 | 0.2500 |
| 40 / 10 | 0.2340 | 0.2500 |

This supports an experimental live display. Virtual markets remain inside the
existing Dice live beta gate; they must not be promoted as calibrated wagering
odds without materially more games and tighter calibration evidence.
