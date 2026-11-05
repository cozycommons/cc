import datetime as dt

import duckdb

from bikes.model import build, month_window


def trips(con, rows):
    con.execute("""CREATE TABLE trips (ride_id VARCHAR, started_at TIMESTAMP, ended_at TIMESTAMP,
        start_station_id VARCHAR, end_station_id VARCHAR, start_lat DOUBLE, start_lng DOUBLE,
        end_lat DOUBLE, end_lng DOUBLE, member_casual VARCHAR, year INTEGER, month INTEGER)""")
    con.executemany('INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', rows)


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
    trips(con, [('r', start, None, station, 'end', 40.70, -74.0, 40.7162, -74.0, 'member', 2026, 7)
                for station, start in rows])
    con.execute("UPDATE trips SET ended_at = started_at + INTERVAL 10 MINUTE")

    model = build(con, months=1)
    assert model['window'] == ['2026-07', '2026-07']
    assert model['stations']['a'][17] == 200  # 46 departures / 23 weekdays
    assert model['stations']['a'][24 + 17] == 0
    assert model['stations']['b'][8] == 100  # 10 / 10 weekdays since opening, not / 23
    assert model['ride_mps'] == 3.0
    assert model['month_factor'][6] == 1.0


def test_month_window_crosses_years():
    assert month_window(202602, 4) == [202511, 202512, 202601, 202602]
