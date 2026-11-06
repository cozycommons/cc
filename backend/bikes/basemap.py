"""Build the /bikes street basemap: static JSON tiles cut from an OpenStreetMap extract.

The page draws streets, bike lanes, parks and shoreline under the live station
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

Data © OpenStreetMap contributors, ODbL; the page credits it.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request

from .model import SERVICE_AREA

EXTRACT_URL = 'https://download.bbbike.org/osm/bbbike/NewYork/NewYork.osm.pbf'
OUT_DIR = Path(__file__).resolve().parents[2] / 'frontend/public/bikes/map'
# About 1.1 km each way at New York's latitude.
TILE_LAT, TILE_LNG = 0.01, 0.013
QUANTUM = 1e-5  # degrees, about 1 m
SIMPLIFY_DEG = 2e-5

LAYERS = {
    'major': "highway IN ('motorway', 'trunk', 'primary', 'secondary', 'motorway_link', 'trunk_link', "
             "'primary_link', 'secondary_link')",
    'minor': "highway IN ('tertiary', 'tertiary_link', 'residential', 'unclassified', 'living_street', 'pedestrian')",
    'bike': "highway = 'cycleway' OR (highway = 'path' AND bicycle IN ('designated', 'yes'))",
    'park': "leisure IN ('park', 'garden', 'playground') AND closed",
    'water': "\"natural\" = 'coastline' OR (\"natural\" = 'water' AND closed) OR waterway = 'riverbank'",
}


def build(con, pbf):
    south, north, west, east = SERVICE_AREA
    con.execute(f"""
        CREATE TEMP TABLE ways AS
        SELECT id, refs, tags['highway'] AS highway, tags['leisure'] AS leisure, tags['natural'] AS "natural",
               tags['waterway'] AS waterway, tags['bicycle'] AS bicycle, refs[1] = refs[-1] AS closed
        FROM ST_ReadOSM('{pbf}')
        WHERE kind = 'way' AND (tags['highway'] IS NOT NULL OR tags['leisure'] IS NOT NULL
              OR tags['natural'] IN ('coastline', 'water') OR tags['waterway'] = 'riverbank')
    """)
    layer = 'CASE ' + ' '.join(f"WHEN {cond} THEN '{name}'" for name, cond in LAYERS.items()) + ' END'
    con.execute(f"CREATE TEMP TABLE kept AS SELECT id, refs, {layer} AS layer FROM ways WHERE ({layer}) IS NOT NULL")
    con.execute(f"""
        CREATE TEMP TABLE nodes AS
        SELECT id, lat, lon FROM ST_ReadOSM('{pbf}')
        WHERE kind = 'node' AND id IN (SELECT DISTINCT unnest(refs) FROM kept)
    """)
    # Each way's points in order, simplified, kept if it touches the service area.
    con.execute(f"""
        CREATE TEMP TABLE shapes AS
        WITH points AS (
            SELECT k.id, k.layer, p.i, n.lat, n.lon
            FROM kept k, LATERAL (SELECT unnest(k.refs) AS ref, generate_subscripts(k.refs, 1) AS i) p
            JOIN nodes n ON n.id = p.ref
        ), lines AS (
            SELECT id, any_value(layer) AS layer,
                   ST_MakeLine(list(ST_Point(lon, lat) ORDER BY i)) AS geom
            FROM points GROUP BY id HAVING count(*) >= 2
        )
        SELECT id, layer, ST_Simplify(geom, {SIMPLIFY_DEG}) AS geom FROM lines
        WHERE ST_Intersects(geom, ST_MakeEnvelope({west}, {south}, {east}, {north}))
    """)
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
    """).fetchall()
    return encode(rows)


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
        'layers': list(LAYERS), 'tiles': sorted(f'{x}_{y}' for x, y in tiles),
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
