"""Build the /bikes street basemap: static JSON tiles cut from an OpenStreetMap extract.

The page draws streets, bike lanes, parks and filled water under the live station
dots without calling a map service: the user's location never leaves the
browser, and there is no runtime dependency or CSP change. Run it a few times a
year; streets change slowly.

    python -m bikes.basemap [--pbf NewYork.osm.pbf] [--out frontend/public/bikes/map]

Without --pbf it downloads BBBike's New York extract (NYC plus Jersey City and
Hoboken). Needs the bikes venv: DuckDB's spatial extension reads the .pbf (DuckDB
verifies the extension's signature when it loads).

Output: index.json (grid origin, tile size, quantum, the tiles that exist) and
<ix>_<iy>.json per tile. A tile holds each layer's polylines as integer lists,
[x0, y0, dx1, dy1, ...] in QUANTUM-degree units from the tile's south-west
corner (y grows north). A way crossing tiles appears in each, whole.
The `names` layer instead holds street labels, [x, y, degrees, text]: a
label's point, its turn on screen and the name as Citi Bike writes it ("W 31 St").

Data © OpenStreetMap contributors, ODbL; the page credits it.
"""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request

from .model import SERVICE_AREA

EXTRACT_URL = 'https://download.bbbike.org/osm/bbbike/NewYork/NewYork.osm.pbf'
OUT_DIR = Path(__file__).with_name('map')
# About 1.1 km each way at New York's latitude.
TILE_LAT, TILE_LNG = 0.01, 0.013
QUANTUM = 1e-5  # degrees, about 1 m
SIMPLIFY_DEG = 2e-5
# Sea (harbor, Hudson, East River) is filled from the coastline, closed along the
# edges of this box. Its south edge stops above the Raritan River mouth (40.47),
# where OSM's coastline gives way to a river area the extract lacks; no Citi Bike
# station is south of about 40.63.
SEA_BOX = (40.55, SERVICE_AREA[1], SERVICE_AREA[2], SERVICE_AREA[3])
LAND_POINTS = 10

LAYERS = {
    'major': "highway IN ('motorway', 'trunk', 'primary', 'secondary', 'motorway_link', 'trunk_link', "
             "'primary_link', 'secondary_link')",
    'minor': "highway IN ('tertiary', 'tertiary_link', 'residential', 'unclassified', 'living_street', 'pedestrian')",
    'bike': "highway = 'cycleway' OR (highway = 'path' AND bicycle IN ('designated', 'yes'))",
    'park': "leisure IN ('park', 'garden', 'playground') AND closed",
    'water': "(\"natural\" = 'water' AND closed) OR waterway = 'riverbank'",
    # Not drawn itself: it bounds the filled 'sea' layer.
    'coast': "\"natural\" = 'coastline'",
}
DRAWN = [name for name in LAYERS if name != 'coast'] + ['sea', 'names']


