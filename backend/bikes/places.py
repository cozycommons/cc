"""Address and place search for /bikes, from OpenStreetMap, served in house.

Look up "123 w 14th st", "barclays center" or "37-10 30th st queens" without a
geocoding service: what people type stays on our server, and there is no new
outbound host. Like the basemap, the index is built offline from BBBike's New
York extract and committed; addresses and places farther than about a kilometer
from any Citi Bike station are left out.

    python -m bikes.places [--pbf NewYork.osm.pbf]   (bikes venv)

places.tsv.gz holds one line per street and area, and one per named place:

    A  <normalized street>  <street>  <area>  <numbers>  <lat deltas>  <lng deltas>
    P  <normalized name>    <name>    <area>  <kind>     <lat>         <lng>

Coordinates are integers in 1e-5 degrees (about 1 m); a street's are deltas in
house-number order. `search` is stdlib only and parses a street's numbers only
when the street matches.

Data © OpenStreetMap contributors, ODbL.
"""
import argparse
import bisect
from collections import Counter
from functools import lru_cache
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.request

PLACES_PATH = Path(__file__).with_name('places.tsv.gz')
Q = 1e5
WORDS = {
    'street': 'st', 'str': 'st', 'avenue': 'ave', 'av': 'ave', 'boulevard': 'blvd', 'place': 'pl', 'road': 'rd',
    'drive': 'dr', 'parkway': 'pkwy', 'lane': 'ln', 'court': 'ct', 'terrace': 'ter', 'square': 'sq',
    'highway': 'hwy', 'expressway': 'expy', 'plaza': 'plz', 'east': 'e', 'west': 'w', 'north': 'n', 'south': 's',
    'saint': 'st', 'and': '', 'the': '', 'of': '', 'first': '1', 'second': '2', 'third': '3', 'fourth': '4',
    'fifth': '5', 'sixth': '6', 'seventh': '7', 'eighth': '8', 'ninth': '9', 'tenth': '10', 'eleventh': '11',
    'twelfth': '12',
}
ORDINAL = re.compile(r'^(\d+)(st|nd|rd|th)$')
HOUSE = re.compile(r'^\d+[a-z]?(-\d+[a-z]?)?$')
AREAS = {'manhattan': 'Manhattan', 'brooklyn': 'Brooklyn', 'queens': 'Queens', 'bronx': 'Bronx',
         'jersey': 'Jersey City', 'hoboken': 'Hoboken'}
LIMIT = 8


def words(text):
    """Lowercase tokens with street words abbreviated and ordinals as numbers: 'West 14th Street' -> w 14 st."""
    out = []
    for token in re.sub(r"[^0-9a-z\- ]", ' ', text.lower().replace("'", '')).split():
        token = token.strip('-')
        token = WORDS.get(token, token)
        match = ORDINAL.match(token)
        if match:
            token = match[1]
        if token:
            out.append(token)
    return out


def number_key(number):
    """'37-10' -> (37, 10); '123A' -> (123,): Queens hyphenated numbers sort by block, then house."""
    return tuple(int(n) for n in re.findall(r'\d+', number))


# Places people search for by name rank above shops and businesses with the same words.
LANDMARKS = {'transit', 'attraction', 'park', 'museum', 'stadium', 'university', 'college', 'hospital', 'library',
             'theatre', 'arts_centre', 'zoo', 'marina', 'ferry_terminal', 'garden', 'playground', 'viewpoint'}


@lru_cache(maxsize=1)
def index():
    """(streets, places, words): `words` maps each word to the (kind, i) entries that contain it."""
    streets, places, vocab = [], [], {}
    if PLACES_PATH.exists():
        with gzip.open(PLACES_PATH, 'rt', encoding='utf-8') as lines:
            for line in lines:
                kind, norm, *rest = line.rstrip('\n').split('\t')
                if kind == 'A':
                    key, entry = ('A', len(streets)), (len(norm.split()), *rest)
                    streets.append(entry)
                else:
                    name, area, what, lat, lng = rest
                    key = ('P', len(places))
                    places.append((len(norm.split()), name, area, what, int(lat) / Q, int(lng) / Q))
                for word in set(norm.split()):
                    vocab.setdefault(word, []).append(key)
    return streets, places, (vocab, sorted(vocab))


