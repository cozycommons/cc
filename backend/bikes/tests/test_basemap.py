from bikes.basemap import QUANTUM, TILE_LAT, TILE_LNG, encode
from bikes.model import SERVICE_AREA


def test_tiles_are_delta_coded_from_the_tile_corner():
    south, _, west, _ = SERVICE_AREA
    ox, oy = west + 3 * TILE_LNG, south + 2 * TILE_LAT
    line = [[ox + 0.00010, oy + 0.00020], [ox + 0.00110, oy + 0.00020], [ox + 0.00110, oy + 0.00520]]
    tiles = encode([(3, 2, 'minor', line), (3, 2, 'major', line[:2])])
    # The same fixture is decoded in frontend/src/bikes/basemap.test.js.
    assert tiles == {(3, 2): {'minor': [[10, 20, 100, 0, 0, 500]], 'major': [[10, 20, 100, 0]]}}
    assert QUANTUM == 1e-5
