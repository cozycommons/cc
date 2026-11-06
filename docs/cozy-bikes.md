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

## Weather, holidays and alerts

The rates are yearly averages by station, day type, hour and month. What moves a
given hour off that average is mostly weather and holidays: over 2025-11 to
2026-10 the days furthest from normal were the Jan 25-30 snowstorm and cold snap
(7% to 27% of normal, and low for days after the snow stopped), Feb 23 (no trips:
a snowstorm), 43-56 mm rain days (19% to 34%), and Christmas and New Year's Day
(about a third). Events (marathons, parades) do not show citywide; they are local.

- `python -m bikes.weather_history` (bikes venv) stores hourly weather since June
  2013 as `<data>/weather/{obs,model}-<year>.parquet` and a `weather` view in
  `bikes.duckdb`: METAR observations from the Iowa Environmental Mesonet's ASOS
  archive (`obs`) and Open-Meteo's reanalysis (`model`), at Central Park, LaGuardia,
  JFK and Newark. Columns: `hour` (New York), `station`, `source`, `temp_c`,
  `precip_mm`, `snow_cm` (model only), `snowing`, `wx` (METAR codes). About 2 MB;
  finished years download once. NOAA's own access service stops in mid 2025.
- `bikes.model` fits trip multipliers against the model's own baseline: by sky
  (dry, drizzle, rain, heavy rain, snow) and temperature band, plus "snow on the
  ground" (2 cm or more in the past 72 hours, dry now). It uses Central Park's
  observations from the `weather` view when the store has them (snowing from the
  observer, depth from the model), else the Open-Meteo archive. Fitted on the
  year: heavy rain 0.26, rain 0.43, drizzle 0.79, snow 0.36 (0.17 below freezing),
  snow on the ground 0.59, dry 1.07. They are in `wait_model.json` as `weather`.

### Is Central Park enough?

Checked on Oct 2025 to Sep 2026, trips counted by the hour in each area, every
fifth day held out:

- The stations agree. When Central Park records 0.5 mm in an hour, LaGuardia is
  wet 93% of the time, Newark 86%, JFK 78%; daily totals correlate 0.93, 0.86 and
  0.82. Splitting trips by nearest station puts 90% in Central Park's area anyway
  (LaGuardia 8%, Newark under 1%, JFK almost none).
- Nearest-station weather predicts each area no better than Central Park (wet-hour
  error 34.4% against 34.5%). One point is enough.
- The source matters. Open-Meteo's reanalysis catches 81% of observed rain hours
  and 72% of heavy ones, and 35% of its rain hours were dry at the park. Fitted on
  modeled rain, the factors are diluted (heavy rain 0.47 instead of 0.31). Fitting
  on observations and still serving on the Open-Meteo forecast cut wet-hour error
  from 34.5% to 30.6%. Factors fit on observations and served on observations
  would reach 28%; a live METAR for the current hour is the next step.
- `bikes.conditions` fetches the live hourly forecast from `api.open-meteo.com`
  (cached 30 minutes, 4 s timeout; if it is down, rates are unadjusted) and scales
  every arrival and departure rate by its hour's factor, so waits and odds account
  for the weather at the time you arrive. Federal holidays use the weekend profile.
- Citi Bike's GBFS `system_alerts` (storm suspensions, closures for events) are
  passed through.
- Answers carry `conditions` (weather, holiday, factor, a `note`, alerts). `message`
  adds the note and alerts for speech; `answer` is the recommendation alone. The
  page shows the note and alerts above the answer when the hour is unusual.

## The /bikes page

Linked from the home shelf. Mobile first. The first decision is renting or
returning: the start screen is two large keys, **Find a bike** and **Find a
dock**, and one tap picks the mode and asks for your location. After that the
same two keys stay at the top of Near me (with "E-bikes only" under Find a
bike), and the page takes the mode's accent: moss for bikes, clay for docks. The
choice is remembered on the device, and `?need=bike|ebike|dock` sets it in a link.

Three tabs:

- **Near me**: Bike, E-bike or Dock. The answer sentence, a live map of stations
  within 800 m (colored 3+, 1–2, none or closed, with the five listed stations
  labeled by count), and a card per station with live classic, e-bike and dock
  counts, the chance it still has one when you arrive, the wait if it is gone
  and the expected minutes. Refreshes every minute while visible.
  `?lat=&lng=` sets the location, for shared links.
- **Plan**: from your location (or a station) to a searched station, leaving
  now or in 15, 30 or 60 minutes, optionally on an e-bike. Shows walk, start
  station, ride, end station and walk with live odds at each end, against
  walking the whole way. There is no address search: it would need a geocoder,
  a new outbound host.