def matching(query, vocab):
    """Entries holding every query word; the last may be the start of a word (typing)."""
    words_to_ids, ordered = vocab
    *whole, last = query
    found = None
    for word in whole:
        ids = set(words_to_ids.get(word, ()))
        found = ids if found is None else found & ids
        if not found:
            return set()
    start = bisect.bisect_left(ordered, last)
    prefixed = set()
    for word in ordered[start:]:
        if not word.startswith(last):
            break
        prefixed.update(words_to_ids[word])
    return prefixed if found is None else found & prefixed


def houses(numbers, lats, lngs):
    lat = lng = 0
    for number, d_lat, d_lng in zip(numbers.split(), lats.split(), lngs.split()):
        lat, lng = lat + int(d_lat), lng + int(d_lng)
        yield number, lat / Q, lng / Q


def nearest_house(found, number):
    """The exact number, else the closest on the same side of the street (same parity)."""
    exact = [h for h in found if h[0] == number]
    if exact:
        return exact[0], True
    want = number_key(number)
    def gap(house):
        have = number_key(house[0])
        if not want or not have:
            return (1, 0)
        return (have[0] % 2 != want[0] % 2, abs(have[0] - want[0]), have[1:] != want[1:])
    return min(found, key=gap), False


def result(label, area, kind, lat, lng):
    return {'label': label, 'area': area, 'kind': kind, 'lat': round(lat, 5), 'lng': round(lng, 5)}


def search(text, limit=LIMIT, near=None):
    """Addresses, streets and named places matching `text`, best first; equally good
    matches nearest `near` (lat, lng) first, so "350 5th ave" finds Manhattan's from Midtown."""
    query = words(text)
    area = next((AREAS[w] for w in query if w in AREAS), None)
    if area:
        found = _search([w for w in query if w not in AREAS and w not in ('city', 'ny', 'nyc', 'nj')], area, limit, near)
        if found:
            return found
    return _search(query, None, limit, near)


