"""Record Citi Bike's live station status, so fullness by hour can be measured later.

Trip files say when bikes moved, not how full a station was. This polls GBFS
station_status and appends one CSV row per station whenever its report changes
(its last_reported time), to a gzip file per New York day:

    <out>/status-YYYY-MM-DD.csv.gz
    recorded_at,last_reported,station_id,bikes,ebikes,docks,renting,returning

Forward-fill a station's rows to get its state at any moment. Each poll appends
a gzip member, which gzip, Python and DuckDB read as one stream. Standard library
only, so it runs anywhere the API's GBFS host is reachable.

    python -m bikes.recorder --out DIR [--interval 60] [--once]
"""
import argparse
import csv
from datetime import datetime
import gzip
import io
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from . import gbfs

NEW_YORK = ZoneInfo('America/New_York')
COLUMNS = ['recorded_at', 'last_reported', 'station_id', 'bikes', 'ebikes', 'docks', 'renting', 'returning']


class Recorder:
    def __init__(self, out):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.seen = {}  # GBFS station_id -> last_reported already written
        self.short_names = {}

    def poll(self, now=None):
        """Append the stations whose report changed; return how many rows were written."""
        now = now or time.time()
        status = gbfs._fetch('station_status')
        if any(s['station_id'] not in self.short_names for s in status):
            self.short_names = {s['station_id']: s['short_name'] for s in gbfs._fetch('station_information')}
        rows = []
        for s in status:
            short = self.short_names.get(s['station_id'])
            reported = s.get('last_reported')
            if short is None or not s.get('is_installed') or self.seen.get(s['station_id']) == reported:
                continue
            self.seen[s['station_id']] = reported
            rows.append([int(now), reported, short, s.get('num_bikes_available', 0), s.get('num_ebikes_available', 0),
                         s.get('num_docks_available', 0), int(bool(s.get('is_renting'))), int(bool(s.get('is_returning')))])
        if rows:
            path = self.out / f"status-{datetime.fromtimestamp(now, NEW_YORK):%Y-%m-%d}.csv.gz"
            text = io.StringIO()
            writer = csv.writer(text)
            if not path.exists():
                writer.writerow(COLUMNS)
            writer.writerows(rows)
            with gzip.open(path, 'at', newline='') as out:
                out.write(text.getvalue())
        return len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=os.environ.get(
        'COZY_BIKES_STATUS', Path.home() / '.local/share/cozy-bikes/status'))
    parser.add_argument('--interval', type=float, default=60.0, help='seconds between polls (GBFS ttl is 60)')
    parser.add_argument('--once', action='store_true', help='poll once, for cron')
    args = parser.parse_args(argv)
    recorder = Recorder(args.out)
    while True:
        started = time.monotonic()
        try:
            print(f'{datetime.now(NEW_YORK):%H:%M:%S} {recorder.poll()} stations changed', flush=True)
        except gbfs.GbfsError as error:
            print(f'{datetime.now(NEW_YORK):%H:%M:%S} GBFS unavailable: {error}', flush=True)
        if args.once:
            return
        time.sleep(max(0.0, args.interval - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
