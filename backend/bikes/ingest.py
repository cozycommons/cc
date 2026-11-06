"""Mirror Citi Bike trip history into zstd Parquet, one file per published CSV.

Layout under the data directory:

    trips/system=<nyc|jc>/year=YYYY/month=MM/<csv name>.parquet
    manifest.json   archive key -> S3 ETag, size, row count and the Parquet files it produced
    bikes.duckdb    a `trips` view over every Parquet file

Every era's CSV is normalized to one schema (TRIP_COLUMNS). Archives are processed one at a time
and deleted after conversion, so peak disk is one archive plus one extracted CSV. An unknown
column or an unparseable timestamp stops the run instead of dropping rows.
"""
import argparse
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

SOURCE = 'https://s3.amazonaws.com/tripdata/'
S3 = '{http://s3.amazonaws.com/doc/2006-03-01/}'

TRIP_COLUMNS = {
    'ride_id': 'VARCHAR',
    'rideable_type': 'VARCHAR',
    'started_at': 'TIMESTAMP',
    'ended_at': 'TIMESTAMP',
    'start_station_id': 'VARCHAR',
    'start_station_name': 'VARCHAR',
    'end_station_id': 'VARCHAR',
    'end_station_name': 'VARCHAR',
    'start_lat': 'DOUBLE',
    'start_lng': 'DOUBLE',
    'end_lat': 'DOUBLE',
    'end_lng': 'DOUBLE',
    'member_casual': 'VARCHAR',
    # Published only before February 2021.
    'bike_id': 'VARCHAR',
    'birth_year': 'SMALLINT',
    'gender': 'TINYINT',
}

# Header spellings across eras, compared lowercased with spaces and underscores removed.
SOURCE_NAMES = {
    'rideid': 'ride_id', 'rideabletype': 'rideable_type',
    'startedat': 'started_at', 'starttime': 'started_at',
    'endedat': 'ended_at', 'stoptime': 'ended_at',
    'startstationid': 'start_station_id', 'startstationname': 'start_station_name',
    'endstationid': 'end_station_id', 'endstationname': 'end_station_name',
    'startlat': 'start_lat', 'startstationlatitude': 'start_lat',
    'startlng': 'start_lng', 'startstationlongitude': 'start_lng',
    'endlat': 'end_lat', 'endstationlatitude': 'end_lat',
    'endlng': 'end_lng', 'endstationlongitude': 'end_lng',
    'membercasual': 'member_casual', 'usertype': 'usertype',
    'bikeid': 'bike_id', 'birthyear': 'birth_year', 'gender': 'gender',
}
# Derivable from the timestamps.
IGNORED_SOURCE_NAMES = {'tripduration'}

TIMESTAMP_FORMATS = ['%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M',
                     '%m/%d/%Y %H:%M:%S', '%m/%d/%Y %H:%M']
FORMATS_SQL = '[' + ', '.join("'" + f + "'" for f in TIMESTAMP_FORMATS) + ']'


@dataclass(frozen=True)
class Archive:
    key: str
    size: int
    etag: str

    @property
    def system(self):
        return 'jc' if self.key.startswith('JC-') else 'nyc'

    @property
    def period(self):
        """Inclusive (first, last) YYYYMM covered: a year archive or a month archive."""
        match = re.match(r'(?:JC-)?(\d{4})(\d{2})?', self.key)
        year, month = match.group(1), match.group(2)
        return (year + month, year + month) if month else (year + '01', year + '12')


def parse_listing(xml_text):
    root = ET.fromstring(xml_text)
    archives = [Archive(item.findtext(S3 + 'Key'), int(item.findtext(S3 + 'Size')),
                        item.findtext(S3 + 'ETag').strip('"'))
                for item in root.iter(S3 + 'Contents')]
    truncated = root.findtext(S3 + 'IsTruncated') == 'true'
    return [a for a in archives if re.match(r'(JC-)?\d{4}', a.key) and a.key.endswith('.zip')], truncated


def list_archives():
    archives, marker = [], ''
    while True:
        url = SOURCE + ('?marker=' + urllib.parse.quote(marker) if marker else '')
        with urllib.request.urlopen(url, timeout=60) as response:
            page, truncated = parse_listing(response.read())
        archives += page
        if not truncated:
            return archives
        marker = page[-1].key