def build(con, pbf):
    south, north, west, east = SERVICE_AREA
    con.execute(f"""
        CREATE TEMP TABLE ways AS
        SELECT id, refs, tags['name'] AS name, tags['highway'] AS highway, tags['leisure'] AS leisure, tags['natural'] AS "natural",
               tags['waterway'] AS waterway, tags['bicycle'] AS bicycle, refs[1] = refs[-1] AS closed,
               tags['bridge'] IS NOT NULL OR tags['tunnel'] IS NOT NULL OR coalesce(tags['man_made'], '') = 'pier' AS crossing,
               coalesce(tags['highway'], '') IN ('primary', 'secondary', 'tertiary', 'residential', 'unclassified') AS street
        FROM ST_ReadOSM('{pbf}')
        WHERE kind = 'way' AND (tags['highway'] IS NOT NULL OR tags['leisure'] IS NOT NULL
              OR tags['natural'] IN ('coastline', 'water') OR tags['waterway'] = 'riverbank')
    """)
    layer = 'CASE ' + ' '.join(f"WHEN {cond} THEN '{name}'" for name, cond in LAYERS.items()) + ' END'
    con.execute(f"CREATE TEMP TABLE kept AS SELECT id, refs, name, crossing, street, {layer} AS layer "
                f"FROM ways WHERE ({layer}) IS NOT NULL")
    con.execute(f"""
        CREATE TEMP TABLE nodes AS
        SELECT id, lat, lon FROM ST_ReadOSM('{pbf}')
        WHERE kind = 'node' AND id IN (SELECT DISTINCT unnest(refs) FROM kept)
    """)
    # Each way's points in order; drawn layers are simplified and kept if they touch the service area.
    con.execute("""
        CREATE TEMP TABLE lines AS
        WITH points AS (
            SELECT k.id, k.layer, k.name, k.crossing, k.street, p.i, n.lat, n.lon
            FROM kept k, LATERAL (SELECT unnest(k.refs) AS ref, generate_subscripts(k.refs, 1) AS i) p
            JOIN nodes n ON n.id = p.ref
        )
        SELECT id, any_value(layer) AS layer, any_value(name) AS name, any_value(crossing) AS crossing, any_value(street) AS street,
               ST_MakeLine(list(ST_Point(lon, lat) ORDER BY i)) AS geom
        FROM points GROUP BY id HAVING count(*) >= 2
    """)
    con.execute(f"""
        CREATE TEMP TABLE shapes AS
        SELECT id, layer, ST_Simplify(geom, {SIMPLIFY_DEG}) AS geom FROM lines
        WHERE layer <> 'coast' AND ST_Intersects(geom, ST_MakeEnvelope({west}, {south}, {east}, {north}))
    """)
    sea(con)
    rows = con.execute(f"""
        WITH b AS (
            SELECT id, layer, geom,
                   floor((ST_XMin(geom) - {west}) / {TILE_LNG})::INT AS x0, floor((ST_XMax(geom) - {west}) / {TILE_LNG})::INT AS x1,
                   floor((ST_YMin(geom) - {south}) / {TILE_LAT})::INT AS y0, floor((ST_YMax(geom) - {south}) / {TILE_LAT})::INT AS y1
            FROM shapes
        )
        SELECT x, y, layer, [[ST_X(p.geom), ST_Y(p.geom)] FOR p IN ST_Dump(ST_Points(geom))] AS coords
        FROM b, range(x0, x1 + 1) AS rx(x), range(y0, y1 + 1) AS ry(y)
        WHERE x >= 0 AND y >= 0
        UNION ALL
        SELECT x, y, 'sea', coords FROM sea_rings
    """).fetchall()
    named = con.execute(f"""
        SELECT name, [[ST_X(p.geom), ST_Y(p.geom)] FOR p IN ST_Dump(ST_Points(geom))] FROM lines
        WHERE layer IN ('major', 'minor') AND name IS NOT NULL AND NOT crossing
          AND ST_Intersects(geom, ST_MakeEnvelope({west}, {south}, {east}, {north}))
    """).fetchall()
    tiles = encode(rows)
    for (x, y), names in street_labels(named).items():
        tiles.setdefault((x, y), {})['names'] = names
    return tiles


# Street names the way Citi Bike writes them in station names: "W 31 St & 7 Ave".
SHORT = {'Street': 'St', 'Avenue': 'Ave', 'West': 'W', 'East': 'E', 'North': 'N', 'South': 'S',
         'Boulevard': 'Blvd', 'Place': 'Pl', 'Road': 'Rd', 'Drive': 'Dr', 'Parkway': 'Pkwy', 'Lane': 'Ln',
         'Court': 'Ct', 'Terrace': 'Ter', 'Square': 'Sq', 'Highway': 'Hwy', 'Expressway': 'Expy'}
LABEL_EVERY_M = 250


def short_name(name):
    out = []
    for word in name.split():
        word = SHORT.get(word, word)
        if word[:-2].isdigit() and word[-2:] in ('st', 'nd', 'rd', 'th'):
            word = word[:-2]
        out.append(word)
    return ' '.join(out)


def street_labels(named):
    """{(x, y): [[qx, qy, degrees, text], ...]}: a label every LABEL_EVERY_M or so along each named
    street in each tile, at a segment's midpoint and turned along it, upright (-90 to 90 degrees)."""
    south, _, west, _ = SERVICE_AREA
    k = math.cos(math.radians((SERVICE_AREA[0] + SERVICE_AREA[1]) / 2))
    since, out = {}, {}
    for name, coords in named:
        text = short_name(name)
        for (lng0, lat0), (lng1, lat1) in zip(coords, coords[1:]):
            dx, dy = (lng1 - lng0) * k * 111320, (lat1 - lat0) * 111320
            length = math.hypot(dx, dy)
            mid_lng, mid_lat = (lng0 + lng1) / 2, (lat0 + lat1) / 2
            x, y = math.floor((mid_lng - west) / TILE_LNG), math.floor((mid_lat - south) / TILE_LAT)
            key = (text, x, y)
            # A label needs room: skip segments shorter than its rough length.
            since[key] = since.get(key, LABEL_EVERY_M) + length
            if length < 4 * len(text) or since[key] < LABEL_EVERY_M:
                continue
            since[key] = 0.0
            degrees = math.degrees(math.atan2(-dy, dx))  # screen y grows down
            degrees = degrees - 180 if degrees > 90 else degrees + 180 if degrees <= -90 else degrees
            ox, oy = west + x * TILE_LNG, south + y * TILE_LAT
            out.setdefault((x, y), []).append([round((mid_lng - ox) / QUANTUM), round((mid_lat - oy) / QUANTUM),
                                               round(degrees), text])
    return out


