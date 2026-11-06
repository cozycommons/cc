# Cozy Bikes

Citi Bike's public trip history (New York since June 2013, Jersey City since
September 2015) as local Parquet you can query with DuckDB, and a wait-or-ride
answer for a full dock at `/bikes`.

## Source and license

Citi Bike publishes monthly trip archives at `https://s3.amazonaws.com/tripdata/`
under the [Citi Bike Data License Agreement](https://citibikenyc.com/data-sharing-policy).
The data has no rider identity. Bike ID, birth year and gender appear only
before February 2021; ride ID and bike type only from then on. Do not try to
re-identify riders.

## Ingest

The ingest is an offline command with its own lockfile. The API does not import
it or install DuckDB.

```sh
python3 -m venv ~/.venvs/cozy-bikes
~/.venvs/cozy-bikes/bin/pip install --require-hashes --only-binary=:all: -r backend/requirements-bikes.txt
cd backend && ~/.venvs/cozy-bikes/bin/python -m bikes.ingest --dry-run   # what would download
~/.venvs/cozy-bikes/bin/python -m bikes.ingest                           # everything
~/.venvs/cozy-bikes/bin/python -m bikes.ingest --from 2024-01 --system nyc
```

Data goes to `~/.local/share/cozy-bikes`, or `--data-dir`/`COZY_BIKES_DATA`. Rerun
the same command monthly. It skips archives whose S3 ETag it already holds and
re-converts any archive Citi Bike republishes.

It processes one archive at a time and deletes it after conversion. The defaults
(`--threads 2 --memory-limit 1GB`) run on a small box: DuckDB spills to the data
directory past the limit. Peak disk is the Parquet plus the largest archive
(about 1.6 GB) plus one extracted CSV.

An unknown CSV column or an unparseable start or end time stops the run with the
file name and a sample value. Nothing is dropped silently. Teach `SOURCE_NAMES`
or `TIMESTAMP_FORMATS` in `backend/bikes/ingest.py` the new shape, then rerun.

## Layout

```
~/.local/share/cozy-bikes/
  trips/system=nyc/year=2024/month=07/202407-citibike-tripdata_1.parquet
  trips/system=jc/year=2016/month=01/JC-20161-citibike-tripdata.parquet
  manifest.json   archive -> ETag, size, trips, Parquet files
  bikes.duckdb    `trips` view over all of the above
```

Each published CSV becomes one zstd Parquet file sorted by `started_at`. The
partition is the month of the archive (or of the CSV inside a year archive), so a
trip that crosses midnight at month end stays with the month that published it.

Every era maps to one schema:

| Column | Notes |
| --- | --- |
| `ride_id`, `rideable_type` | Feb 2021 on |
| `started_at`, `ended_at` | `TIMESTAMP`, local time, never null |
| `start_station_id`, `start_station_name`, `end_station_id`, `end_station_name` | IDs are text: legacy integers and current `4404.10` style differ |
| `start_lat`, `start_lng`, `end_lat`, `end_lng` | |
| `member_casual` | Legacy `Subscriber`/`Customer` map to `member`/`casual` |
| `bike_id`, `birth_year`, `gender` | Before Feb 2021; gender 0 unknown, 1 male, 2 female |
| `system`, `year`, `month` | Partition columns; filter on them to skip files |

## Query

```sh
duckdb ~/.local/share/cozy-bikes/bikes.duckdb
```

```sql
-- Trips per year
SELECT year, count(*) FROM trips WHERE system = 'nyc' GROUP BY year ORDER BY year;

-- Busiest start stations last summer
SELECT start_station_name, count(*) AS trips
FROM trips WHERE system = 'nyc' AND year = 2026 AND month BETWEEN 6 AND 8
GROUP BY ALL ORDER BY trips DESC LIMIT 10;
```

The view stores the data directory's absolute path. After moving the directory,
rerun the ingest to rewrite it.

## Wait at the nearest stations

`GET /bikes/wait?lat=&lng=` answers one question: which stations are nearest, and
how long until I have a bike there?

| Parameter | Default | Meaning |
| --- | --- | --- |
| `lat`, `lng` | required | Inside `SERVICE_AREA` |
| `need` | `bike` | `bike` to rent, `dock` to return |
| `at` | now | Any ISO time; without an offset it is New York time |
| `limit` | 3 | Nearest stations to return, 1 to 10 |
| `format` | `json` | `text` returns the sentence alone, for Siri |

Each station has its walk at 1 m/s crow-flies and two expected waits read at
arrival time: `wait_if_empty_min` (60 / arrivals per hour, when someone returns a
bike) and `wait_if_full_min` (60 / departures per hour, when someone takes one).
`null` means no such trips at that hour.

Without `at`, live GBFS adds `bikes`, `open_docks`, `status` (`available`,
`empty`, `full` or `closed`), `wait_min` (0 when it has what you need) and
`total_min` (walk plus wait). `best` is the returned station with the lowest
`total_min`. With `at`, there are no live counts for that time, so `live` is
false, `best` is null and the message gives both conditional waits for the
nearest station. Station names and places still come from the live feed.

```
$ curl 'https://<api>/bikes/wait?lat=40.7497&lng=-73.9915&format=text'
Walk to W 31 St & 7 Ave, a 1-minute walk: 71 bikes now.
$ curl 'https://<api>/bikes/wait?lat=40.7497&lng=-73.9915&at=2026-07-15T03:00&format=text'
At 3 AM on a weekday, the nearest station is W 31 St & 7 Ave, a 1-minute walk. If it is empty,
a bike usually comes back in about 72 minutes; if it is full, a dock usually opens in about 72 minutes.
```

### Latency

The request path is plain Python over in-memory data; DuckDB only builds the
model offline. The model (890 KB JSON) loads once per process in about 12 ms, and
the nearest-station search scans about 2,500 live stations. The GBFS feeds are
served from memory past their TTL (60 s status, 1 h locations) while one
background thread refreshes them, so warm requests never wait on Citi Bike.
Only a cold process, or status older than 5 minutes, fetches inline (about
350 ms; 503 if Citi Bike is down). Measured in-process on `/bikes/wait?limit=10`:
p50 2 ms, p99 4 ms warm; 2 ms max during a simulated 3 s refresh.

## Wait or ride

At a full dock a slot opens when someone takes a bike out, so the expected wait
is `60 / departures per hour` for that station, weekday or weekend, hour, and
season. `python -m bikes.model` (bikes venv) builds `backend/bikes/wait_model.json`
from the last 12 published months:

- per GBFS `short_name`, mean departures (`stations`) and arrivals (`arrivals`)
  per hour for 24 weekday and 24 weekend hours, in hundredths, averaged over the
  days since the station's first trip in the window;
- a system-wide factor per calendar month for the season;
- the median riding speed between stations, crow-flies, from real trips.

Rebuild and commit it after a monthly ingest. `--source s3` builds the same
model without the Parquet store: it streams the latest monthly archives through an
in-memory DuckDB, one archive on disk at a time, keeping only departures per
station, day and hour and a speed histogram.

`GET /bikes/wait-or-ride?lat=&lng=` reads live docks from
`gbfs.lyft.com/gbfs/2.3/bkn/en/` (station status cached 60 s, locations 1 h).
It answers for the station nearest the caller: dock now if it has room,
otherwise the expected wait against the best open dock within 1.5 km, priced as
the ride there plus a walk back at 1 m/s crow-flies. Add `format=text` for a
sentence that Siri can speak.

Siri Shortcut: Get Current Location, then Get Contents of URL
`https://<api>/bikes/wait-or-ride?format=text&lat=<Latitude>&lng=<Longitude>`, then
Speak Text.

## Explorer

`/bikes` also loads `frontend/public/bikes/explore.json`, written by the same
`bikes.model` run (559 KB, 203 KB gzipped by nginx): every station's name, mean
departure location and 48-slot profile from the model window, plus trips per month
for every ingested year. It draws each dock as a dot colored by departures per hour,
with an hour scrubber, a weekday/weekend toggle, a station's 24-hour profile and a
busiest-docks table, then trips per month since 2013. The last year feeds the map
and waits; every year feeds only trips per month, which the S3 build carries over.

Stations whose mean location falls outside `SERVICE_AREA` in `bikes/model.py` are
dropped: the trip files include Lyft test stations in Los Angeles. The API
validates caller locations against the same box.

Known simplifications: departures and arrivals are averaged, not live, and
arrivals exclude rebalancing vans; other riders already
waiting for the same dock and rebalancing vans are ignored; the full dock stands
in for your destination.
