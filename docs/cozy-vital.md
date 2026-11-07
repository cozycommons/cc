# VITAL Brooklyn occupancy

`/vital` shows how many people are at VITAL Brooklyn (221 N 14th St) now,
against the typical count for this weekday and hour, the quietest hour still
ahead today, and a week of typical counts by hour.

When is VITAL Brooklyn quiet? Its Brooklyn page shows a live
headcount from Safespace, which also serves the bare number as plain text:

```
$ curl https://display.safespace.io/value/live/a7796f34
191
```

Staff say the count covers the whole building, including the roof, patio and
classes, so it runs higher than the number of people on the walls.

## API

| Route | Returns |
| --- | --- |
| `GET /vital/now` | `people`, `at` (New York time of the fetch) and `typical` for that weekday and hour. The count is cached 60 s per process; a failed fetch returns 503 and later requests fail fast for 30 s. |
| `GET /vital/week` | The committed `backend/vital/week.json`: `hours[day][hour]` medians, Monday first, with `from`, `to` and `samples`. |

## Recording

`python -m vital.recorder` (run from `backend/`) polls that URL every minute (`--interval`)
and appends `recorded_at,people` (Unix seconds) to `occupancy.csv` under
`~/.local/share/cozy-vital` (or `--out`, `COZY_VITAL_DATA`). It uses only the
standard library. `--once` polls once, for cron. A failed poll prints a line and
writes nothing, so gaps are missing rows, never zeros.

## Best time to go

`python -m vital.busy` prints the median headcount for each weekday and hour over
the last 365 days (`--days`), then each day's busiest hour and its quietest open
hour (the quietest hour with at least a tenth of the peak, so closed hours do not
count).

`--write` saves the medians to `backend/vital/week.json`, which `/vital/week`
serves. Rebuild and commit it as recordings accumulate.

`--scrape FILE` adds the community scrape at
[dhoogs/brooklyn_vital_occupancy](https://github.com/dhoogs/brooklyn_vital_occupancy),
which polls the same URL from GitHub Actions and goes back to March 2022. Its
schedule has thinned to a few samples a day since early 2026, which is why we
record our own.

From that scrape, November 2025 to October 2026: weekdays peak at 7 PM
(about 300 people) and are quietest before 9 AM (40 to 70) or after 10 PM.
Midday on a weekday sits near 90. Weekends peak from 1 to 4 PM (about 250) and
are quiet early morning and after 8 PM.
