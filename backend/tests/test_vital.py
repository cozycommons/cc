from datetime import date, datetime

from vital import busy, recorder


def test_record_writes_header_once(tmp_path):
    recorder.record(tmp_path, 31, now=1_700_000_000)
    recorder.record(tmp_path, 29, now=1_700_000_300)
    assert (tmp_path / 'occupancy.csv').read_text() == 'recorded_at,people\n1700000000,31\n1700000300,29\n'


def test_recorded_times_are_new_york_local(tmp_path):
    # 2026-11-07 01:00 UTC is Friday 20:00 in New York (EST).
    recorder.record(tmp_path, 191, now=datetime.fromisoformat('2026-11-07T01:00:00+00:00').timestamp())
    assert list(busy.read_recorded(tmp_path / 'occupancy.csv')) == [(datetime(2026, 11, 6, 20, 0), 191)]


def test_read_scrape_skips_header_and_broken_rows(tmp_path):
    path = tmp_path / 'occupancy.csv'
    path.write_text('People at Gym, Timestamp\n31, Tue Mar 22 23:14:49 EDT 2022\n, Tue Mar 22 23:19:25 EDT 2022\n'
                    '0, Fri Nov  6 04:30:58 EST 2026\n')
    assert list(busy.read_scrape(path)) == [(datetime(2022, 3, 22, 23, 14, 49), 31), (datetime(2026, 11, 6, 4, 30, 58), 0)]


def test_quietest_hour_ignores_closed_hours():
    friday = [(datetime(2026, 11, 6, hour, minute), people)
              for hour, people in [(2, 0), (9, 80), (12, 40), (19, 300)] for minute in range(0, 50, 10)]
    medians = busy.hourly(friday + [(datetime(2025, 1, 3, 12), 999)], since=date(2026, 1, 1))
    assert medians[4, 12] == 40
    assert 'Fri: busiest 19:00 (300), quietest open hour 12:00 (40)' in busy.report(medians)


def vital_client(monkeypatch, fetch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from vital import feed, routes
    monkeypatch.setattr(feed, 'fetch', fetch)
    monkeypatch.setattr(routes, '_live', None)
    monkeypatch.setattr(routes, '_failed_at', 0.0)
    app = FastAPI()
    app.include_router(routes.router, prefix='/vital')
    return TestClient(app), routes


def test_now_caches_the_count_and_adds_the_typical_hour(monkeypatch):
    calls = []
    client, routes = vital_client(monkeypatch, lambda: calls.append(1) or 191)
    friday_8pm = datetime.fromisoformat('2026-11-06T20:05:00-05:00').timestamp()
    monkeypatch.setattr(routes.time, 'time', lambda: friday_8pm)
    first, second = client.get('/vital/now').json(), client.get('/vital/now').json()
    assert first == second == {'people': 191, 'at': '2026-11-06T20:05:00-05:00',
                               'typical': routes.typical_week()['hours'][4][20]}
    assert len(calls) == 1


def test_now_fails_fast_after_an_outage(monkeypatch):
    from vital import feed
    calls = []

    def down():
        calls.append(1)
        raise feed.FeedError('TimeoutError')
    client, _ = vital_client(monkeypatch, down)
    assert [client.get('/vital/now').status_code for _ in range(3)] == [503, 503, 503]
    assert len(calls) == 1


def test_committed_week_has_every_weekday_hour():
    from vital import routes
    week = routes.typical_week()
    assert len(week['hours']) == 7 and all(len(day) == 24 for day in week['hours'])
