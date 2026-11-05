"""Build backend/bikes/wait_model.json from the local trip Parquet (see bikes.ingest).

A full dock frees a slot when someone takes a bike out, so the expected wait is
the time to the station's next departure. The model stores each station's mean
departures per hour by day type (weekday, weekend) and hour, over the last
`--months` published months, keyed by the station's GBFS `short_name`. A
system-wide factor per calendar month scales those averages for the season.
It also stores the riding speed between stations, measured crow-flies from real
trips, which the API uses to price riding to another dock.

    python -m bikes.model [--data-dir DIR] [--months 12]
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path

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


def build(con, months=12):
    # Ride IDs exist only from February 2021, and only those rows use GBFS short names.
    last = con.execute('SELECT max(year * 100 + month) FROM trips WHERE ride_id IS NOT NULL').fetchone()[0]
    if last is None:
        raise ValueError('No trips with ride IDs; run bikes.ingest first')
    window = month_window(last, months)
    first_day = dt.date(window[0] // 100, window[0] % 100, 1)
    year, month = divmod(window[-1], 100)
    end_day = dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1)
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW recent AS
        SELECT start_station_id AS station, started_at, ended_at, start_lat, start_lng, end_lat, end_lng,
               end_station_id, member_casual
        FROM trips
        WHERE year * 100 + month IN ({', '.join(map(str, window))}) AND ride_id IS NOT NULL
          AND started_at >= DATE '{first_day}' AND started_at < DATE '{end_day}' + 1
    """)
    # A station only counts days from its first departure in the window, so a
    # station opened in July is not averaged over the empty months before.
    rates = con.execute(f"""
        WITH days AS (
            SELECT d::DATE AS day, isodow(d) >= 6 AS weekend
            FROM generate_series(DATE '{first_day}', DATE '{end_day}', INTERVAL 1 DAY) AS t(d)
        ), opened AS (
            SELECT station, min(started_at)::DATE AS first FROM recent WHERE station IS NOT NULL GROUP BY station
        ), active AS (
            SELECT station, weekend, count(*) AS days FROM opened JOIN days ON day >= first GROUP BY ALL
        ), departures AS (
            SELECT station, isodow(started_at) >= 6 AS weekend, hour(started_at) AS hour, count(*) AS n
            FROM recent WHERE station IS NOT NULL GROUP BY ALL
        )
        SELECT station, weekend, hour, n / days AS per_hour
        FROM departures JOIN active USING (station, weekend)
    """).fetchall()
    stations = {}
    for station, weekend, hour, per_hour in rates:
        # Hundredths of a departure per hour; slot 0-23 weekday, 24-47 weekend.
        stations.setdefault(station, [0] * 48)[24 * weekend + hour] = round(per_hour * 100)

    daily = dict(con.execute("""
        SELECT month(started_at), count(*) / count(DISTINCT started_at::DATE) FROM recent GROUP BY ALL
    """).fetchall())
    mean = sum(daily.values()) / len(daily)
    month_factor = [round(daily.get(m, mean) / mean, 3) for m in range(1, 13)]

    ride_mps = con.execute(f"""
        SELECT median({HAVERSINE_M} / epoch(ended_at - started_at)) FROM recent
        WHERE end_station_id IS NOT NULL AND end_station_id <> station AND end_lat IS NOT NULL
          AND epoch(ended_at - started_at) BETWEEN 120 AND 3600
    """).fetchone()[0]
    return {
        'window': [f'{window[0] // 100}-{window[0] % 100:02d}', f'{window[-1] // 100}-{window[-1] % 100:02d}'],
        'ride_mps': round(ride_mps, 2),
        'month_factor': month_factor,
        'stations': dict(sorted(stations.items())),
    }


def main(argv=None):
    import duckdb
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data-dir', type=Path,
                        default=os.environ.get('COZY_BIKES_DATA', Path.home() / '.local/share/cozy-bikes'))
    parser.add_argument('--months', type=int, default=12)
    parser.add_argument('--out', type=Path, default=MODEL_PATH)
    args = parser.parse_args(argv)
    with duckdb.connect(str(Path(args.data_dir) / 'bikes.duckdb'), read_only=True) as con:
        model = build(con, args.months)
    args.out.write_text(json.dumps(model, separators=(',', ':')) + '\n')
    print(f"{len(model['stations'])} stations, {model['window'][0]} to {model['window'][1]}, "
          f"ride {model['ride_mps']} m/s crow-flies -> {args.out}")


if __name__ == '__main__':
    main()
