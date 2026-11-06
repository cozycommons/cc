"""Build backend/bikes/wait_model.json from Citi Bike trips.

A full dock frees a slot when someone takes a bike out, and an empty dock gets a
bike when someone ends a trip there, so the expected waits are the times to the
station's next departure and next arrival. The model stores each station's mean
departures (`stations`) and arrivals (`arrivals`) per hour by day type (weekday,
weekend) and hour, over the last `--months` published months, keyed by the
station's GBFS `short_name`. A
system-wide factor per calendar month scales those averages for the season.
It also stores the riding speed between stations, measured crow-flies from real
trips, which the API uses to price riding to another dock.

Two sources feed the same aggregates:

    python -m bikes.model                 # local Parquet from bikes.ingest
    python -m bikes.model --source s3     # stream monthly CSVs into in-memory DuckDB

Both keep only departures per station, day and hour plus a histogram of ride
speeds, so the S3 build's memory stays small; its disk holds one archive at a time.

Both also write frontend/public/bikes/explore.json for the /bikes explorer: station
names, places and hourly profiles from the same window, plus trips per month. The
last year is what the wait model and map need; trips per month covers every
ingested year, so only the Parquet build writes it and the S3 build keeps it.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import urllib.request

MODEL_PATH = Path(__file__).with_name('wait_model.json')
# (south, north, west, east): New York and Jersey City. The trip files also carry
# Lyft's test stations, such as "LA Metro Demo 2" in Los Angeles.
SERVICE_AREA = (40.45, 40.95, -74.30, -73.70)
EXPLORE_PATH = Path(__file__).resolve().parents[2] / 'frontend/public/bikes/explore.json'

HAVERSINE_M = """2 * 6371000 * asin(sqrt(
    pow(sin(radians(end_lat - start_lat) / 2), 2)
    + cos(radians(start_lat)) * cos(radians(end_lat)) * pow(sin(radians(end_lng - start_lng) / 2), 2)))"""


def month_window(last, months):
    """The `months` YYYYMM values ending at `last`, oldest first."""
    year, month = divmod(last, 100)
    window = []
    for _ in range(months):
        window.append(year * 100 + month)
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return window[::-1]


def window_days(window):
    first_day = dt.date(window[0] // 100, window[0] % 100, 1)
    year, month = divmod(window[-1], 100)
    return first_day, dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)


def start_aggregates(con):
    # kind 'd' counts departures (trip starts), 'a' arrivals (trip ends).
    con.execute('CREATE OR REPLACE TEMP TABLE hourly (station VARCHAR, kind VARCHAR, day DATE, hour TINYINT, n INTEGER)')
    # Ride speeds in 0.01 m/s bins: an exact-enough median that sums across files.
    con.execute('CREATE OR REPLACE TEMP TABLE speeds (mps DOUBLE, n INTEGER)')
    con.execute('CREATE OR REPLACE TEMP TABLE bike_types (kind VARCHAR, n INTEGER)')
    # Latest name and mean departure coordinates, summed so files combine.
    con.execute('''CREATE OR REPLACE TEMP TABLE places (station VARCHAR, name VARCHAR, seen TIMESTAMP,
                   lat DOUBLE, lng DOUBLE, n INTEGER)''')


def aggregate(con, trips_sql, window):
    """Add departures, arrivals and speeds from normalized trips (TRIP_COLUMNS) within the window."""
    first_day, last_day = window_days(window)
    # Ride IDs exist only from February 2021, and only those rows use GBFS short names.
    recent = (f"SELECT * FROM ({trips_sql}) WHERE ride_id IS NOT NULL AND start_station_id IS NOT NULL "
              f"AND started_at >= DATE '{first_day}' AND started_at < DATE '{last_day}' + 1")
    con.execute(f"""INSERT INTO hourly SELECT start_station_id, 'd', started_at::DATE, hour(started_at), count(*)
                    FROM ({recent}) GROUP BY ALL""")
    con.execute(f"""INSERT INTO hourly SELECT end_station_id, 'a', ended_at::DATE, hour(ended_at), count(*)
                    FROM ({recent}) WHERE end_station_id IS NOT NULL
                      AND ended_at >= DATE '{first_day}' AND ended_at < DATE '{last_day}' + 1 GROUP BY ALL""")
    con.execute(f"""INSERT INTO speeds SELECT round({HAVERSINE_M} / epoch(ended_at - started_at), 2), count(*)
                    FROM ({recent})
                    WHERE end_station_id IS NOT NULL AND end_station_id <> start_station_id AND end_lat IS NOT NULL
                      AND epoch(ended_at - started_at) BETWEEN 120 AND 3600
                    GROUP BY ALL""")
    con.execute(f"INSERT INTO bike_types SELECT rideable_type, count(*) FROM ({recent}) GROUP BY ALL")
    con.execute(f"""INSERT INTO places SELECT start_station_id, arg_max(start_station_name, started_at),
                    max(started_at), sum(start_lat), sum(start_lng), count(start_lat)
                    FROM ({recent}) GROUP BY ALL""")


# Central Park hourly weather for the model window. Fits use observed weather
# (bikes.weather_history) when the store has it; the Open-Meteo archive (CC BY 4.0)
# is the fallback. Held out over Oct 2025 to Sep 2026, factors fit on observations
# cut wet-hour error from 34% to 31% even when the live answer runs on Open-Meteo's
# forecast: the reanalysis misses a fifth of rain hours and smears its effect.
ARCHIVE_URL = ('https://archive-api.open-meteo.com/v1/archive?latitude=40.7812&longitude=-73.9665'
               '&start_date={}&end_date={}&hourly=temperature_2m,precipitation,snowfall&timezone=America%2FNew_York')
# Hours quieter than this (night) are too noisy to fit weather on.
WEATHER_MIN_EXPECTED = 50
WEATHER_MIN_HOURS = 20


def weather_history(first_day, last_day):
    """[(iso hour, temp C, precip mm, snow cm)] for the window, New York time."""
    with urllib.request.urlopen(ARCHIVE_URL.format(first_day, last_day), timeout=60) as response:
        hourly = json.load(response)['hourly']
    return list(zip(hourly['time'], hourly['temperature_2m'], hourly['precipitation'], hourly['snowfall']))


def observed_weather(con, first_day, last_day):
    """weather_history's rows from Central Park's METARs in the store's `weather` view.
    The observer says whether it snowed; the model says how much (METARs carry no depth)."""
    return con.execute("""
        SELECT strftime(o.hour, '%Y-%m-%dT%H:00'), o.temp_c, o.precip_mm,
               CASE WHEN o.snowing THEN greatest(coalesce(m.snow_cm, 0), 0.2) ELSE 0.0 END
        FROM weather o LEFT JOIN weather m ON m.hour = o.hour AND m.station = 'NYC' AND m.source = 'model'
        WHERE o.station = 'NYC' AND o.source = 'obs' AND o.hour >= ? AND o.hour < ? + 1
        ORDER BY 1""", [first_day, last_day]).fetchall()


def weather_table(con, window, rows):
    """Trip multipliers by weather: system departures against the model's own baseline
    (day type and hour mean, times the month factor), by sky, sky and heat, and after snow."""
    from .conditions import SNOW_AFTER_CM, heat, sky
    first_day, last_day = window_days(window)
    con.execute('CREATE OR REPLACE TEMP TABLE wx (ts TIMESTAMP, temp DOUBLE, precip DOUBLE, snow DOUBLE)')
    con.executemany('INSERT INTO wx VALUES (?, ?, ?, ?)', [r for r in rows if None not in r])
    hours = con.execute(f"""
        WITH sys AS (
            SELECT day + to_hours(hour) AS ts, sum(n) AS n FROM hourly WHERE kind = 'd' GROUP BY ALL
        ), h AS (
            SELECT wx.*, coalesce(sys.n, 0) AS n, isodow(wx.ts) >= 6 AS weekend, hour(wx.ts) AS hr, month(wx.ts) AS mo,
                   coalesce(sum(wx.snow) OVER (ORDER BY wx.ts ROWS BETWEEN 72 PRECEDING AND 1 PRECEDING), 0) AS snow72
            FROM wx LEFT JOIN sys USING (ts)
            WHERE wx.ts >= DATE '{first_day}' AND wx.ts < DATE '{last_day}' + 1
        ), dh AS (SELECT weekend, hr, avg(n) AS m FROM h GROUP BY ALL),
        mf AS (SELECT mo, avg(n) / (SELECT avg(n) FROM h) AS f FROM h GROUP BY mo)
        SELECT h.n, dh.m * mf.f AS expect, h.temp, h.precip, h.snow, h.snow72
        FROM h JOIN dh USING (weekend, hr) JOIN mf USING (mo)
    """).fetchall()
    groups = {}
    for n, expect, temp, precip, snow, snow72 in hours:
        if expect < WEATHER_MIN_EXPECTED:
            continue
        s = sky(precip, snow)
        keys = [('sky', s), ('sky_heat', f'{s}|{heat(temp)}')]
        if s in ('dry', 'drizzle') and snow72 >= SNOW_AFTER_CM:
            keys = [('after_snow', '')]
        for key in keys:
            total = groups.setdefault(key, [0.0, 0.0, 0])
            total[0] += n
            total[1] += expect
            total[2] += 1
    fitted = {key: round(n / expect, 3) for key, (n, expect, count) in groups.items() if count >= WEATHER_MIN_HOURS}
    return {
        'by_sky': {k: v for (kind, k), v in fitted.items() if kind == 'sky'},
        'by_sky_heat': {k: v for (kind, k), v in fitted.items() if kind == 'sky_heat'},
        'after_snow': fitted.get(('after_snow', '')),
    }


def finalize(con, window, weather=None):
    first_day, last_day = window_days(window)
    # A station only counts days from its first trip in the window, so a station
    # opened in July is not averaged over the empty months before.
    rates = con.execute(f"""
        WITH days AS (
            SELECT d::DATE AS day, isodow(d) >= 6 AS weekend
            FROM generate_series(DATE '{first_day}', DATE '{last_day}', INTERVAL 1 DAY) AS t(d)
        ), opened AS (
            SELECT station, min(day) AS first FROM hourly GROUP BY station
        ), active AS (
            SELECT station, weekend, count(*) AS days FROM opened JOIN days ON day >= first GROUP BY ALL
        ), counts AS (
            SELECT station, kind, isodow(day) >= 6 AS weekend, hour, sum(n) AS n FROM hourly GROUP BY ALL
        )
        SELECT station, kind, weekend, hour, n / days AS per_hour
        FROM counts JOIN active USING (station, weekend)
    """).fetchall()
    if not rates:
        raise ValueError('No trips with ride IDs in the window')
    by_kind = {'d': {}, 'a': {}}
    for station, kind, weekend, hour, per_hour in rates:
        # Hundredths of a trip per hour; slot 0-23 weekday, 24-47 weekend.
        by_kind[kind].setdefault(station, [0] * 48)[24 * weekend + hour] = round(per_hour * 100)

    daily = dict(con.execute("""
        SELECT month(day), sum(n) / count(DISTINCT day) FROM hourly WHERE kind = 'd' GROUP BY ALL
    """).fetchall())
    mean = sum(daily.values()) / len(daily)
    month_factor = [round(daily.get(m, mean) / mean, 3) for m in range(1, 13)]
    ride_mps = con.execute('''
        WITH bins AS (SELECT mps, sum(n) AS n FROM speeds GROUP BY mps),
             running AS (SELECT mps, sum(n) OVER (ORDER BY mps) AS below, sum(n) OVER () AS total FROM bins)
        SELECT min(mps) FROM running WHERE below * 2 >= total
    ''').fetchone()[0]
    ebike_share = con.execute('''
        SELECT sum(n) FILTER (WHERE kind = 'electric_bike') / sum(n) FROM bike_types
    ''').fetchone()[0] or 0.0
    south, north, west, east = SERVICE_AREA
    places = {station: (name, round(lat / n, 5), round(lng / n, 5)) for station, name, lat, lng, n in con.execute('''
        SELECT station, arg_max(name, seen), sum(lat), sum(lng), sum(n) FROM places GROUP BY station HAVING sum(n) > 0
    ''').fetchall() if south <= lat / n <= north and west <= lng / n <= east}
    # Departures define the station set: an arrival-only id has no place to show.
    stations = {s: slots for s, slots in by_kind['d'].items() if s in places}
    arrivals = {s: by_kind['a'].get(s, [0] * 48) for s in stations}
    return {
        'window': [f'{window[0] // 100}-{window[0] % 100:02d}', f'{window[-1] // 100}-{window[-1] % 100:02d}'],
        'ride_mps': round(ride_mps, 2),
        'month_factor': month_factor,
        # Share of trips on e-bikes, to split station rates for e-bike forecasts.
        'ebike_share': round(ebike_share, 3),
        # Trip multipliers by weather (bikes.conditions); absent when no weather history was given.
        **({'weather': weather_table(con, window, weather(*window_days(window)))} if weather else {}),
        'stations': dict(sorted(stations.items())),
        'arrivals': dict(sorted(arrivals.items())),
    }, places


def history(con):
    """Trips per month and system over every ingested year."""
    rows = con.execute('SELECT year, month, system, count(*) FROM trips GROUP BY ALL ORDER BY ALL').fetchall()
    months = sorted({f'{y}-{m:02d}' for y, m, _, _ in rows})
    series = {'month': months, 'nyc': [0] * len(months), 'jc': [0] * len(months)}
    for y, m, system, n in rows:
        series[system][months.index(f'{y}-{m:02d}')] = n
    return series


def explore(model, places, monthly):
    """Columnar payload for the /bikes explorer; stations without a place are left out."""
    ids = [s for s in model['stations'] if s in places]
    return {
        'window': model['window'],
        'stations': {
            'id': ids,
            'name': [places[s][0] for s in ids],
            'lat': [places[s][1] for s in ids],
            'lng': [places[s][2] for s in ids],
            'rates': [model['stations'][s] for s in ids],
        },
        'history': monthly,
    }


def build(con, months=12, weather=None):
    """From a connection with the bikes.ingest `trips` view."""
    last = con.execute('SELECT max(year * 100 + month) FROM trips WHERE ride_id IS NOT NULL').fetchone()[0]
    if last is None:
        raise ValueError('No trips with ride IDs; run bikes.ingest first')
    window = month_window(last, months)
    start_aggregates(con)
    aggregate(con, f"SELECT * FROM trips WHERE year * 100 + month IN ({', '.join(map(str, window))})", window)
    return (*finalize(con, window, weather), history(con))


def build_from_source(months=12, memory_limit='1GB', threads=2, workdir=None, log=print, weather=None):
    """Stream the latest monthly archives from S3 through an in-memory DuckDB."""
    import duckdb
    from .ingest import download, extract_csvs, list_archives, normalized, sql_literal
    monthly = [a for a in list_archives() if a.period[0] == a.period[1]]
    last = max(int(a.period[0]) for a in monthly if a.system == 'nyc')
    window = month_window(last, months)
    archives = [a for a in monthly if int(a.period[0]) in window]
    missing = set(window) - {int(a.period[0]) for a in archives if a.system == 'nyc'}
    if missing:
        raise ValueError(f'No monthly NYC archive for {sorted(missing)}; use the Parquet build')
    con = duckdb.connect()
    con.execute(f'SET memory_limit = {sql_literal(memory_limit)}')
    con.execute(f'SET threads = {int(threads)}')
    start_aggregates(con)
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        tmp = Path(tmp)
        con.execute(f"SET temp_directory = {sql_literal(str(tmp / 'spill'))}")
        for archive in sorted(archives, key=lambda a: a.key):
            log(f'streaming {archive.key}')
            zip_path = tmp / archive.key
            download(archive, zip_path)
            for csv_path, read in extract_csvs(zip_path, tmp):
                if read:
                    aggregate(con, normalized(con, csv_path), window)
            zip_path.unlink()
    return finalize(con, window, weather)


def main(argv=None):
    import duckdb
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', choices=('parquet', 's3'), default='parquet')
    parser.add_argument('--data-dir', type=Path,
                        default=os.environ.get('COZY_BIKES_DATA', Path.home() / '.local/share/cozy-bikes'))
    parser.add_argument('--months', type=int, default=12)
    parser.add_argument('--memory-limit', default='1GB')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--workdir', type=Path, help='scratch for one archive at a time (s3 source)')
    parser.add_argument('--out', type=Path, default=MODEL_PATH)
    parser.add_argument('--explore-out', type=Path, default=EXPLORE_PATH)
    args = parser.parse_args(argv)
    if args.source == 's3':
        model, places = build_from_source(args.months, args.memory_limit, args.threads, args.workdir,
                                          weather=weather_history)
        monthly = json.loads(args.explore_out.read_text())['history'] if args.explore_out.exists() else None
    else:
        with duckdb.connect(str(Path(args.data_dir) / 'bikes.duckdb'), read_only=True) as con:
            stored = con.execute("SELECT count(*) FROM duckdb_views() WHERE view_name = 'weather'").fetchone()[0]
            weather = (lambda first, last: observed_weather(con, first, last)) if stored else weather_history
            model, places, monthly = build(con, args.months, weather=weather)
    write_json(args.out, model)
    write_json(args.explore_out, explore(model, places, monthly))
    print(f"{len(model['stations'])} stations, {model['window'][0]} to {model['window'][1]}, "
          f"ride {model['ride_mps']} m/s crow-flies -> {args.out}")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix('.json.part')
    partial.write_text(json.dumps(value, separators=(',', ':')) + '\n')
    partial.replace(path)


if __name__ == '__main__':
    main()
