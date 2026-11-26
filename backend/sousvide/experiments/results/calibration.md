# Calibration from a probe log

## Recovering alpha and h from a synthetic log

Truth: alpha 1.35e-7, h 130, canonical ribeye from 5 C in a 57.5 C bath. Mean and spread over 12 noise seeds, alpha in 1e-7 m2/s. Fits start from alpha 1.20, h 95.

| log | probe noise C | alpha, h held at 95 | h kept | alpha when h kept | h when kept |
| --- | --- | --- | --- | --- | --- |
| every 5 min to 100 min | 0.1 | 1.44 +/- 0.00 | 5 of 12 | 1.40 +/- 0.04 | 109 +/- 12 |
| every 5 min to 100 min | 0.5 | 1.44 +/- 0.01 | 0 of 12 |  |  |
| every 5 min to 60 min (pulled early) | 0.1 | 1.44 +/- 0.00 | 4 of 12 | 1.42 +/- 0.03 | 101 +/- 9 |
| every 5 min to 60 min (pulled early) | 0.5 | 1.44 +/- 0.01 | 0 of 12 |  |  |
| every 10 min to 100 min | 0.1 | 1.44 +/- 0.00 | 3 of 12 | 1.46 +/- 0.04 | 93 +/- 10 |
| every 10 min to 100 min | 0.5 | 1.44 +/- 0.01 | 0 of 12 |  |  |
| every 1 min to 100 min (logging probe) | 0.1 | 1.44 +/- 0.00 | 12 of 12 | 1.35 +/- 0.02 | 133 +/- 10 |
| every 1 min to 100 min (logging probe) | 0.5 | 1.44 +/- 0.01 | 0 of 12 |  |  |
| every 5 min, tip 5 mm off mid-thickness | 0.1 | 1.50 +/- 0.00 | 0 of 12 |  |  |
| every 5 min, tip 5 mm off mid-thickness | 0.5 | 1.49 +/- 0.01 | 0 of 12 |  |  |
| every 5 min, tip 10 mm off mid-thickness | 0.1 | 1.65 +/- 0.00 | 0 of 12 |  |  |
| every 5 min, tip 10 mm off mid-thickness | 0.5 | 1.65 +/- 0.01 | 0 of 12 |  |  |
| every 5 min, thickness entered 2 mm thin (49) | 0.1 | 1.37 +/- 0.00 | 0 of 12 |  |  |
| every 5 min, thickness entered 2 mm thin (49) | 0.5 | 1.36 +/- 0.01 | 0 of 12 |  |  |
| every 5 min, start entered 3 C warm (8 C) | 0.1 | 1.37 +/- 0.00 | 0 of 12 |  |  |
| every 5 min, start entered 3 C warm (8 C) | 0.5 | 1.37 +/- 0.01 | 0 of 12 |  |  |

## What one calibration buys on the next cook

One log (5 min readings, 0.3 C noise) fitted alpha 1.44e-7 with h held at 95; the truth is alpha 1.35e-7 with h 130.

| next cook | true min | default constants | % off | fitted alpha, h still 95 | % off |
| --- | --- | --- | --- | --- | --- |
| same ribeye, classic 54.5 C | 159 | 192 | 20.7 | 160 | 0.5 |
| same ribeye, +3 C pulled | 79 | 98 | 23.6 | 79 | 0.4 |
| 38 mm boneless, 110 x 160, classic | 109 | 134 | 23.0 | 112 | 2.6 |
| 25 mm strip, classic | 55 | 70 | 27.1 | 58 | 6.1 |

