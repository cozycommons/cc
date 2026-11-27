# Sous vide: validate the model against measured cooks

Worktree: ~/worktrees/cozy-commons/t3-ae973955-27ddd6171c7b75e0, branch mh/sousvide-validation (from main).
Do not commit, push or open PRs; the parent owns delivery.

## Question
Does `backend/sousvide/model.py` (shipped constants: alpha 1.2e-7 m2/s, k 0.46, h_bath 95,
sear h 400 toward 100 C, h_air 10) reproduce *measured* center temperatures of real beef?

Three phases, judged separately:
1. Bath: center temperature vs time in a water bath (the planner's "time in bath").
2. Sear: center rise during and right after a pan sear.
3. Rest: center carryover and surface cooling while resting in air (the planner's
   hot-and-pull method needs ~+3 C of core rise over an ~18 min rest).

## Fixed baseline
The shipped constants, no fitting. Then, separately, a one-dataset fit with
`sousvide/calibrate.py` scored on the *other* datasets (held-out), to see whether one cook
generalises.

## Acceptance (meaningful targets)
- Bath: center RMS error <= 1.5 C and time-to-(target-1 C) within 10% on each dataset.
- Sear+rest: predicted peak core rise within 1.5 C of measured; time of peak within 5 min.
- Report every dataset, including the ones that fail. A failure is a finding, not a bug to tune away.

## Data format (one CSV per source)
`backend/sousvide/experiments/data/<slug>.csv` with a header comment block:
```
# source: full citation + URL
# how: table | digitized figure (tool, est. +/- C, +/- min) | raw log
# cut: ...   thickness_mm: ...   width_mm/length_mm or weight_g if known   bone: none|edge|middle
# start_c: ...   bath_c: ...  (or a bath column if it varies)
# phase notes: when the bag came out, sear method + pan temp + seconds per side, rest conditions
min,phase,core_c[,bath_c][,surface_c]
```
phase is one of bath|sear|rest. Celsius, minutes from the start of the cook.
Record unknowns as unknown; do not invent thickness or start temperature. If a source
omits a value the model needs, say what you assumed and give the plausible range.
Also add an entry to `backend/sousvide/experiments/data/SOURCES.md`: citation, what was
measured, quality (probe type, placement, n), and anything suspicious.

## Rules
- Stdlib only in `experiments/` (matches the existing modules). Run from backend/:
  `.venv/bin/python -m sousvide.experiments.<name>`.
- Measured data only. Model-computed tables (e.g. Baldwin's heating tables) are not
  validation data, though they may be listed as a cross-check, labelled as such.
- Prefer peer-reviewed or instrumented sources; blog probe logs are fine if the setup is stated.
