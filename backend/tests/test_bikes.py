from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from bikes import gbfs, routes
from bikes.wait import Dock, decide, minutes, nearby

# Weekday 17:00 is busy (60 departures/hour, one a minute); 03:00 has one an hour.
SLOTS = [100] * 48
SLOTS[17] = 6000
MODEL = {'window': ['2025-11', '2026-10'], 'ride_mps': 3.0, 'month_factor': [1.0] * 12,
         'stations': {'6230.04': SLOTS}, 'arrivals': {'6230.04': SLOTS}}
PENN = Dock('6230.04', 'W 33 St & 7 Ave', 40.7502, -73.9916, 0, True)
# About 590 m away: a 3-minute ride plus a 10-minute walk back.
OPEN = Dock('6364.07', 'W 37 St & Broadway', 40.7546, -73.9876, 4, True)
WEDNESDAY = datetime(2026, 7, 15)


def test_busy_full_dock_says_wait():
    result = decide(MODEL, [PENN, OPEN], PENN.lat, PENN.lng, WEDNESDAY.replace(hour=17))
    assert result['decision'] == 'wait'
    assert result['wait_min'] == 1.0
    assert result['message'].startswith('Wait. A dock here usually opens in about 1 minute.')


def test_quiet_full_dock_says_ride():
    result = decide(MODEL, [PENN, OPEN], PENN.lat, PENN.lng, WEDNESDAY.replace(hour=3))
    assert result['decision'] == 'ride'
    assert result['alternative']['station'] == 'W 37 St & Broadway'
    assert result['message'] == ('Ride to W 37 St & Broadway: 4 open, a 3-minute ride and a 10-minute walk back. '
                                 'A dock here usually opens in about 60 minutes.')


def test_open_dock_and_dead_end():
    open_here = Dock(**{**PENN.__dict__, 'docks': 2})
    assert decide(MODEL, [open_here], PENN.lat, PENN.lng, WEDNESDAY)['message'] == \
        'Dock now at W 33 St & 7 Ave: 2 open docks.'
    unknown = Dock('9999.99', 'Nowhere', 40.85, -73.88, 0, True)
    assert decide(MODEL, [unknown], 40.85, -73.88, WEDNESDAY)['decision'] == 'unknown'


@pytest.fixture
def client(monkeypatch):
    feeds = {
        'station_information': [{'station_id': 'a', 'short_name': PENN.short_name, 'name': PENN.name,
                                 'lat': PENN.lat, 'lon': PENN.lng}],
        'station_status': [{'station_id': 'a', 'is_installed': 1, 'is_returning': 1, 'num_docks_available': 3}],
    }
    gbfs.reset_cache()
    monkeypatch.setattr(gbfs, '_fetch', lambda feed: feeds[feed])
    monkeypatch.setattr(routes, 'load_model', lambda: MODEL)
    app = FastAPI()
    app.include_router(routes.router, prefix='/bikes')
    yield TestClient(app), feeds
    gbfs.reset_cache()


def test_route_speaks_plain_text_for_siri(client):
    http, _ = client
    response = http.get('/bikes/wait-or-ride', params={'lat': PENN.lat, 'lng': PENN.lng, 'format': 'text'})
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/plain')
    assert response.text == 'Dock now at W 33 St & 7 Ave: 3 open docks.'
    assert http.get('/bikes/wait-or-ride', params={'lat': 51.5, 'lng': -0.1}).status_code == 422


def test_route_hides_feed_failures(client, monkeypatch):
    http, _ = client

    def fail(feed):
        raise gbfs.GbfsError(f'{feed}: URLError')
    monkeypatch.setattr(gbfs, '_fetch', fail)
    response = http.get('/bikes/wait-or-ride', params={'lat': PENN.lat, 'lng': PENN.lng})
    assert response.status_code == 503
    assert 'URLError' not in response.text


def test_minute_phrases():
    assert [minutes(v, True) for v in (1, 8, 11, 18, 21, 84)] == [
        'a 1-minute', 'an 8-minute', 'an 11-minute', 'an 18-minute', 'a 21-minute', 'an 84-minute']
    assert (minutes(0.2), minutes(2)) == ('1 minute', '2 minutes')


