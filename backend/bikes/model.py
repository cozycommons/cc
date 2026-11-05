"""Build backend/bikes/wait_model.json from Citi Bike trips.

A full dock frees a slot when someone takes a bike out, so the expected wait is
the time to the station's next departure. The model stores each station's mean
departures per hour by day type (weekday, weekend) and hour, over the last
`--months` published months, keyed by the station's GBFS `short_name`. A
system-wide factor per calendar month scales those averages for the season.
It also stores the riding speed between stations, measured crow-flies from real
trips, which the API uses to price riding to another dock.

Two sources feed the same aggregates:

    python -m bikes.model                 # local Parquet from bikes.ingest
    python -m bikes.model --source s3     # stream monthly CSVs into in-memory DuckDB

Both keep only departures per station, day and hour plus a histogram of ride
speeds, so the S3 build's memory stays small; its disk holds one archive at a time.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import tempfile

MODEL_PATH = Path(__file__).with_name('wait_model.json')

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
    con.execute('CREATE OR REPLACE TEMP TABLE hourly (station VARCHAR, day DATE, hour TINYINT, n INTEGER)')
    # Ride speeds in 0.01 m/s bins: an exact-enough median that sums across files.
    con.execute('CREATE OR REPLACE TEMP TABLE speeds (mps DOUBLE, n INTEGER)')


def aggregate(con, trips_sql, window):
    """Add departures and speeds from normalized trips (TRIP_COLUMNS) within the window."""
    first_day, last_day = window_days(window)
    # Ride IDs exist only from February 2021, and only those rows use GBFS short names.
    recent = (f"SELECT * FROM ({trips_sql}) WHERE ride_id IS NOT NULL AND start_station_id IS NOT NULL "
              f"AND started_at >= DATE '{first_day}' AND started_at < DATE '{last_day}' + 1")
    con.execute(f"""INSERT INTO hourly SELECT start_station_id, started_at::DATE, hour(started_at), count(*)
                    FROM ({recent}) GROUP BY ALL""")
    con.execute(f"""INSERT INTO speeds SELECT round({HAVERSINE_M} / epoch(ended_at - started_at), 2), count(*)
                    FROM ({recent})
                    WHERE end_station_id IS NOT NULL AND end_station_id <> start_station_id AND end_lat IS NOT NULL
                      AND epoch(ended_at - started_at) BETWEEN 120 AND 3600
                    GROUP BY ALL""")


def finalize(con, window):
    first_day, last_day = window_days(window)
    # A station only counts days from its first departure in the window, so a
    # station opened in July is not averaged over the empty months before.
    rates = con.execute(f"""
        WITH days AS (
            SELECT d::DATE AS day, isodow(d) >= 6 AS weekend
            FROM generate_series(DATE '{first_day}', DATE '{last_day}', INTERVAL 1 DAY) AS t(d)
        ), opened AS (
            SELECT station, min(day) AS first FROM hourly GROUP BY station
        ), active AS (
            SELECT station, weekend, count(*) AS days FROM opened JOIN days ON day >= first GROUP BY ALL
        ), departures AS (
            SELECT station, isodow(day) >= 6 AS weekend, hour, sum(n) AS n FROM hourly GROUP BY ALL
        )
        SELECT station, weekend, hour, n / days AS per_hour
        FROM departures JOIN active USING (station, weekend)
    """).fetchall()
    if not rates:
        raise ValueError('No trips with ride IDs in the window')
    stations = {}
    for station, weekend, hour, per_hour in rates:
        # Hundredths of a departure per hour; slot 0-23 weekday, 24-47 weekend.
        stations.setdefault(station, [0] * 48)[24 * weekend + hour] = round(per_hour * 100)

    daily = dict(con.execute("""
        SELECT month(day), sum(n) / count(DISTINCT day) FROM hourly GROUP BY ALL
    """).fetchall())
    mean = sum(daily.values()) / len(daily)
    month_factor = [round(daily.get(m, mean) / mean, 3) for m in range(1, 13)]
    ride_mps = con.execute('''
        WITH bins AS (SELECT mps, sum(n) AS n FROM speeds GROUP BY mps),
             running AS (SELECT mps, sum(n) OVER (ORDER BY mps) AS below, sum(n) OVER () AS total FROM bins)
        SELECT min(mps) FROM running WHERE below * 2 >= total
    ''').fetchone()[0]
    return {
        'window': [f'{window[0] // 100}-{window[0] % 100:02d}', f'{window[-1] // 100}-{window[-1] % 100:02d}'],
        'ride_mps': round(ride_mps, 2),
        'month_factor': month_factor,
        'stations': dict(sorted(stations.items())),
    }


def build(con, months=12):
    """From a connection with the bikes.ingest `trips` view."""
    last = con.execute('SELECT max(year * 100 + month) FROM trips WHERE ride_id IS NOT NULL').fetchone()[0]
    if last is None:
        raise ValueError('No trips with ride IDs; run bikes.ingest first')
    window = month_window(last, months)
    start_aggregates(con)
    aggregate(con, f"SELECT * FROM trips WHERE year * 100 + month IN ({', '.join(map(str, window))})", window)
    return finalize(con, window)


def build_from_source(months=12, memory_limit='1GB', threads=2, workdir=None, log=print):
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
            for csv_path in extract_csvs(zip_path, tmp):
                aggregate(con, normalized(con, csv_path), window)
            zip_path.unlink()
    return finalize(con, window)


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
    args = parser.parse_args(argv)
    if args.source == 's3':
        model = build_from_source(args.months, args.memory_limit, args.threads, args.workdir)
    else:
        with duckdb.connect(str(Path(args.data_dir) / 'bikes.duckdb'), read_only=True) as con:
            model = build(con, args.months)
    partial = args.out.with_suffix('.json.part')
    partial.write_text(json.dumps(model, separators=(',', ':')) + '\n')
    partial.replace(args.out)
    print(f"{len(model['stations'])} stations, {model['window'][0]} to {model['window'][1]}, "
          f"ride {model['ride_mps']} m/s crow-flies -> {args.out}")


if __name__ == '__main__':
    main()