def download(archive, path):
    partial = path.with_suffix('.part')
    with urllib.request.urlopen(SOURCE + urllib.parse.quote(archive.key), timeout=120) as response, \
            open(partial, 'wb') as out:
        shutil.copyfileobj(response, out, 1 << 20)
    if partial.stat().st_size != archive.size:
        raise RuntimeError(f'{archive.key}: downloaded {partial.stat().st_size} bytes, listed {archive.size}')
    partial.replace(path)


PART = re.compile(r'_\d+\.csv$', re.IGNORECASE)


def name_month(name):
    match = re.search(r'(20\d{2})-?(\d{2})', name)
    return match.group(1) + match.group(2) if match else None


def plan_members(zip_path, archive):
    """(info, read) for each trip member: read=False marks a duplicate to count only.

    The 2013 and 2018 year archives hold each month twice: the original
    YYYYMM-citibike-tripdata.csv and a 2024 re-export split into _1, _2 parts,
    some of them in two folders. Read each part once by name; the original
    is only counted, so the caller can check it holds the same trips.
    """
    members, parts = [], {}
    for info in archive.infolist():
        name = Path(info.filename).name
        if info.is_dir() or info.filename.startswith('__MACOSX/') or name.startswith('.'):
            continue
        if not name.lower().endswith(('.csv', '.zip')):
            raise ValueError(f'{zip_path.name}: unexpected member {info.filename}')
        if PART.search(name):
            first = parts.setdefault(name, info)
            if first is not info:
                if (first.file_size, first.CRC) != (info.file_size, info.CRC):
                    raise ValueError(f'{zip_path.name}: two different {name}')
                continue
        members.append(info)
    split_months = {name_month(name) for name in parts}
    return [(info, not (Path(info.filename).name.lower().endswith('.csv')
                        and not PART.search(info.filename)
                        and name_month(Path(info.filename).name) in split_months))
            for info in members]


def extract_csvs(zip_path, workdir):
    """Yield (csv_path, read) for each trip CSV in a zip, extracted one at a time and removed after use."""
    with zipfile.ZipFile(zip_path) as archive:
        for info, read in plan_members(zip_path, archive):
            name = Path(info.filename).name
            target = workdir / name
            with archive.open(info) as source, open(target, 'wb') as out:
                shutil.copyfileobj(source, out, 1 << 20)
            try:
                if name.lower().endswith('.zip'):
                    yield from extract_csvs(target, workdir)
                else:
                    yield target, read
            finally:
                target.unlink(missing_ok=True)


def count_rows(con, csv_path):
    _, _, source = trip_select(con, csv_path)
    return con.execute(f'SELECT count(*) FROM {source}').fetchone()[0]


def csv_month(archive, csv_path):
    """(YYYY, MM) partition for a CSV: the month archive's own, else the CSV name's."""
    first, last = archive.period
    if first == last:
        # Member names are not reliable (JC-20161-citibike-tripdata.csv is January 2016).
        return first[:4], first[4:]
    match = re.search(r'(20\d{2})-?(\d{2})', csv_path.name)
    if not match or match.group(1) != first[:4] or not '01' <= match.group(2) <= '12':
        raise ValueError(f'{archive.key}: no month of {first[:4]} in {csv_path.name}')
    return match.group(1), match.group(2)


