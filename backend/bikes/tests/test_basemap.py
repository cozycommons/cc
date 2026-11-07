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


def test_street_labels_read_like_station_names_and_turn_along_the_street():
    from bikes.basemap import short_name, street_labels
    assert short_name('West 31st Street') == 'W 31 St'
    assert short_name('7th Avenue') == '7 Ave'
    assert short_name('McGuinness Boulevard') == 'McGuinness Blvd'
    # A Manhattan cross street runs about 29 degrees off east-west; its label turns with it, upright.
    labels = street_labels([('West 35th Street', [[-73.9958, 40.7541], [-73.9990, 40.7555]])])
    [(qx, qy, degrees, text)] = next(iter(labels.values()))
    assert (text, 25 <= degrees <= 35) == ('W 35 St', True)
    assert street_labels([('Tiny Lane', [[-73.99, 40.75], [-73.99001, 40.75]])]) == {}