# Bike returns at PENN: 60 an hour at 17:00, one an hour otherwise. OPEN has no history.
EMPTY_PENN = Dock('6230.04', 'W 33 St & 7 Ave', 40.7502, -73.9916, 10, True, bikes=0)
STOCKED = Dock('6364.07', 'W 37 St & Broadway', 40.7546, -73.9876, 4, True, bikes=5)


def test_empty_nearest_station_loses_to_a_stocked_one_at_a_quiet_hour():
    result = nearby(MODEL, [STOCKED, EMPTY_PENN], PENN.lat, PENN.lng, WEDNESDAY.replace(hour=3))
    nearest, other = result['stations']
    assert (nearest['station'], nearest['status'], nearest['wait_min']) == ('W 33 St & 7 Ave', 'empty', 60.0)
    assert (other['status'], other['wait_min'], result['best']['station']) == ('available', 0.0, 'W 37 St & Broadway')
    assert result['message'] == ('Walk to W 37 St & Broadway, a 10-minute walk: 5 bikes now. '
                                 'The nearest, W 33 St & 7 Ave, is empty: about 60 minutes with the wait.')


def test_busy_empty_station_is_worth_waiting_at():
    result = nearby(MODEL, [STOCKED, EMPTY_PENN], PENN.lat, PENN.lng, WEDNESDAY.replace(hour=17))
    assert result['best']['station'] == 'W 33 St & 7 Ave'
    assert result['message'] == ('Walk to W 33 St & 7 Ave, a 1-minute walk. '
                                 'It is empty, but a bike usually comes back in about 1 minute.')


def test_need_dock_uses_departures_and_closed_stations_are_out():
    closed = Dock(**{**STOCKED.__dict__, 'returning': False})
    result = nearby(MODEL, [closed, PENN], PENN.lat, PENN.lng, WEDNESDAY.replace(hour=17), need='dock')
    assert [s['status'] for s in result['stations']] == ['full', 'closed']
    assert result['best']['station'] == 'W 33 St & 7 Ave' and result['best']['wait_min'] == 1.0


def test_arbitrary_time_gives_conditional_waits_without_live_counts():
    result = nearby(MODEL, [EMPTY_PENN], PENN.lat, PENN.lng, WEDNESDAY.replace(hour=3), live=False, limit=1)
    station, = result['stations']
    assert result['best'] is None and 'status' not in station
    assert (station['wait_if_empty_min'], station['wait_if_full_min']) == (60.0, 60.0)
    assert result['message'] == ('At 3 AM on a weekday, the nearest station is W 33 St & 7 Ave, a 1-minute walk. '
                                 'If it is empty, a bike usually comes back in about 60 minutes; '
                                 'if it is full, a dock usually opens in about 60 minutes.')


def test_wait_route_reads_at_as_new_york_time(client):
    http, _ = client
    response = http.get('/bikes/wait', params={'lat': PENN.lat, 'lng': PENN.lng, 'at': '2026-07-18T03:00'})
    assert response.status_code == 200
    body = response.json()
    assert (body['at'], body['live'], body['need']) == ('2026-07-18T03:00-04:00', False, 'bike')
    assert body['message'].startswith('At 3 AM on a weekend, the nearest station is W 33 St & 7 Ave')
    live = http.get('/bikes/wait', params={'lat': PENN.lat, 'lng': PENN.lng, 'need': 'dock', 'format': 'text'})
    assert live.text == 'Walk to W 33 St & 7 Ave, a 1-minute walk: 3 open docks now.'
    assert http.get('/bikes/wait', params={'lat': PENN.lat, 'lng': PENN.lng, 'limit': 11}).status_code == 422


def test_durations_switch_to_hours():
    from bikes.wait import duration
    assert [duration(v) for v in (0.4, 12, 89, 90, 150)] == [
        'about 1 minute', 'about 12 minutes', 'about 89 minutes', 'about 2 hours', 'about 2 hours']