def trip_select(con, csv_path):
    """SELECT normalizing one CSV to TRIP_COLUMNS, from its header."""
    # Quotes are explicit: the sniffer reads only the first rows, and a station
    # name with a comma first appears on line 947,029 of April 2017.
    source = (f"read_csv({sql_literal(str(csv_path))}, header=true, all_varchar=true, quote='\"', escape='\"', "
              "nullstr=['', 'NULL', '\\N'])")
    columns = {}
    for (name,) in con.execute(f'SELECT column_name FROM (DESCRIBE SELECT * FROM {source})').fetchall():
        key = re.sub(r'[\s_]', '', name.lower())
        if key in IGNORED_SOURCE_NAMES:
            continue
        if key not in SOURCE_NAMES:
            raise ValueError(f'{csv_path.name}: unknown column {name!r}')
        columns[SOURCE_NAMES[key]] = '"' + name.replace('"', '""') + '"'
    if not {'started_at', 'ended_at'} <= columns.keys():
        raise ValueError(f'{csv_path.name}: missing start or end time')
    if 'usertype' in columns:
        columns['member_casual'] = (f"CASE {columns['usertype']} WHEN 'Subscriber' THEN 'member' "
                                    "WHEN 'Customer' THEN 'casual' END")
    expressions = []
    for name, kind in TRIP_COLUMNS.items():
        value = columns.get(name)
        if value is None:
            expressions.append(f'CAST(NULL AS {kind}) AS {name}')
        elif kind == 'TIMESTAMP':
            expressions.append(f'try_strptime({value}, {FORMATS_SQL}) AS {name}')
        elif kind in ('SMALLINT', 'TINYINT'):
            # Older files write birth year as 1988.0.
            expressions.append(f'TRY_CAST(TRY_CAST({value} AS DOUBLE) AS {kind}) AS {name}')
        else:
            expressions.append(f'TRY_CAST({value} AS {kind}) AS {name}')
    raw_times = (columns['started_at'], columns['ended_at'])
    return f"SELECT {', '.join(expressions)} FROM {source}", raw_times, source


def normalized(con, csv_path):
    """trip_select for a CSV whose every start and end time parses."""
    select, (raw_start, raw_end), source = trip_select(con, csv_path)
    bad = con.execute(
        f'SELECT any_value({raw_start}), any_value({raw_end}), count(*) FROM {source} '
        f'WHERE try_strptime({raw_start}, {FORMATS_SQL}) IS NULL OR try_strptime({raw_end}, {FORMATS_SQL}) IS NULL'
    ).fetchone()
    if bad[2]:
        raise ValueError(f'{csv_path.name}: {bad[2]} rows with unparseable times, e.g. {bad[0]!r} / {bad[1]!r}')
    return select


