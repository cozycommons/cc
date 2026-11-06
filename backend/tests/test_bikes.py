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
    # STOCKED has no history, so its 5 bikes are certain to last; PENN refills once an hour.
    assert (other['status'], other['chance'], result['best']['station']) == ('available', 1.0, 'W 37 St & Broadway')
    assert result['message'] == ('Walk to W 37 St & Broadway, a 10-minute walk: 5 bikes now. '
                                 'The nearest, W 33 St & 7 Ave, is empty: about 60 minutes expected.')


def test_busy_empty_station_is_worth_waiting_at():
    result = nearby(MODEL, [STOCKED, EMPTY_PENN], PENN.lat, PENN.lng, WEDNESDAY.replace(hour=17))
    assert result['best']['station'] == 'W 33 St & 7 Ave'
    assert result['message'] == ('Walk to W 33 St & 7 Ave, a 1-minute walk. '
                                 'It is empty, but a bike usually comes back in about 1 minute.')
    assert result['best']['expected_min'] == 1.0


def test_need_dock_uses_departures_and_closed_stations_are_out():
    closed = Dock(**{**STOCKED.__dict__, 'returning': False})
    result = nearby(MODEL, [closed, PENN], PENN.lat, PENN.lng, WEDNESDAY.replace(hour=17), need='dock')
    assert [s['status'] for s in result['stations']] == ['full', 'closed']
    assert result['best']['station'] == 'W 33 St & 7 Ave' and result['best']['expected_min'] == 1.0


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


def test_stale_feed_is_served_while_one_refresh_runs(monkeypatch):
    gbfs.reset_cache()
    fetched, started = [], []
    monkeypatch.setattr(gbfs, '_fetch', lambda feed: fetched.append(feed) or [{'v': len(fetched)}])
    monkeypatch.setattr(gbfs, 'start_refresh', started.append)
    assert gbfs._feed('station_status') == [{'v': 1}]  # cold: fetched inline

    gbfs._cache['station_status'] = (gbfs.time.monotonic() - 120, [{'v': 'old'}])
    assert gbfs._feed('station_status') == [{'v': 'old'}]  # past TTL: no wait
    assert gbfs._feed('station_status') == [{'v': 'old'}]
    assert started == ['station_status'] and fetched == ['station_status']  # one refresh, not inline

    def fail(feed):
        raise gbfs.GbfsError('timeout')
    monkeypatch.setattr(gbfs, '_fetch', fail)
    gbfs._refresh('station_status')  # what the thread runs
    assert gbfs._feed('station_status') == [{'v': 'old'}] and 'station_status' in started

    gbfs._cache['station_status'] = (gbfs.time.monotonic() - 600, [{'v': 'old'}])
    with pytest.raises(gbfs.GbfsError):  # too stale to serve: fetch inline, and surface the failure
        gbfs._feed('station_status')
    gbfs.reset_cache()


from bikes.forecast import chance, distribution
from bikes.plan import plan
from bikes.recorder import Recorder

# Two departures a minute at 17:00 on weekdays, no arrivals.
DRAIN = {**MODEL, 'stations': {'d': [0] * 17 + [12000] + [0] * 30}, 'arrivals': {'d': [0] * 48}, 'ebike_share': 0.25}


def test_forecast_drains_a_busy_station_and_stops_at_empty():
    five_pm = WEDNESDAY.replace(hour=17)
    p = distribution(DRAIN, 'd', 3, 10, five_pm, 5)
    assert abs(sum(p) - 1) < 1e-9 and p[0] > 0.9  # ten expected departures, three bikes
    one = Dock('d', 'Drain', 40.75, -73.99, 7, True, bikes=3, ebikes=1)
    assert chance(DRAIN, one, 'bike', five_pm, 0) == 1.0
    assert chance(DRAIN, one, 'bike', five_pm, 1) > chance(DRAIN, one, 'bike', five_pm, 3)
    assert chance(DRAIN, one, 'dock', five_pm, 3) == 1.0  # departures only open docks
    assert chance(DRAIN, one, 'ebike', five_pm, 1) > 0.5  # e-bikes leave at a quarter of the rate
    assert chance(DRAIN, one, 'bike', five_pm, 61) is None
    assert chance(DRAIN, Dock(**{**one.__dict__, 'renting': False}), 'bike', five_pm, 1) is None