def _search(query, area, limit, near):
    if not query:
        return []
    streets, places, vocab = index()
    number = query[0] if HOUSE.match(query[0]) and len(query) > 1 else None
    ranked = []
    if number:
        for kind, i in matching(query[1:], vocab):
            if kind != 'A':
                continue
            size, label, place_area, numbers, lats, lngs = streets[i]
            if area and place_area != area:
                continue
            house, exact = nearest_house(list(houses(numbers, lats, lngs)), number)
            ranked.append(((0 if exact else 1, 0, size - len(query) + 1, label),
                           result(f'{house[0].upper()} {label}', place_area, 'address', house[1], house[2])))
    for kind, i in matching(query, vocab):
        if kind == 'A':
            size, label, place_area, numbers, lats, lngs = streets[i]
            if area and place_area != area:
                continue
            found = list(houses(numbers, lats, lngs))
            middle = found[len(found) // 2]
            ranked.append(((3, 0, size - len(query), label), result(label, place_area, 'street', middle[1], middle[2])))
        else:
            size, name, place_area, what, lat, lng = places[i]
            if area and place_area != area:
                continue
            ranked.append(((2 if number else 1, what not in LANDMARKS, size - len(query), name),
                           result(name, place_area, what, lat, lng)))
    def key(entry):
        rank, r = entry
        away = 0.0 if near is None else (r['lat'] - near[0]) ** 2 + ((r['lng'] - near[1]) * 0.76) ** 2
        return (*rank[:-1], away, rank[-1])
    ranked.sort(key=key)
    out, seen = [], set()
    for _, r in ranked:
        key = (r['label'].lower(), r['area'])
        if key not in seen:
            seen.add(key)
            out.append(r)
        if len(out) == limit:
            break
    return out


# Building the index (offline, bikes venv).

# Postcode prefixes when addr:city is missing or a neighborhood name.
POSTCODE_AREAS = [('100', 'Manhattan'), ('101', 'Manhattan'), ('102', 'Manhattan'), ('104', 'Bronx'),
                  ('112', 'Brooklyn'), ('110', 'Queens'), ('111', 'Queens'), ('113', 'Queens'), ('114', 'Queens'),
                  ('116', 'Queens'), ('07030', 'Hoboken'), ('073', 'Jersey City')]
CITY_AREAS = {'new york': 'Manhattan', 'manhattan': 'Manhattan', 'brooklyn': 'Brooklyn', 'bronx': 'Bronx',
              'the bronx': 'Bronx', 'queens': 'Queens', 'jersey city': 'Jersey City', 'hoboken': 'Hoboken'}
KINDS = "coalesce(tags['railway'], tags['amenity'], tags['shop'], tags['tourism'], tags['leisure'], tags['building'])"


def area_of(city, postcode):
    city = (city or '').strip().lower()
    if city in CITY_AREAS:
        return CITY_AREAS[city]
    postcode = (postcode or '').strip()
    return next((area for prefix, area in POSTCODE_AREAS if postcode.startswith(prefix)), '')


def build(con, pbf, stations):
    # Kilometer cells around every station: kept places fall in one of them or its neighbors.
    con.execute('CREATE TEMP TABLE near (cy INTEGER, cx INTEGER)')
    cells = {(round(lat * 100) + dy, round(lng * 77) + dx) for lat, lng in stations for dy in (-1, 0, 1) for dx in (-1, 0, 1)}
    con.executemany('INSERT INTO near VALUES (?, ?)', sorted(cells))
    con.execute(f"""
        CREATE TEMP TABLE tagged AS
        SELECT kind, id, lat, lon, refs[1] AS ref, tags['addr:housenumber'] AS number, tags['addr:street'] AS street,
               tags['addr:city'] AS city, tags['addr:postcode'] AS postcode, tags['name'] AS name,
               CASE WHEN tags['railway'] IN ('station', 'subway_entrance') OR tags['public_transport'] = 'station' THEN 'transit'
                    ELSE {KINDS} END AS what
        FROM ST_ReadOSM('{pbf}')
        WHERE kind IN ('node', 'way') AND ((tags['addr:housenumber'] IS NOT NULL AND tags['addr:street'] IS NOT NULL)
              OR (tags['name'] IS NOT NULL AND (tags['amenity'] IS NOT NULL OR tags['shop'] IS NOT NULL
                  OR tags['tourism'] IS NOT NULL OR tags['leisure'] IS NOT NULL OR tags['railway'] IN ('station')
                  OR tags['public_transport'] = 'station' OR (tags['building'] IS NOT NULL AND tags['addr:housenumber'] IS NULL))))
    """)
    # A way is placed at its first node: within a building or a park's edge.
    con.execute(f"""
        CREATE TEMP TABLE located AS
        SELECT t.*, coalesce(t.lat, n.lat) AS y, coalesce(t.lon, n.lon) AS x FROM tagged t
        LEFT JOIN (SELECT id, lat, lon FROM ST_ReadOSM('{pbf}') WHERE kind = 'node'
                   AND id IN (SELECT ref FROM tagged WHERE kind = 'way')) n ON t.kind = 'way' AND n.id = t.ref
    """)
    rows = con.execute("""
        SELECT number, street, city, postcode, name, what, y, x FROM located
        WHERE y IS NOT NULL AND (round(y * 100)::INTEGER, round(x * 77)::INTEGER) IN (SELECT (cy, cx) FROM near)
    """).fetchall()
    # Many entries carry no city or postcode: they take the most common area of their kilometer cell.
    cell = lambda lat, lng: (round(lat * 100), round(lng * 77))
    tally = {}
    for _, _, city, postcode, _, _, lat, lng in rows:
        if area := area_of(city, postcode):
            tally.setdefault(cell(lat, lng), Counter())[area] += 1
    cell_area = {c: counts.most_common(1)[0][0] for c, counts in tally.items()}
    streets, places = {}, {}
    for number, street, city, postcode, name, what, lat, lng in rows:
        area = area_of(city, postcode) or cell_area.get(cell(lat, lng), '')
        if number and street:
            norm = ' '.join(words(street))
            entry = streets.setdefault((norm, area), {'labels': {}, 'houses': {}})
            entry['labels'][street] = entry['labels'].get(street, 0) + 1
            entry['houses'].setdefault(number.strip().upper().replace(' ', ''), (lat, lng))
        if name and what:
            norm = ' '.join(words(name))
            if norm:
                places.setdefault((norm, area), (name, what, lat, lng))
    return streets, places


def write(streets, places, path):
    lines = []
    for (norm, area), entry in sorted(streets.items()):
        label = max(entry['labels'], key=lambda s: (entry['labels'][s], s))
        numbers = sorted(entry['houses'], key=lambda n: (number_key(n), n))
        lat0 = lng0 = 0
        d_lat, d_lng = [], []
        for n in numbers:
            lat, lng = (round(v * Q) for v in entry['houses'][n])
            d_lat.append(str(lat - lat0))
            d_lng.append(str(lng - lng0))
            lat0, lng0 = lat, lng
        lines.append('\t'.join(['A', norm, label, area, ' '.join(n.lower() for n in numbers), ' '.join(d_lat), ' '.join(d_lng)]))
    for (norm, area), (name, what, lat, lng) in sorted(places.items()):
        clean = name.replace('\t', ' ')
        lines.append('\t'.join(['P', norm, clean, area, what, str(round(lat * Q)), str(round(lng * Q))]))
    partial = path.with_suffix('.part')
    with gzip.open(partial, 'wt', encoding='utf-8', compresslevel=9) as out:
        out.write('\n'.join(lines) + '\n')
    partial.replace(path)


def main(argv=None):
    import duckdb
    # The API imports this module for search; the extract download stays with the offline builders.
    from .basemap import EXTRACT_URL
    from .model import EXPLORE_PATH
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--pbf', type=Path, help='an OSM extract; downloaded from BBBike when omitted')
    parser.add_argument('--out', type=Path, default=PLACES_PATH)
    parser.add_argument('--memory-limit', default='2GB')
    args = parser.parse_args(argv)
    explore = json.loads(Path(EXPLORE_PATH).read_text())['stations']
    stations = list(zip(explore['lat'], explore['lng']))
    with tempfile.TemporaryDirectory() as tmp:
        pbf = args.pbf
        if pbf is None:
            pbf = Path(tmp) / 'NewYork.osm.pbf'
            print(f'downloading {EXTRACT_URL}', flush=True)
            with urllib.request.urlopen(EXTRACT_URL, timeout=120) as response, open(pbf, 'wb') as out:
                shutil.copyfileobj(response, out, 1 << 20)
        con = duckdb.connect()
        con.execute(f"SET memory_limit = '{args.memory_limit}'")
        con.execute(f"SET temp_directory = '{os.path.join(tmp, 'spill')}'")
        con.execute('INSTALL spatial; LOAD spatial')
        streets, places = build(con, str(pbf).replace("'", "''"), stations)
    write(streets, places, args.out)
    count = sum(len(e['houses']) for e in streets.values())
    print(f'{count:,} addresses on {len(streets):,} streets, {len(places):,} places, '
          f'{args.out.stat().st_size / 1e6:.1f} MB -> {args.out}')


if __name__ == '__main__':
    main()
