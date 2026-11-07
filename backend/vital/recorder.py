"""Record how many people are at VITAL Brooklyn, so the quiet hours can be measured.

VITAL's Brooklyn page shows a live headcount from Safespace, which serves the
bare number as plain text. This polls it and appends one row per poll to

    <out>/occupancy.csv
    recorded_at,people

with recorded_at in Unix seconds. The count covers the whole building (walls,
roof, patio and classes), not just climbers. Standard library only.

    python -m vital.recorder [--out DIR] [--interval 300] [--once]
"""
import argparse
from datetime import datetime
import os
from pathlib import Path
import time
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

URL = 'https://display.safespace.io/value/live/a7796f34'
NEW_YORK = ZoneInfo('America/New_York')
COLUMNS = 'recorded_at,people'


def fetch():
    """Return the live headcount; raises URLError or ValueError when the feed is down or garbled."""
    with urlopen(URL, timeout=15) as response:
        return int(response.read().decode().strip())


def record(out, people, now=None):
    path = Path(out) / 'occupancy.csv'
    new = not path.exists()
    with path.open('a') as file:
        if new:
            file.write(COLUMNS + '\n')
        file.write(f'{int(now or time.time())},{people}\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=os.environ.get(
        'COZY_VITAL_DATA', Path.home() / '.local/share/cozy-vital'))
    parser.add_argument('--interval', type=float, default=300.0, help='seconds between polls')
    parser.add_argument('--once', action='store_true', help='poll once, for cron')
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    while True:
        started = time.monotonic()
        try:
            people = fetch()
            record(args.out, people)
            print(f'{datetime.now(NEW_YORK):%H:%M:%S} {people} people', flush=True)
        except (URLError, ValueError, TimeoutError) as error:
            print(f'{datetime.now(NEW_YORK):%H:%M:%S} occupancy unavailable: {error}', flush=True)
        if args.once:
            return
        time.sleep(max(0.0, args.interval - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