- **Explore**: every dock by hour and trips per month (below).

`?tab=plan` or `?tab=explore` opens a tab.

### Live dock status and freshness

Every answer reads Citi Bike's live open docks (`num_docks_available`, which
already leaves out broken docks; `docks_disabled` counts those) and whether the
station accepts returns (`is_returning`, else status `closed`). Citi Bike rebuilds
the feed about every 60 s and each station's own report is typically 1 to 4
minutes old; the cache adds at most a minute. Responses carry `reported_s`, the
age of each station's report. A station silent for 15 minutes (`STALE_S`) is
`unknown`: no odds, never recommended, left out of plans, and drawn hollow on the
map. In November 2026 about two dozen stations had not reported for over an hour,
and a few send report times near 1970, which read as "over a day".

Every live JSON response carries `feed_updated_at` (Citi Bike's own
`last_updated` for the status copy we hold, New York time) and `age_s` (seconds
since this server fetched it). The page shows one line above Near me results and
Plan: "Citi Bike data from 10:57 PM · checked 10 s ago", counting every 5 s,
with Refresh. If Citi Bike's own time is over 5 minutes old it says Citi Bike
has not updated since then; if a refresh fails, the last results stay, dimmed,
with "Couldn't refresh. Showing Citi Bike data from 10:39 PM, 3 min ago" and
Retry.

The locate button (lucide `LocateFixed` on the Cozy Wabi key) sits beside the
Bike/E-bike/Dock toggle and in the Plan tab's From row, so a moved phone can
re-center without reloading.

### Interactive map

Near me's map moves: drag to pan, pinch or scroll to zoom (200 m to 3 km from
the center to each side), arrow keys and +/- when focused, and the corner keys
zoom or return to you. Tap a station for its live counts, the chance a bike or
dock is still there in 15 and 30 minutes, and Plan from here / Plan to here,
which opens Plan with that end filled in. The search box above flies to a
station by cross streets. During a gesture the drawing moves by a CSS transform
and is redrawn for the new view when the gesture ends, so phones stay smooth.
Minor streets drop out past 1.5 km. `/bikes?lat=&lng=&radius=&station=` opens
that view with the station's popup: answers link it as `map_url`.

### Street basemap

The map draws OpenStreetMap streets, bike lanes, parks and filled water (harbor,
Hudson, East River, lakes) from tiles in `backend/bikes/map/` (2,022 tiles,
6.0 MB). The API serves them at `/bikes/map/{name}.json` (gzipped, cached a day)
to the page, and draws the same tiles into `/bikes/map.png`; only our own
origins see where you look. There is no map library or CSP change.
`python -m bikes.basemap` (bikes venv) rebuilds them from BBBike's New York
extract (NYC, Jersey City, Hoboken) with DuckDB's spatial extension in under a
minute; rerun it a few times a year. The format is in the module docstring.

OpenStreetMap draws the harbor and tidal rivers only as coastline lines, so the
builder closes the coastline into areas and calls an area water when it holds
fewer than 10 ordinary street points (bridges, tunnels and piers do not count).
The sea starts at latitude 40.55, above a coastline gap at the Raritan River
mouth; no station is that far south. Data © OpenStreetMap contributors (ODbL),
credited under the map.

## For agents

Everything is public and read only, so an agent needs no connector or sign-in:
`GET /bikes/agents.txt` is a one-page guide (`backend/bikes/agents.txt`), and
`/openapi.json` has the schemas. `/bikes/stations?q=` searches live stations by
cross streets (street words folded: "west 31st street" finds "W 31 St"), and
`/bikes/stations/{id}` gives live counts plus the chance a bike, e-bike or dock
is still there in 15, 30 and 60 minutes. `/bikes/wait` takes `station=` and
`/bikes/plan` takes `from_station=`/`to_station=` in place of coordinates.
Landmarks and addresses are the agent's to geocode.

### Integrating an agent client

- **Any agent that can call HTTPS** (Claude Code, Codex, scripts): point it at
  `https://api.cozycommons.dev/bikes/agents.txt`. No key, no sign-in.
- **Meta Muse** builds custom connectors itself, in chat, from a public API: ask
  it to make a Cozy Bikes connector from that `agents.txt` URL. No OAuth is
  needed, which matters: Muse's custom OAuth connectors have been reported to
  lose access after about an hour (no refresh token).
- **OpenAI Dots** connects through OpenAI's plugin and app ecosystem; OpenAI
  has published no guide for adding a custom server to Dots. Until it does, give
  Dots the same `agents.txt` URL if it can browse, or use ChatGPT's custom
  connector path when that reaches Dots.
