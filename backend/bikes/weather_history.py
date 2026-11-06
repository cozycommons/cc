"""Hourly weather history for the Citi Bike area, observed and modeled, as Parquet.

Two sources, four places, June 2013 on:

- `obs`: airport-style observations (METAR) from the Iowa Environmental Mesonet's
  ASOS archive for Central Park (NYC), LaGuardia (LGA), JFK and Newark (EWR).
  NOAA's own access service has no 2026 data yet; IEM is current.
- `model`: Open-Meteo's historical archive (reanalysis) at the same four points,
  the same kind of data as the live forecast bikes.conditions uses.

    <data>/weather/<source>-<year>.parquet
        hour (TIMESTAMP, New York), station, source, temp_c, precip_mm, snow_cm, snowing, wx

`precip_mm` is liquid-equivalent for the hour; `snow_cm` is model snowfall (null
for obs); `snowing` is from the observer's weather codes or model snowfall;
`wx` keeps the METAR codes. Finished years are fetched once; the current year is
refetched each run. bikes.duckdb gets a `weather` view.

    python -m bikes.weather_history [--data-dir DIR] [--first-year 2013]
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import urllib.parse
import urllib.request

STATIONS = {
    # METAR id: (lat, lng), the observing station's own position
    'NYC': (40.7790, -73.9693),
    'LGA': (40.7794, -73.8803),
    'JFK': (40.6386, -73.7622),
    'EWR': (40.6827, -74.1693),
}
FIRST_DAY = dt.date(2013, 6, 1)  # Citi Bike opened
IEM_URL = 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py'
ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
COLUMNS = 'hour TIMESTAMP, station VARCHAR, source VARCHAR, temp_c DOUBLE, precip_mm DOUBLE, ' \
          'snow_cm DOUBLE, snowing BOOLEAN, wx VARCHAR'


def get(url, timeout=300):
    request = urllib.request.Request(url, headers={'User-Agent': 'cozy-commons bikes weather history'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode()


def observed(first, last):
    """Routine hourly METARs for every station, one row per station and hour."""
    query = [('station', s) for s in STATIONS] + [
        ('data', 'tmpc'), ('data', 'p01m'), ('data', 'wxcodes'),
        ('year1', first.year), ('month1', first.month), ('day1', first.day),
        ('year2', last.year), ('month2', last.month), ('day2', last.day),
        ('tz', 'America/New_York'), ('format', 'onlycomma'), ('latlon', 'no'),
        ('missing', 'null'), ('trace', '0.0001'), ('report_type', '3'),
    ]
    rows = {}
    for row in csv.DictReader(io.StringIO(get(f'{IEM_URL}?{urllib.parse.urlencode(query)}'))):
        # A routine report at :51 closes the hour it falls in (its precipitation is the past hour's).
        hour = dt.datetime.strptime(row['valid'], '%Y-%m-%d %H:%M').replace(minute=0)
        if not first <= hour.date() <= last:
            continue
        temp = float(row['tmpc']) if row['tmpc'] not in ('null', '') else None
        precip = float(row['p01m']) if row['p01m'] not in ('null', '') else None
        wx = '' if row['wxcodes'] in ('null', None) else row['wxcodes']
        rows[(hour, row['station'])] = (hour, row['station'], 'obs', temp, precip, None, 'SN' in wx, wx or None)
    return list(rows.values())


def modeled(first, last):
    """Open-Meteo reanalysis at each station's position."""
    query = urllib.parse.urlencode({
        'latitude': ','.join(str(p[0]) for p in STATIONS.values()),
        'longitude': ','.join(str(p[1]) for p in STATIONS.values()),
        'start_date': first.isoformat(), 'end_date': last.isoformat(),
        'hourly': 'temperature_2m,precipitation,snowfall', 'timezone': 'America/New_York',
    })
    body = json.loads(get(f'{ARCHIVE_URL}?{query}'))
    rows = []
    for station, place in zip(STATIONS, body if isinstance(body, list) else [body]):
        h = place['hourly']
        for t, temp, precip, snow in zip(h['time'], h['temperature_2m'], h['precipitation'], h['snowfall']):
            rows.append((dt.datetime.fromisoformat(t), station, 'model', temp, precip, snow, bool(snow), None))
    return rows


def write_year(con, path, rows):
    con.execute(f'CREATE OR REPLACE TEMP TABLE year_rows ({COLUMNS})')
    con.executemany('INSERT INTO year_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?)', rows)
    partial = path.with_suffix('.parquet.part')
    con.execute(f"COPY (SELECT * FROM year_rows ORDER BY station, hour) TO '{partial}' (FORMAT parquet, COMPRESSION zstd)")
    partial.replace(path)
    return len(rows)


def main(argv=None):
    import duckdb
    from .ingest import Store
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data-dir', type=Path,
                        default=os.environ.get('COZY_BIKES_DATA', Path.home() / '.local/share/cozy-bikes'))
    parser.add_argument('--first-year', type=int, default=FIRST_DAY.year)
    args = parser.parse_args(argv)
    out = args.data_dir / 'weather'
    out.mkdir(parents=True, exist_ok=True)
    # The archives trail by a few days; stop a week back so a finished year is complete.
    last_day = dt.date.today() - dt.timedelta(days=7)
    con = duckdb.connect()
    for year in range(args.first_year, last_day.year + 1):
        first, last = max(FIRST_DAY, dt.date(year, 1, 1)), min(last_day, dt.date(year, 12, 31))
        for source, fetch in (('obs', observed), ('model', modeled)):
            path = out / f'{source}-{year}.parquet'
            if path.exists() and year < last_day.year:
                continue
            count = write_year(con, path, fetch(first, last))
            print(f'{source} {year}: {count:,} station-hours', flush=True)
    Store(args.data_dir).write_catalog()
    print(f'weather view -> {args.data_dir / "bikes.duckdb"}')


if __name__ == '__main__':
    main()
