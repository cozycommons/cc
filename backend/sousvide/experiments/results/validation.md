# Validation against measured cooks

Question: does `model.py` at its shipped constants (alpha 1.2e-7 m2/s, k 0.46, h_bath 95, sear h 400 toward 100 C,
h_air 10) reproduce measured core temperatures of real beef? Targets are the brief's: bath RMS <= 1.5 C and time
within 10 %; sear and rest peak rise within 1.5 C and peak time within 5 min.

This section is written by hand from the tables below. Everything under "Generated output" is
`python -m sousvide.experiments.validate`, unedited. Sources and their quality: `../data/SOURCES.md`.

## Verdict

**Bath: fails on all five datasets, always in the same direction. The model heats too slowly.**
Core RMS is 2.8 to 12.9 C and the time to temperature is 40 to 126 % long. The two thin, well-instrumented
laboratory cooks (25 mm brisket strips and 25.4 mm strip loin at 71 to 72.5 C) are the worst: the model takes about
twice the measured time. The three 57 to 64 mm pieces are each about 40 % long.

The size of the miss points at the bath coefficient more than at the meat. With alpha held at 1.2e-7, raising
h_bath from 95 to 1000 cuts the time error on the thick pieces from 40 % to 9 to 13 %, and no value of h rescues
the thin ones (19 to 25 % long even with the surface at bath temperature). With alpha at the top of its sourced
range (1.44e-7) and h_bath 1000, all five land within 12 % on time and three within 6 % (RMS 1.2 to 3.5 C).
No single pair passes every dataset: the best row in the table passes two of five. What I would change, if this were mine to
change: h_bath from 95 to somewhere in 400 to 1000 and alpha from 1.2e-7 to about 1.4e-7. That shortens a planned
bath by roughly 25 to 35 % on thick steaks and more on thin ones. I have not changed either.

Caveats that could shrink the miss but not remove it: these are 60 to 80 C cooks of lean round, brisket and strip
loin, hotter than a 54 C steak bath, and meat shrinks and stiffens above 60 C; the DeVane time origin is uncertain
by a minute and its thickness is the frozen cutting target; Logsdon suspects an off-centre probe. An off-centre
probe reads fast, which is the direction of the error, but five independent setups agreeing makes that an unlikely
whole explanation.

**Leave-one-out fit: one cook does not generalise.** `calibrate.fit` holds h at 95 unless the log pins it, so the
fitted alpha absorbs the missing surface conductance and lands at 1.46 to 2.50e-7 (one on the bound), outside
the sourced range for beef. Those alphas transfer only between like thicknesses: brisket to strip loin (both
25 mm) scores RMS 3.2 C and strip loin to brisket 0.8 C, but either one applied to the 57 to 64 mm pieces is about
30 % fast, and a thick-piece fit applied to the thin ones is 34 to 86 % slow. Held-out passes: 2 of 16. This is
what a wrong h looks like: Bi changes with thickness, so an alpha that hides it at one thickness cannot at
another. A fit of alpha alone is a per-steak patch, not a calibration.

**Sear: the shipped contact delivers too little heat on a long sear from raw. On the planner's own short
post-bath sears the evidence is too weak to say.**
The only instrumented data (Moya et al., pan at 215 C, raw strips, 3 to 13 minute cooks) has the core 11 to
14 C hotter than the model at the end of a 19 or 26 mm "done" cook, rebuilt with one face on the pan at a time.
Even a surface pinned at 100 C leaves the model 5 to 9 C short there, so in that cook the meat under the crust
ran above 100 C. A contact of h 400 toward about 125 C brings the three 19 mm cooks within 3 C (-2.8, +1.0,
+2.0) where the shipped 100 C gives -11.1, -4.9, -0.8. That agrees with the 120 C face temperature in the authors'
own fitted model. The 34 mm file fails under every contact tried and is probably a probe or geometry problem
(see SOURCES.md), so it should not drive anything.

For the sear the planner actually plans (45 to 60 s a side on a steak already at 50 C), the only readings are
one blog's single thermometer values with the time of reading not stated. The model's range covers the 52 C
ribeye (measured +8.0 C, model up to +7.7) and is 1.3 to 1.6 C under the 40 mm fillet (measured +2.1), and it is
4 C under the 47 C ribeye, a reading that cannot be a true core (same 60 C as the 52 C cook). Read generously,
the shipped sear is not contradicted for short sears; read strictly, 1 of 4 passes and every miss is on the low
side. The two refrigerator-start cooks miss by 14 to 33 C under every contact up to h 400 toward 150 C, which says
the assumed 5 C start or the probe position is wrong, not that a sear can do that.

