import datetime as dt
import json

import duckdb

import bikes.weather_history as wh
from bikes.model import observed_weather

IEM = (
    'station,valid,tmpc,p01m,wxcodes\n'
    'NYC,2026-01-25 13:51,-3.30,1.02,-SN BR\n'
    'NYC,2026-01-25 14:51,-3.90,null,null\n'
    'LGA,2026-01-25 13:51,-2.80,0.76,-SN\n'
    # Outside the requested days: the archive pads by a day either side.
    'NYC,2026-01-27 00:51,-8.00,0.00,null\n'
)


def test_observed_keeps_each_station_hour_and_flags_snow(monkeypatch):
    monkeypatch.setattr(wh, 'get', lambda url, timeout=300: IEM)
    rows = wh.observed(dt.date(2026, 1, 25), dt.date(2026, 1, 26))
    assert rows == [
        (dt.datetime(2026, 1, 25, 13), 'NYC', 'obs', -3.3, 1.02, None, True, '-SN BR'),
        (dt.datetime(2026, 1, 25, 14), 'NYC', 'obs', -3.9, None, None, False, None),
        (dt.datetime(2026, 1, 25, 13), 'LGA', 'obs', -2.8, 0.76, None, True, '-SN'),
    ]


def test_modeled_maps_each_location_to_its_station(monkeypatch):
    places = [{'hourly': {'time': ['2026-01-25T13:00'], 'temperature_2m': [t], 'precipitation': [1.0],
                          'snowfall': [0.7 if t < 0 else 0.0]}} for t in (-3.0, -2.0, 1.0, -4.0)]
    monkeypatch.setattr(wh, 'get', lambda url, timeout=300: json.dumps(places))
    rows = wh.modeled(dt.date(2026, 1, 25), dt.date(2026, 1, 25))
    assert [(r[1], r[3], r[6]) for r in rows] == [('NYC', -3.0, True), ('LGA', -2.0, True), ('JFK', 1.0, False),
                                                    ('EWR', -4.0, True)]


def test_observed_weather_takes_snow_from_the_observer_and_depth_from_the_model(tmp_path):
    con = duckdb.connect()
    path = tmp_path / 'w.parquet'
    rows = [(dt.datetime(2026, 1, 25, 13), 'NYC', 'obs', -3.3, 1.0, None, True, '-SN'),
            (dt.datetime(2026, 1, 25, 13), 'NYC', 'model', -3.0, 0.9, 1.4, True, None),
            # The model snows; the observer saw rain.
            (dt.datetime(2026, 1, 25, 14), 'NYC', 'obs', 0.5, 2.0, None, False, 'RA'),
            (dt.datetime(2026, 1, 25, 14), 'NYC', 'model', 0.2, 1.5, 0.8, True, None),
            # Observed snow the model missed still counts as snow.
            (dt.datetime(2026, 1, 25, 15), 'NYC', 'obs', -1.0, 0.3, None, True, '-SN'),
            (dt.datetime(2026, 1, 25, 15), 'LGA', 'obs', -1.0, 9.0, None, True, '+SN')]
    wh.write_year(con, path, rows)
    con.execute(f"CREATE VIEW weather AS SELECT * FROM read_parquet('{path}')")
    assert observed_weather(con, dt.date(2026, 1, 25), dt.date(2026, 1, 25)) == [
        ('2026-01-25T13:00', -3.3, 1.0, 1.4), ('2026-01-25T14:00', 0.5, 2.0, 0.0), ('2026-01-25T15:00', -1.0, 0.3, 0.2)]
