import datetime as dt

import duckdb

from bikes.model import build, explore, month_window


def trips(con, rows):
    con.execute("""CREATE TABLE trips (ride_id VARCHAR, started_at TIMESTAMP, ended_at TIMESTAMP,
        start_station_id VARCHAR, start_station_name VARCHAR, end_station_id VARCHAR, start_lat DOUBLE, start_lng DOUBLE,
        end_lat DOUBLE, end_lng DOUBLE, member_casual VARCHAR, system VARCHAR, year INTEGER, month INTEGER)""")
    con.executemany('INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)
    # Every third trip is on an e-bike.
    con.execute("ALTER TABLE trips ADD COLUMN rideable_type VARCHAR")
    con.execute("UPDATE trips SET rideable_type = CASE WHEN hash(started_at, start_station_id) % 3 = 0 THEN 'electric_bike' ELSE 'classic_bike' END")


def test_rates_count_only_days_a_station_existed():
    con = duckdb.connect()
    rows = []
    # Every trip rides 0.0162 degrees of latitude (1.8 km) in 10 minutes: 3 m/s.
    # July 2026 has 23 weekdays and 8 weekend days. A: two 17:00 weekday departures a day.
    for day in range(1, 32):
        if dt.date(2026, 7, day).weekday() < 5:
            rows += [('a', f'2026-07-{day:02d} 17:{m:02d}:00') for m in (5, 35)]
    # B opens Monday July 20: 10 weekdays and 2 weekend days remain; one 08:00 departure each weekday.
    rows += [('b', f'2026-07-{day:02d} 08:00:00') for day in (20, 21, 22, 23, 24, 27, 28, 29, 30, 31)]
    trips(con, [('r', start, None, station, station.upper(), 'end', 40.70, -74.0, 40.7162, -74.0, 'member', 'nyc',
                 2026, 7) for station, start in rows])
    # A Lyft test station in Los Angeles appears in the NYC files.
    con.execute("INSERT INTO trips SELECT 'r', TIMESTAMP '2026-07-01 12:00', TIMESTAMP '2026-07-01 12:10', 'LA Metro Demo 2', "
                "'LA Metro Demo 2', 'end', 34.026, -118.25, 34.04, -118.25, 'member', 'nyc', 2026, 7, 'classic_bike'")
    con.execute("UPDATE trips SET ended_at = started_at + INTERVAL 10 MINUTE, rideable_type = coalesce(rideable_type, 'classic_bike')")

    model, places, monthly = build(con, months=1)
    assert model['window'] == ['2026-07', '2026-07']
    assert model['stations']['a'][17] == 200  # 46 departures / 23 weekdays
    assert model['stations']['a'][24 + 17] == 0
    assert model['stations']['b'][8] == 100  # 10 / 10 weekdays since opening, not / 23
    assert model['ride_mps'] == 3.0
    assert model['month_factor'][6] == 1.0
    assert 'LA Metro Demo 2' not in model['stations']
    assert 0.2 < model['ebike_share'] < 0.5
    # Every trip ends at 'end', which has no departures, so no place: only a and b keep arrival rows.
    assert set(model['arrivals']) == {'a', 'b'} and model['arrivals']['a'] == [0] * 48
    assert monthly == {'month': ['2026-07'], 'nyc': [57], 'jc': [0]}
    stations = explore(model, places, monthly)['stations']
    assert (stations['id'], stations['name'], stations['lat']) == (['a', 'b'], ['A', 'B'], [40.7, 40.7])


def test_month_window_crosses_years():
    assert month_window(202602, 4) == [202511, 202512, 202601, 202602]


def test_arrivals_count_trip_ends_by_end_hour():
    con = duckdb.connect()
    days = [day for day in range(1, 32) if dt.date(2026, 7, day).weekday() < 5]
    # a -> b at 08:50 every weekday, arriving 09:00; b -> a once a day so b has a place.
    rows = [('r', f'2026-07-{d:02d} 08:50:00', f'2026-07-{d:02d} 09:00:00', 'a', 'A', 'b', 40.70, -74.0, 40.7162, -74.0,
             'member', 'nyc', 2026, 7) for d in days]
    rows += [('r', f'2026-07-{d:02d} 18:00:00', f'2026-07-{d:02d} 18:10:00', 'b', 'B', 'a', 40.7162, -74.0, 40.70, -74.0,
              'member', 'nyc', 2026, 7) for d in days]
    trips(con, rows)
    model, _, _ = build(con, months=1)
    assert model['arrivals']['b'][9] == 100 and model['arrivals']['b'][8] == 0
    assert model['stations']['b'][18] == 100


def test_weather_table_finds_fewer_trips_in_rain(monkeypatch):
    import bikes.model as model_module
    monkeypatch.setattr(model_module, 'WEATHER_MIN_EXPECTED', 0)
    monkeypatch.setattr(model_module, 'WEATHER_MIN_HOURS', 1)
    con = duckdb.connect()
    weekdays = [d for d in range(1, 32) if dt.date(2026, 7, d).weekday() < 5]
    rainy = set(weekdays[:8])
    # Four 17:00 departures on dry weekdays, two when it rains.
    rows = [('r', f'2026-07-{d:02d} 17:{m:02d}:00', None, 'a', 'A', 'b', 40.70, -74.0, 40.7162, -74.0, 'member', 'nyc', 2026, 7)
            for d in weekdays for m in ((5, 35) if d in rainy else (5, 20, 35, 50))]
    trips(con, rows)
    con.execute("UPDATE trips SET ended_at = started_at + INTERVAL 10 MINUTE")

    def weather(first, last):
        return [(f'2026-07-{d:02d}T{h:02d}:00', 22.0, 3.0 if d in rainy and h == 17 else 0.0, 0.0)
                for d in range(1, 32) for h in range(24)]
    model, _, _ = build(con, months=1, weather=weather)
    table = model['weather']
    assert table['by_sky']['heavy rain'] < table['by_sky']['dry']
    assert abs(table['by_sky']['heavy rain'] / table['by_sky']['dry'] - 0.5) < 0.01