- **Maps in any agent, no MCP needed**: `/bikes/wait`, `/bikes/plan` and
  `/bikes/stations/{id}` answers carry `map_url` (the interactive page on that
  view, station open) and `map_image` (`/bikes/map.png`: a 640 x 640 PNG of
  live stations over the streets, colored by bikes or docks, with counts on the
  stations that matter). Nearly every chat agent can show an image or a link, so
  this is the visual path for Muse and Dots today. Renders take 70 to 150 ms
  and are shared for a minute per view. `COMMONS_SITE_URL` and `PUBLIC_API_URL`
  set the link origins (default cozycommons.dev, api.cozycommons.dev).
- **Rich UI in the chat (not built)**: hosts that support MCP Apps (spec
  2026-01-26, `io.modelcontextprotocol/ui`; Claude and ChatGPT) render a tool's
  `ui://` HTML resource inline. If we want Muse, Dots or ChatGPT to show station
  cards and the map instead of text, add a public read-only MCP server at
  `/bikes/mcp` (fastmcp 3.4 supports `@mcp.tool(app=AppConfig(resource_uri=...))`)
  whose tools return the same JSON as `structuredContent`, plus one self-contained
  `ui://cozy-bikes/stations.html` that renders it. Clients without MCP Apps still
  get the text. A new public endpoint in `main:app` is in `docs/security.md`'s
  review scope.

## Live stations and trip plans

`GET /bikes/live` returns every station in service, columnar (`id`, `name`,
`lat`, `lng`, `bikes`, `ebikes`, `docks`, `flags` with 1 renting and 2
returning) and the status feed's age. It is gzipped (46 KB for about 2,500
stations).

`GET /bikes/plan?from_lat=&from_lng=&to_lat=&to_lng=[&depart=][&ebike=true]`
tries the four nearest renting stations within 1 km of the origin against the
four nearest returning stations of the destination. Each pair costs walk, ride
(`ride_mps`) and walk, plus each end's refill wait weighted by the chance it is
empty or full on arrival. The lowest expected minutes wins; `walk_only_min`
compares walking. Live odds cover departures up to an hour ahead.

### Arrival odds

`forecast.py` treats a station's available bikes as a birth-death chain bounded
by 0 and its docks in service (bikes plus open docks now). From the live count
it steps in 10 s ticks with the station's arrival and departure rates for each
hour it crosses. `chance` is the probability it is not empty (or, for a dock,
not full) on arrival. E-bikes use the same chain with rates scaled by the
system e-bike share of trips (`ebike_share`, 72% for 2025-11 to 2026-10).
`/bikes/wait` ranks stations by expected minutes: walk plus
`(1 - chance) * refill wait`, with an hour for a station that never refills at
that hour.

## Recording live status

The trip files do not say how full a station was, so measuring fullness by hour
needs a record of the live feed. `python -m bikes.recorder` polls station status
every minute and appends a row per station whose report changed to
`status-YYYY-MM-DD.csv.gz` under `~/.local/share/cozy-bikes/status` (or `--out`,
`COZY_BIKES_STATUS`). It uses only the standard library and `gbfs.lyft.com`.
`--once` polls once, for cron. Nothing reads these files yet: after a few weeks
they can replace the forecast's trip-based rates with observed fullness, which
includes rebalancing.

## Wait at the nearest stations

`GET /bikes/wait?lat=&lng=` answers one question: which stations are nearest, and
how long until I have a bike there?

| Parameter | Default | Meaning |
| --- | --- | --- |
| `lat`, `lng` | required | Inside `SERVICE_AREA` |
| `need` | `bike` | `bike` or `ebike` to rent, `dock` to return |
| `at` | now | Any ISO time; without an offset it is New York time |
| `limit` | 3 | Nearest stations to return, 1 to 10 |
| `format` | `json` | `text` returns the sentence alone, for Siri |

Each station has its walk at 1 m/s crow-flies and two expected waits read at
arrival time: `wait_if_empty_min` (60 / arrivals per hour, when someone returns a
bike) and `wait_if_full_min` (60 / departures per hour, when someone takes one).
`null` means no such trips at that hour.

Without `at`, live GBFS adds `bikes`, `ebikes`, `open_docks`, `status`
(`available`, `empty`, `full` or `closed`), `chance` (it has what you need on
arrival), `wait_min` (the refill wait if it does not) and `expected_min`.
`best` is the returned station with the lowest `expected_min`. With `at`, there are no live counts for that time, so `live` is
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

Siri Shortcut (as the page shows): Get Current Location, then Get Contents of URL
`https://<api>/bikes/wait?format=text&lat=<Latitude>&lng=<Longitude>`, then Speak
Text. Add `&need=dock` for the docking version. `/bikes/wait-or-ride` stays for
shortcuts that already use it.

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