def test_plan_picks_the_pair_with_the_lowest_expected_time():
    origin, destination = (40.7500, -73.9900), (40.7800, -73.9700)
    near_empty = Dock('a', 'Near but empty', 40.7502, -73.9902, 9, True, bikes=0)
    stocked = Dock('b', 'Stocked', 40.7520, -73.9910, 4, True, bikes=6)
    end = Dock('c', 'Open end', 40.7798, -73.9702, 5, True, bikes=10)
    model = {**MODEL, 'stations': {}, 'arrivals': {'a': [10] * 48}}  # 'a' refills every ~10 hours
    result = plan(model, [near_empty, stocked, end], origin, destination,
                  WEDNESDAY.replace(hour=12), WEDNESDAY.replace(hour=12), live=True)
    assert (result['best']['start']['station'], result['best']['end']['station']) == ('Stocked', 'Open end')
    assert result['best']['start']['chance'] == 1.0
    assert result['walk_only_min'] > result['best']['expected_min']
    assert result['message'].startswith('Walk 4 minutes to Stocked, ride ')
    later = plan(model, [near_empty, stocked, end], origin, destination,
                 WEDNESDAY.replace(hour=12), WEDNESDAY.replace(hour=15), live=False)
    assert later['best']['start']['chance'] is None and later['best']['expected_min'] == later['best']['minutes']


def test_plan_needs_a_station_at_each_end(client):
    http, _ = client
    response = http.get('/bikes/plan', params={'from_lat': PENN.lat, 'from_lng': PENN.lng,
                                              'to_lat': PENN.lat + 0.0005, 'to_lng': PENN.lng, 'format': 'text'})
    assert response.status_code == 200 and response.text == 'No Citi Bike stations near both ends of this trip.'


def test_live_route_is_columnar(client):
    http, _ = client
    body = http.get('/bikes/live').json()
    assert body['stations']['id'] == [PENN.short_name] and body['stations']['flags'] == [2]  # returning, not renting


def test_recorder_writes_only_changed_reports(tmp_path, monkeypatch):
    import csv, gzip
    feeds = {
        'station_information': [{'station_id': 'u1', 'short_name': '6230.04'}, {'station_id': 'u2', 'short_name': '1.01'}],
        'station_status': [
            {'station_id': 'u1', 'is_installed': 1, 'is_renting': 1, 'is_returning': 1, 'last_reported': 100,
             'num_bikes_available': 3, 'num_ebikes_available': 1, 'num_docks_available': 7},
            {'station_id': 'u2', 'is_installed': 1, 'is_renting': 1, 'is_returning': 1, 'last_reported': 100,
             'num_bikes_available': 0, 'num_docks_available': 9}],
    }
    monkeypatch.setattr(gbfs, '_fetch', lambda feed: feeds[feed])
    recorder = Recorder(tmp_path)
    assert recorder.poll(now=1_783_000_000) == 2
    feeds['station_status'][0] = {**feeds['station_status'][0], 'last_reported': 160, 'num_bikes_available': 2}
    assert recorder.poll(now=1_783_000_060) == 1
    path, = tmp_path.iterdir()
    with gzip.open(path, 'rt') as f:
        rows = list(csv.DictReader(f))
    assert [(r['station_id'], r['bikes']) for r in rows] == [('6230.04', '3'), ('1.01', '0'), ('6230.04', '2')]


def test_low_odds_are_spelled_out_and_a_rarely_refilled_station_still_counts():
    five_pm = WEDNESDAY.replace(hour=17)
    one_left = Dock('d', 'Drain', 40.7500, -73.9900, 9, True, bikes=1)
    far = Dock('f', 'Far', 40.7590, -73.9900, 9, True, bikes=8)
    # Two departures a minute and no returns: its one bike rarely survives the walk, so walk on.
    result = nearby(DRAIN, [one_left, far], 40.7495, -73.9900, five_pm)
    assert result['stations'][0]['chance'] < 0.2 and result['best']['station'] == 'Far'
    assert result['message'].endswith('The nearest, Drain, has 1, 9% likely to last until you arrive.')
    quiet = nearby(DRAIN, [one_left, far], 40.7495, -73.9900, WEDNESDAY.replace(hour=3))
    assert quiet['best']['station'] == 'Drain' and quiet['message'] == 'Walk to Drain, a 1-minute walk: 1 bike now.'


def test_plan_accepts_the_depart_format_the_page_sends(client):
    from datetime import datetime, timedelta, timezone
    http, _ = client
    soon = (datetime.now(timezone.utc) + timedelta(minutes=30)).strftime('%Y-%m-%dT%H:%MZ')
    later = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%MZ')
    trip = {'from_lat': PENN.lat, 'from_lng': PENN.lng, 'to_lat': 40.7295, 'to_lng': -73.9965}
    assert http.get('/bikes/plan', params={**trip, 'depart': soon}).json()['live'] is True
    assert http.get('/bikes/plan', params={**trip, 'depart': later}).json()['live'] is False