def sea(con):
    """sea_rings(x, y, coords): water areas clipped to each tile, as rings.

    The coastline, closed by SEA_BOX's edges, cuts the box into areas. Land areas
    hold streets; an area with fewer than LAND_POINTS street points is water.
    Only ordinary streets count, and not on bridges, tunnels or piers: motorways
    run on viaducts over the East River and walkways out onto the piers. (An island without
    streets reads as water: tidal marsh, mostly, outside the Citi Bike area.)
    """
    south, north, west, east = SEA_BOX
    box = f'ST_MakeEnvelope({west}, {south}, {east}, {north})'
    origin_south, _, origin_west, _ = SERVICE_AREA
    con.execute(f"""
        CREATE TEMP TABLE faces AS
        WITH edges AS (
            SELECT ST_Intersection(geom, {box}) AS g FROM lines WHERE layer = 'coast' AND ST_Intersects(geom, {box})
            UNION ALL SELECT ST_Boundary({box})
        )
        SELECT unnest(ST_Dump(ST_Polygonize([ST_Union_Agg(g)]))).geom AS geom FROM edges
    """)
    con.execute(f"""
        CREATE TEMP TABLE street_points AS
        SELECT DISTINCT ST_Point(ST_X(p.geom), ST_Y(p.geom)) AS p
        FROM lines, LATERAL (SELECT unnest(ST_Dump(ST_Points(geom))) AS p) d
        WHERE street AND NOT crossing AND ST_Intersects(geom, {box})
    """)
    con.execute(f"""
        CREATE TEMP TABLE sea_rings AS
        WITH counted AS (
            SELECT f.geom, count(s.p) AS n FROM faces f LEFT JOIN street_points s ON ST_Contains(f.geom, s.p) GROUP BY f.geom
        ), water AS (
            SELECT geom FROM counted WHERE n < {LAND_POINTS}
        ), b AS (
            SELECT geom,
                   floor((ST_XMin(geom) - {origin_west}) / {TILE_LNG})::INT AS x0, floor((ST_XMax(geom) - {origin_west}) / {TILE_LNG})::INT AS x1,
                   floor((ST_YMin(geom) - {origin_south}) / {TILE_LAT})::INT AS y0, floor((ST_YMax(geom) - {origin_south}) / {TILE_LAT})::INT AS y1
            FROM water
        ), clipped AS (
            SELECT x, y, ST_Simplify(ST_CollectionExtract(ST_Intersection(geom, ST_MakeEnvelope(
                       {origin_west} + x * {TILE_LNG}, {origin_south} + y * {TILE_LAT},
                       {origin_west} + (x + 1) * {TILE_LNG}, {origin_south} + (y + 1) * {TILE_LAT})), 3), {SIMPLIFY_DEG}) AS g
            FROM b, range(x0, x1 + 1) AS rx(x), range(y0, y1 + 1) AS ry(y)
        )
        SELECT x, y, [[ST_X(p.geom), ST_Y(p.geom)] FOR p IN ST_Dump(ST_Points(ring.geom))] AS coords
        FROM clipped, LATERAL (SELECT unnest(ST_Dump(ST_Boundary(g))) AS ring)
        WHERE NOT ST_IsEmpty(g)
    """)


def encode(rows):
    """{(x, y): {layer: [[x0, y0, dx1, dy1, ...], ...]}} from (x, y, layer, [[lng, lat], ...]) rows."""
    south, _, west, _ = SERVICE_AREA
    tiles = {}
    for x, y, layer, coords in rows:
        ox, oy = west + x * TILE_LNG, south + y * TILE_LAT
        flat, px, py = [], None, None
        for lng, lat in coords:
            qx, qy = round((lng - ox) / QUANTUM), round((lat - oy) / QUANTUM)
            flat += [qx, qy] if px is None else [qx - px, qy - py]
            px, py = qx, qy
        tiles.setdefault((x, y), {}).setdefault(layer, []).append(flat)
    return tiles


def write(tiles, out):
    south, _, west, _ = SERVICE_AREA
    staging = Path(tempfile.mkdtemp(dir=out.parent))
    for (x, y), layers in tiles.items():
        (staging / f'{x}_{y}.json').write_text(json.dumps(layers, separators=(',', ':')))
    (staging / 'index.json').write_text(json.dumps({
        'origin': [south, west], 'tile': [TILE_LAT, TILE_LNG], 'quantum': QUANTUM,
        'layers': DRAWN, 'tiles': sorted(f'{x}_{y}' for x, y in tiles),
        'attribution': '© OpenStreetMap contributors',
    }, separators=(',', ':')))
    if out.exists():
        shutil.rmtree(out)
    staging.rename(out)


def main(argv=None):
    import duckdb
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--pbf', type=Path, help='an OSM extract; downloaded from BBBike when omitted')
    parser.add_argument('--out', type=Path, default=OUT_DIR)
    parser.add_argument('--memory-limit', default='2GB')
    args = parser.parse_args(argv)
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
        tiles = build(con, str(pbf).replace("'", "''"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write(tiles, args.out)
    size = sum(f.stat().st_size for f in args.out.iterdir())
    print(f'{len(tiles)} tiles, {size / 1e6:.1f} MB -> {args.out}')


if __name__ == '__main__':
    main()