What I would change: nothing in h_sear, and I would not trust "toward 100 C" beyond about a minute a side. If
the surface target went to 125 C, the existing sweep (`sear.md`) puts the canonical 51 mm ribeye's carryover
at roughly +1 C more than shipped and a 25 mm steak's at roughly +3 C more (interpolated between its 100 and
150 C rows, not run). The planner's quoted sear range (half to double h) does not cover that case, and
`SEAR_SPREAD`'s own note says so. Also worth knowing: rebuilding these cooks with both faces at once for half the
time (the planner's convention) instead of one face at a time loses a further 5 to 6 C on the long Moya cooks and
almost nothing on the 1 minute sears.

**Rest: not validated. There is no usable data.**
No measured core series through a rest in air was found with enough stated (thickness, cook history, timing) to
rebuild: the sources either publish images, refuse automated reading, or omit the geometry. So h_air 10, the
predicted +3 C over about 18 minutes for the hot-and-pull method, and every "peak time" in the planner are
untested here. The one rest reading in the set (a chilled fillet after 5 minutes in foil) fails by 33 C for
reasons that are about its unknown start, not the rest. A logged probe through one real sear and rest would be
worth more than everything in the sear and rest tables.

## What was and was not measured

- Bath: five independent sources, 13 to 54 readings each, four digitized from figures and one from a table.
- Sear: one peer-reviewed source (five curves read by eye from blurry figures, about +/- 1.5 C on top of the
  paper's +/- 2 to 3 C band) and one blog (five single readings, thermometer and timing unstated).
- Pan surface temperature or heat flux measured during a sear: none obtained. The published contact coefficients
  listed in SOURCES.md (120 to 900 W/(m2 K)) are all defined against the plate's temperature, so they cannot be
  compared with "h 400 toward 100 C" without a model of the evaporation at the face.
- Rest: nothing.

# Generated output

## Validation against measured cooks

15 datasets in data/: 5 with a bath log, 10 with sear or rest readings. Sources and their quality: data/SOURCES.md.

### Values the sources do not give

| dataset | assumed in the header |
| --- | --- |
| rest_stefan2020_fillet40_chilled | start_c, weight_g, air_c |
| sear_stefan2020_fillet40_bath50 | start_c, weight_g, air_c |
| sear_stefan2020_ribeye20_bath47 | start_c, weight_g, air_c |
| sear_stefan2020_ribeye20_bath52 | start_c, air_c |
| sear_stefan2020_ribeye20_chilled | start_c, air_c |

### Bath, shipped constants

The core through model.Body with alpha 1.2e-7, k 0.46, h_bath 95, the logged bath where there is a bath column. The time is to the bath target minus 1 C, or to the highest logged core when the log stops before that; n/a means the model had not got there in 4 times the logged bath.

| dataset | mm | readings | core RMS C | mean model - measured C | time to reach C | measured min | model min | time off % | RMS <= 1.5 and time within 10 % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bath_akmal_brisket | 25 x 30 x 100 | 41 | 12.79 | -10.08 | 70.0 | 20.8 | 42.5 | 104.1 | FAIL |
| bath_devane_striploin | 25.4 | 54 | 12.87 | -10.96 | 71.5 | 31.0 | 69.9 | 125.6 | FAIL |
| bath_fareh_eye_round | 60 x 60 x 100 | 27 | 7.75 | -6.19 | 59.0 | 95.0 | 134.0 | 41.1 | FAIL |
| bath_ishiwatari_round | 57.4 x 71 x 107 | 13 | 12.17 | -10.91 | 58.0 (log stops short of bath - 1) | 39.7 | 56.0 | 41.1 | FAIL |
| bath_logsdon_steak | 63.5 | 18 | 2.77 | -2.72 | 54.0 | 220.4 | 308.3 | 39.9 | FAIL |

### The bath coefficient, tested directly

Nothing fitted: the same scoring with h_bath and alpha set by hand. h 1e4 is a surface at bath temperature.

| alpha 1e-7 m2/s | h_bath | bath_akmal_brisket: RMS C / time off % | bath_devane_striploin: RMS C / time off % | bath_fareh_eye_round: RMS C / time off % | bath_ishiwatari_round: RMS C / time off % | bath_logsdon_steak: RMS C / time off % | passes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1.20 | 95 | 12.79 / 104.1 | 12.87 / 125.6 | 7.75 / 41.1 | 12.17 / 41.1 | 2.77 / 39.9 | 0 of 5 |
| 1.20 | 200 | 8.32 / 58.5 | 9.11 / 71.1 | 5.57 / 24.2 | 9.29 / 25.2 | 0.94 / 21.9 | 0 of 5 |
| 1.20 | 400 | 5.91 / 38.0 | 7.13 / 47.3 | 4.49 / 16.7 | 7.68 / 17.7 | 0.54 / 14.0 | 0 of 5 |
| 1.20 | 1000 | 4.30 / 25.9 | 5.83 / 33.4 | 3.82 / 12.2 | 6.61 / 13.1 | 0.80 / 9.3 | 1 of 5 |
| 1.20 | 10000 | 3.26 / 18.7 | 5.01 / 25.3 | 3.40 / 9.6 | 5.93 / 10.3 | 1.03 / 6.5 | 1 of 5 |
| 1.44 | 95 | 9.06 / 70.2 | 10.07 / 88.2 | 4.46 / 18.3 | 7.41 / 17.6 | 0.57 / 16.6 | 0 of 5 |
| 1.44 | 200 | 4.87 / 32.2 | 6.53 / 42.8 | 2.60 / 4.6 | 4.46 / 4.3 | 1.50 / 1.6 | 0 of 5 |
| 1.44 | 400 | 2.64 / 15.2 | 4.69 / 22.9 | 1.84 / -1.5 | 3.12 / -1.9 | 2.13 / -5.0 | 0 of 5 |
| 1.44 | 1000 | 1.17 / 5.0 | 3.50 / 11.4 | 1.53 / -5.2 | 2.54 / -5.7 | 2.49 / -8.9 | 1 of 5 |
| 1.44 | 10000 | 0.35 / -0.9 | 2.75 / 4.6 | 1.45 / -7.5 | 2.41 / -8.0 | 2.70 / -11.2 | 2 of 5 |

### Sear and rest, shipped constants

Rise is the core above its temperature when the sear began. "Model rise" is at the reading times; where the source does not say when it read the core, it is the model's range over the scheduled rest and the error is the distance to that range. Peak time is scored only with three or more rest readings.

| dataset | rebuilt | readings | measured rise C | model rise C | rise error C | core RMS C | model peak rise C | model peak, min after the pull | peak time error min | rise within 1.5 C |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rest_stefan2020_fillet40_chilled | planner | 1 | 36.0 | 3.0 | -33.0 | 33.0 | 3.0 | 7.0 | n/a | FAIL |
| rest_stefan2020_fillet40_chilled | as cooked | 1 | 36.0 | 3.5 | -32.5 | 32.5 | 3.5 | 7.0 | n/a | FAIL |
| sear_moya2021_19mm_done | planner | 13 | 38.0 | 22.1 | -15.9 | 12.5 | 22.1 | 7.0 | n/a | FAIL |
| sear_moya2021_19mm_done | as cooked | 13 | 38.0 | 26.9 | -11.1 | 8.8 | 26.9 | 7.0 | n/a | FAIL |
| sear_moya2021_19mm_medium | planner | 9 | 23.7 | 12.9 | -10.8 | 7.2 | 12.9 | 5.0 | n/a | FAIL |
| sear_moya2021_19mm_medium | as cooked | 9 | 23.7 | 18.8 | -4.9 | 3.4 | 18.8 | 5.0 | n/a | FAIL |
| sear_moya2021_19mm_veryrare | planner | 5 | 10.0 | 4.1 | -5.9 | 3.5 | 4.1 | 3.0 | n/a | FAIL |
| sear_moya2021_19mm_veryrare | as cooked | 5 | 10.0 | 9.2 | -0.8 | 0.5 | 9.2 | 3.0 | n/a | pass |
| sear_moya2021_26mm_done | planner | 10 | 39.3 | 20.9 | -18.4 | 12.7 | 20.9 | 12.0 | n/a | FAIL |
| sear_moya2021_26mm_done | as cooked | 10 | 39.3 | 25.7 | -13.6 | 9.1 | 25.7 | 12.0 | n/a | FAIL |
| sear_moya2021_34mm_done | planner | 9 | 39.4 | 9.7 | -29.7 | 21.5 | 9.7 | 12.8 | n/a | FAIL |
| sear_moya2021_34mm_done | as cooked | 9 | 39.4 | 15.7 | -23.7 | 17.6 | 15.7 | 12.8 | n/a | FAIL |
| sear_stefan2020_fillet40_bath50 | planner | 1 | 2.1 | 0.0 to 0.5 | -1.6 | n/a | 0.5 | 5.0 | n/a | FAIL |
| sear_stefan2020_fillet40_bath50 | as cooked | 1 | 2.1 | 0.0 to 0.8 | -1.3 | n/a | 0.8 | 5.0 | n/a | pass |
| sear_stefan2020_ribeye20_bath47 | planner | 1 | 13.0 | 0.5 to 8.7 | -4.3 | n/a | 8.7 | 5.0 | n/a | FAIL |
| sear_stefan2020_ribeye20_bath47 | as cooked | 1 | 13.0 | 2.3 to 8.8 | -4.2 | n/a | 8.8 | 5.0 | n/a | FAIL |
| sear_stefan2020_ribeye20_bath52 | planner | 1 | 8.0 | 0.5 to 7.7 | -0.3 | n/a | 7.7 | 5.0 | n/a | pass |
| sear_stefan2020_ribeye20_bath52 | as cooked | 1 | 8.0 | 2.0 to 7.8 | -0.2 | n/a | 7.8 | 5.0 | n/a | pass |
| sear_stefan2020_ribeye20_chilled | planner | 1 | 40.0 | 0.9 to 16.5 | -23.5 | n/a | 16.5 | 5.0 | n/a | FAIL |
| sear_stefan2020_ribeye20_chilled | as cooked | 1 | 40.0 | 4.2 to 17.3 | -22.7 | n/a | 17.3 | 5.0 | n/a | FAIL |

### The sear boundary, tested directly

Rise error in C (model - measured) with only the pan contact changed. A positive number means the model heats too much.

| sear (as cooked) | rest_stefan2020_fillet40_chilled | sear_moya2021_19mm_done | sear_moya2021_19mm_medium | sear_moya2021_19mm_veryrare | sear_moya2021_26mm_done | sear_moya2021_34mm_done | sear_stefan2020_fillet40_bath50 | sear_stefan2020_ribeye20_bath47 | sear_stefan2020_ribeye20_bath52 | sear_stefan2020_ribeye20_chilled | RMS of the errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| shipped: h 400 to 100 C | -32.5 | -11.1 | -4.9 | -0.8 | -13.6 | -23.7 | -1.3 | -4.2 | -0.2 | -22.7 | 15.8 |
| h 800 to 100 C | -31.9 | -8.3 | -2.5 | 0.7 | -11.5 | -22.5 | -1.2 | -2.4 | 0.0 | -19.5 | 14.6 |
| surface pinned at 100 C | -31.0 | -4.9 | 0.5 | 2.7 | -9.0 | -21.0 | -1.0 | -0.1 | 0.0 | -15.4 | 13.2 |
| h 400 to 125 C | -31.6 | -2.8 | 1.0 | 2.0 | -5.8 | -19.0 | -1.0 | 0.0 | 0.0 | -18.2 | 13.2 |
| h 400 to 150 C | -30.7 | 5.5 | 6.8 | 4.9 | 2.1 | -14.3 | -0.6 | 0.0 | 0.0 | -13.8 | 12.0 |
| h 400 to 200 C | -29.0 | 22.1 | 18.5 | 10.6 | 17.8 | -4.8 | 0.0 | 0.0 | 0.0 | -4.9 | 14.6 |
| h 120 to 215 C (Moya et al. contact, no evaporation) | -31.7 | 6.4 | 5.9 | 3.3 | 5.7 | -12.0 | -0.7 | 0.0 | 0.0 | -18.5 | 12.7 |
| shipped sear, alpha 1.44e-7 (top of the sourced range) | -30.8 | -6.5 | -0.6 | 2.2 | -9.2 | -20.0 | -0.7 | -2.7 | 0.0 | -19.4 | 13.7 |

### Leave-one-out fit

calibrate.fit on one bath log (h kept only when the log pins it), then every other bath dataset scored with that fit. A log with a varying bath is scored but never fitted on: calibrate.fit takes one bath temperature.

| fitted on | alpha 1e-7 m2/s | h_bath | own RMS before C | own RMS after C | bath_akmal_brisket: RMS C / time off % | bath_devane_striploin: RMS C / time off % | bath_fareh_eye_round: RMS C / time off % | bath_ishiwatari_round: RMS C / time off % | bath_logsdon_steak: RMS C / time off % | held-out passes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bath_akmal_brisket | 2.40 | 95 | 12.79 | 0.49 | fitted on | 3.21 / 13.5 | 3.97 / -30.0 | 8.27 / -29.3 | 4.21 / -29.9 | 0 of 4 |
| bath_devane_striploin | 2.50 (on a bound) | 95 | 12.87 | 2.71 | 0.82 / -1.6 | fitted on | 4.51 / -32.8 | 9.46 / -32.2 | 4.40 / -32.8 | 1 of 4 |
| bath_ishiwatari_round | 1.84 | 95 | 12.17 | 2.25 | 4.52 / 33.8 | 6.63 / 47.9 | 1.33 / -5.5 | fitted on | 2.47 / -8.5 | 1 of 4 |
| bath_logsdon_steak | 1.46 | 95 | 2.77 | 0.55 | 8.82 / 68.2 | 9.89 / 85.9 | 4.25 / 17.0 | 7.08 / 16.2 | fitted on | 0 of 4 |

