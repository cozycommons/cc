"""Show when VITAL Brooklyn is quiet: the median headcount by weekday and hour.

Reads the recorder's occupancy.csv and, optionally, the community scrape at
github.com/dhoogs/brooklyn_vital_occupancy (occupancy.csv there, rows like
"31, Tue Mar 22 23:14:49 EDT 2022" in New York time), which goes back to March
2022 but has thinned to a few samples a day since 2026.

    python -m vital.busy [--out DIR] [--scrape FILE] [--days 365] [--write]

--write saves the medians to week.json beside this file, which /vital/week serves.
"""
import argparse
from collections import defaultdict
import csv
import json
from datetime import date, datetime, timedelta
import os
from pathlib import Path
from statistics import median

from .recorder import NEW_YORK

DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
WEEK = Path(__file__).with_name('week.json')
MIN_SAMPLES = 5  # a weekday-hour with fewer samples prints as '.'


def read_recorded(path):
    with open(path, newline='') as file:
        for row in csv.DictReader(file):
            yield datetime.fromtimestamp(int(row['recorded_at']), NEW_YORK).replace(tzinfo=None), int(row['people'])


def read_scrape(path):
    """Yield (New York time, people) from the community scrape, skipping its header and broken rows."""
    with open(path) as file:
        for line in file:
            people, _, stamp = line.partition(',')
            parts = stamp.split()  # weekday month day time zone year
            if len(parts) != 6 or not people.strip().isdigit():
                continue
            yield datetime.strptime(' '.join(parts[1:4] + parts[5:]), '%b %d %H:%M:%S %Y'), int(people)


def hourly(samples, since):
    """Median people for each (weekday, hour) with enough samples on or after since."""
    cells = defaultdict(list)
    for at, people in samples:
        if at.date() >= since:
            cells[at.weekday(), at.hour].append(people)
    return {cell: median(counts) for cell, counts in cells.items() if len(counts) >= MIN_SAMPLES}


def week(samples, since):
    """The committed model: for Monday to Sunday, 24 hourly medians (None without enough samples)."""
    kept = [(at, people) for at, people in samples if at.date() >= since]
    medians = hourly(kept, since)
    return {'from': min(at for at, _ in kept).date().isoformat(), 'to': max(at for at, _ in kept).date().isoformat(),
            'samples': len(kept),
            'hours': [[None if (day, hour) not in medians else round(medians[day, hour]) for hour in range(24)]
                      for day in range(7)]}


def report(medians):
    lines = ['hour ' + ''.join(f'{d:>6}' for d in DAYS)]
    for hour in range(24):
        cells = (medians.get((day, hour)) for day in range(7))
        lines.append(f'{hour:>4} ' + ''.join(f'{"." if m is None else round(m):>6}' for m in cells))
    for day in range(7):
        day_cells = {hour: m for (d, hour), m in medians.items() if d == day}
        if not day_cells:
            continue
        peak = max(day_cells, key=day_cells.get)
        # Hours under a tenth of the peak are the gym closing or barely open, not a good time to go.
        open_hours = {hour: m for hour, m in day_cells.items() if m >= day_cells[peak] / 10}
        quiet = min(open_hours, key=open_hours.get)
        lines.append(f'{DAYS[day]}: busiest {peak}:00 ({round(day_cells[peak])}), '
                     f'quietest open hour {quiet}:00 ({round(open_hours[quiet])})')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, default=os.environ.get(
        'COZY_VITAL_DATA', Path.home() / '.local/share/cozy-vital'))
    parser.add_argument('--scrape', type=Path, help="the community scrape's occupancy.csv")
    parser.add_argument('--days', type=int, default=365, help='use only the last this many days')
    parser.add_argument('--write', action='store_true', help=f'save the medians to {WEEK.name}')
    args = parser.parse_args(argv)
    samples = []
    if (args.out / 'occupancy.csv').exists():
        samples += read_recorded(args.out / 'occupancy.csv')
    if args.scrape:
        samples += read_scrape(args.scrape)
    since = date.today() - timedelta(days=args.days)
    print(report(hourly(samples, since)))
    if args.write:
        WEEK.write_text(json.dumps(week(samples, since), separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