def convert(con, csv_path, out_path):
    """Write one CSV as sorted zstd Parquet; return its row count."""
    select = normalized(con, csv_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    partial = out_path.with_suffix('.parquet.part')
    rows = con.execute(
        f"COPY ({select} ORDER BY started_at) TO {sql_literal(str(partial))} "
        "(FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 9)"
    ).fetchone()[0]
    partial.replace(out_path)
    return rows


def sql_literal(value):
    return "'" + value.replace("'", "''") + "'"


class Store:
    def __init__(self, data_dir, memory_limit='1GB', threads=2):
        import duckdb
        self.root = Path(data_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / 'manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}
        self.con = duckdb.connect()
        self.con.execute(f"SET memory_limit = {sql_literal(memory_limit)}")
        self.con.execute(f'SET threads = {int(threads)}')
        self.con.execute(f"SET temp_directory = {sql_literal(str(self.root / 'tmp'))}")

    def current(self, archive):
        entry = self.manifest.get(archive.key)
        return bool(entry) and entry['etag'] == archive.etag and all(
            (self.root / f).exists() for f in entry['files'])

    def ingest(self, archive, zip_path):
        previous = self.manifest.pop(archive.key, None)
        if previous:
            for name in previous['files']:
                (self.root / name).unlink(missing_ok=True)
            self.save()
        owned = {f: key for key, entry in self.manifest.items() for f in entry['files']}
        files, rows = [], 0
        read_rows, duplicate_rows = {}, {}
        with tempfile.TemporaryDirectory(dir=self.root) as workdir:
            for csv_path, read in extract_csvs(zip_path, Path(workdir)):
                year, month = csv_month(archive, csv_path)
                if not read:
                    duplicate_rows[year + month] = duplicate_rows.get(year + month, 0) + count_rows(self.con, csv_path)
                    continue
                relative = f'trips/system={archive.system}/year={year}/month={month}/{csv_path.stem}.parquet'
                if relative in owned or relative in files:
                    raise ValueError(f'{archive.key}: {relative} already written by {owned.get(relative, archive.key)}')
                written = convert(self.con, csv_path, self.root / relative)
                read_rows[year + month] = read_rows.get(year + month, 0) + written
                rows += written
                files.append(relative)
        if not files:
            raise ValueError(f'{archive.key}: no trip CSVs')
        for month, count in duplicate_rows.items():
            if read_rows.get(month) != count:
                raise ValueError(f'{archive.key}: {month} parts hold {read_rows.get(month)} trips, '
                                 f'the whole-month file {count}')
        self.manifest[archive.key] = {'etag': archive.etag, 'size': archive.size, 'rows': rows, 'files': files}
        self.save()
        return rows

    def prune(self):
        """Delete Parquet an interrupted run wrote but the manifest does not list."""
        owned = {f for entry in self.manifest.values() for f in entry['files']}
        for path in (self.root / 'trips').rglob('*.parquet*'):
            if str(path.relative_to(self.root)) not in owned:
                path.unlink()

    def save(self):
        partial = self.manifest_path.with_suffix('.json.part')
        partial.write_text(json.dumps(self.manifest, indent=1, sort_keys=True) + '\n')
        partial.replace(self.manifest_path)

    def write_catalog(self):
        """Point bikes.duckdb's `trips` (and `weather`) views at the Parquet files (absolute path)."""
        import duckdb
        path, partial = self.root / 'bikes.duckdb', self.root / 'bikes.duckdb.part'
        partial.unlink(missing_ok=True)
        pattern = sql_literal(str(self.root / 'trips' / '**' / '*.parquet'))
        with duckdb.connect(str(partial)) as con:
            con.execute(f"CREATE VIEW trips AS SELECT * FROM read_parquet({pattern}, hive_partitioning=true, "
                        "hive_types={'system': VARCHAR, 'year': INTEGER, 'month': INTEGER})")
            # Hourly weather from bikes.weather_history, when it has been built.
            if any((self.root / 'weather').glob('*.parquet')):
                weather = sql_literal(str(self.root / 'weather' / '*.parquet'))
                con.execute(f'CREATE VIEW weather AS SELECT * FROM read_parquet({weather})')
        partial.replace(path)


def select_archives(archives, systems, first, last):
    return sorted((a for a in archives if a.system in systems
                   and a.period[1] >= first and a.period[0] <= last), key=lambda a: (a.system, a.key))


def month_arg(value):
    if not re.fullmatch(r'\d{4}-\d{2}', value):
        raise argparse.ArgumentTypeError('expected YYYY-MM')
    return value.replace('-', '')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--data-dir', type=Path,
                        default=os.environ.get('COZY_BIKES_DATA', Path.home() / '.local/share/cozy-bikes'))
    parser.add_argument('--system', choices=('nyc', 'jc', 'all'), default='all')
    parser.add_argument('--from', dest='first', type=month_arg, default='0000-01', metavar='YYYY-MM',
                        help='first month (a year archive is ingested whole)')
    parser.add_argument('--to', dest='last', type=month_arg, default='9999-12', metavar='YYYY-MM')
    parser.add_argument('--memory-limit', default='1GB', help='DuckDB memory limit; spills to disk beyond it')
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--keep-downloads', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='list what would be downloaded')
    args = parser.parse_args(argv)

    systems = {'nyc', 'jc'} if args.system == 'all' else {args.system}
    store = Store(args.data_dir, args.memory_limit, args.threads)
    with open(store.root / '.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit(f'Another ingest holds {store.root / ".lock"}')
        store.prune()
        pending = [a for a in select_archives(list_archives(), systems, args.first, args.last)
                   if not store.current(a)]
        print(f'{len(pending)} archives to ingest, {sum(a.size for a in pending) / 1e9:.1f} GB to download')
        if args.dry_run:
            for archive in pending:
                print(f'  {archive.key}  {archive.size / 1e6:.0f} MB')
            return
        downloads = store.root / 'downloads'
        downloads.mkdir(exist_ok=True)
        for archive in pending:
            zip_path = downloads / archive.key
            if not (zip_path.exists() and zip_path.stat().st_size == archive.size):
                print(f'downloading {archive.key}', flush=True)
                download(archive, zip_path)
            rows = store.ingest(archive, zip_path)
            print(f'ingested {archive.key}: {rows:,} trips', flush=True)
            if not args.keep_downloads:
                zip_path.unlink()
        store.write_catalog()
        total = sum(e['rows'] for e in store.manifest.values())
        size = sum((store.root / f).stat().st_size for e in store.manifest.values() for f in e['files'])
        print(f'{total:,} trips in {size / 1e9:.2f} GB of Parquet; query with: duckdb {store.root / "bikes.duckdb"}')


if __name__ == '__main__':
    main()
