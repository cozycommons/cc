"""Offline gateway contracts: clocks and transports are always injected."""
import gzip
import io
import json
import multiprocessing
import threading
import urllib.error
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import format_datetime

import pytest

from espn.read_gateway import (ReadGateway, AuthRejected, BudgetExceeded,
                               CircuitOpen, GatewayError)

URL = 'https://example.test/league?view=mTeam&view=mRoster'


class Clock:
    def __init__(self):
        self.now = 1800000000.0
        self.waits = []

    def __call__(self):
        return self.now

    def sleep(self, duration):
        self.waits.append(duration)
        self.now += duration


class Response:
    def __init__(self, data, compressed=False):
        self.body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.headers = {}
        if compressed:
            self.body = gzip.compress(self.body)
            self.headers['Content-Encoding'] = 'gzip'

    def read(self, size=-1):
        return self.body[:size] if size >= 0 else self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def setup(tmp_path, **kwargs):
    clock = Clock()
    return ReadGateway(tmp_path, limits={'test': (1, 1)}, daily_budget=kwargs.pop('budget', 10),
                       clock=clock, sleep=clock.sleep, jitter=lambda low, high: high, **kwargs), clock


def get(gateway, url=URL, **kwargs):
    return gateway.get(url, host='test', endpoint='league', **kwargs)


def test_ttl_gzip_canonical_query_and_counters(tmp_path):
    gateway, clock = setup(tmp_path)
    calls = []
    def transport(req, **kwargs):
        calls.append(req)
        assert req.get_header('Accept-encoding') == 'gzip'
        return Response({'n': len(calls)}, compressed=True)
    assert get(gateway, opener=transport) == {'n': 1}
    assert get(gateway, URL.replace('view=mTeam&view=mRoster', 'view=mRoster&view=mTeam'), opener=transport) == {'n': 1}
    clock.now += 61
    assert get(gateway, opener=transport) == {'n': 2}
    assert gateway.stats()['endpoints']['league'] == {'calls': 3, 'network': 2, 'cache_hit': 1}


def test_credentials_and_filters_isolate_cache_and_auth_latch(tmp_path):
    gateway, clock = setup(tmp_path)
    calls = []
    def transport(req, **kwargs):
        calls.append(req)
        if req.get_header('Cookie') == 'dead':
            raise urllib.error.HTTPError(URL, 401, 'Unauthorized', {}, io.BytesIO())
        return Response({'ok': True})
    for _ in range(2):
        with pytest.raises(AuthRejected):
            get(gateway, headers={'Cookie': 'dead'}, scope='abc123', opener=transport)
    assert len(calls) == 1
    get(gateway, headers={'Cookie': 'new', 'X-Fantasy-Filter': '{"offset":0}'}, scope='new-hmac', opener=transport)
    get(gateway, headers={'Cookie': 'new', 'X-Fantasy-Filter': '{"offset":1}'}, scope='new-hmac', opener=transport)
    assert len(calls) == 3
    assert b'dead' not in gateway.path.read_bytes()  # only hashed request keys / caller scopes


@pytest.mark.parametrize('http_date', [False, True])
def test_retry_after_shared_circuit_and_backoff(tmp_path, http_date):
    gateway, clock = setup(tmp_path)
    calls = []
    def transport(req, **kwargs):
        calls.append(req)
        retry = format_datetime(datetime.fromtimestamp(clock.now+120, timezone.utc)) if http_date else '120'
        raise urllib.error.HTTPError(URL, 429, 'limited', {'Retry-After': retry}, io.BytesIO(b'Cookie: secret'))
    with pytest.raises(GatewayError) as error:
        get(gateway, opener=transport)
    assert 'secret' not in str(error.value)
    other = ReadGateway(tmp_path, limits={'test': (1, 1)}, daily_budget=10, clock=clock, sleep=clock.sleep)
    clock.now += 119
    with pytest.raises(CircuitOpen):
        get(other, opener=transport)
    assert len(calls) == 1
    clock.now += 2
    with pytest.raises(GatewayError):
        get(other, opener=transport)
    assert len(calls) == 2


def test_budget_and_day_rollover_cache_does_not_spend(tmp_path):
    gateway, clock = setup(tmp_path, budget=1)
    get(gateway, opener=lambda *a, **k: Response({}))
    get(gateway, opener=lambda *a, **k: pytest.fail('cache miss'))
    with pytest.raises(BudgetExceeded):
        get(gateway, URL+'/other', opener=lambda *a, **k: pytest.fail('budget bypass'))
    clock.now += 86400
    get(gateway, opener=lambda *a, **k: Response({}))
    assert gateway.stats()['requests'] == 1


def test_final_permanent_and_fresh_bypasses(tmp_path):
    gateway, clock = setup(tmp_path)
    calls = []
    def transport(*a, **k):
        calls.append(1)
        return Response({'version': len(calls)})
    get(gateway, opener=transport, ttl=None, scope='account')
    clock.now += 86400*30
    assert get(gateway, opener=transport, scope='account') == {'version': 1}
    assert get(gateway, opener=transport, fresh=True, scope='account') == {'version': 2}
    gateway.invalidate('account')
    assert get(gateway, opener=transport, scope='account') == {'version': 3}


def test_singleflight_and_fresh_never_joins_prewrite(tmp_path):
    gateway, clock = setup(tmp_path)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def transport(*a, **k):
        calls.append(1)
        version = len(calls)
        if version == 1:
            entered.set()
            assert release.wait(5)
        return Response({'version': version})
    with ThreadPoolExecutor(3) as pool:
        leader = pool.submit(get, gateway, opener=transport)
        assert entered.wait(5)
        follower = pool.submit(get, gateway, opener=transport)
        fresh = get(gateway, opener=transport, fresh=True)
        assert fresh == {'version': 2}
        release.set()
        assert leader.result() == follower.result() == {'version': 1}
    assert len(calls) == 2


def process_read(directory, count, ready, start, queue):
    gateway = ReadGateway(directory, limits={'test': (100, 1)}, daily_budget=10)
    ready.put(True)
    start.wait(5)
    def transport(*a, **k):
        with count.get_lock():
            count.value += 1
        return Response({'shared': True})
    queue.put(get(gateway, opener=transport))


def test_processes_share_cache_fill_and_budget(tmp_path):
    ctx = multiprocessing.get_context('spawn')
    count, ready, queue, start = ctx.Value('i', 0), ctx.Queue(), ctx.Queue(), ctx.Event()
    processes = [ctx.Process(target=process_read, args=(str(tmp_path), count, ready, start, queue)) for _ in range(2)]
    for process in processes:
        process.start()
    try:
        for _ in processes:
            ready.get(timeout=10)
        start.set()
        assert [queue.get(timeout=10) for _ in processes] == [{'shared': True}]*2
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        assert count.value == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()


def test_shared_host_limiter(tmp_path):
    gateway, clock = setup(tmp_path)
    other = ReadGateway(tmp_path, limits={'test': (1, 1)}, daily_budget=10, clock=clock, sleep=clock.sleep)
    get(gateway, opener=lambda *a, **k: Response({}))
    get(other, URL+'/2', opener=lambda *a, **k: Response({}))
    assert clock.waits == [1.0]


def test_write_epoch_rejects_late_fill_and_new_read_does_not_join_it(tmp_path):
    gateway, clock = setup(tmp_path)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def transport(*a, **k):
        calls.append(1)
        version = len(calls)
        if version == 1:
            entered.set()
            assert release.wait(5)
        return Response({'version': version})
    with ThreadPoolExecutor(2) as pool:
        old = pool.submit(get, gateway, opener=transport, scope='account')
        assert entered.wait(5)
        gateway.invalidate('account')
        # Fresh verification never waits for the older read's fill lock.
        assert get(gateway, opener=transport, scope='account', fresh=True) == {'version': 2}
        release.set()
        assert old.result() == {'version': 1}
    # The old result was not allowed to repopulate the cache.
    assert get(gateway, opener=transport, scope='account') == {'version': 3}


def test_json_and_bytes_flights_cannot_exchange_decoded_values(tmp_path):
    gateway, clock = setup(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def transport(*a, **k):
        entered.set()
        assert release.wait(5)
        return Response({'same': True})
    with ThreadPoolExecutor(2) as pool:
        structured = pool.submit(get, gateway, opener=transport)
        assert entered.wait(5)
        raw = pool.submit(get, gateway, opener=transport, result_type='bytes', decode=lambda body: body)
        release.set()
        assert structured.result() == {'same': True}
        assert json.loads(raw.result()) == {'same': True}


@pytest.mark.parametrize('error', [TimeoutError(), ConnectionResetError(), EOFError(), zlib.error()])
def test_read_failures_map_to_circuit_and_counter(tmp_path, error):
    gateway, clock = setup(tmp_path)
    def transport(*a, **k):
        raise error
    with pytest.raises(GatewayError, match='network'):
        get(gateway, opener=transport)
    with pytest.raises(CircuitOpen):
        get(gateway, opener=transport)
    assert gateway.stats()['endpoints']['league']['error'] == 1


def test_retry_after_is_bounded_and_fresh_has_reserved_budget(tmp_path):
    gateway, clock = setup(tmp_path, budget=1, critical_reserve=1)
    get(gateway, opener=lambda *a, **k: Response({}))
    get(gateway, opener=lambda *a, **k: Response({}), fresh=True, critical=True)
    with pytest.raises(BudgetExceeded):
        get(gateway, fresh=True, critical=True)
    clock.now += 86400
    def transport(*a, **k):
        raise urllib.error.HTTPError(URL, 503, 'unavailable', {'Retry-After': 'inf'}, io.BytesIO())
    with pytest.raises(GatewayError):
        get(gateway, fresh=True, critical=True, opener=transport)
    assert gateway.stats()['circuits'][0]['until'] == clock.now+3600


def test_refresh_rereads_expiring_entries_stores_them_and_never_spends_the_reserve(tmp_path):
    gateway, clock = setup(tmp_path, budget=3, critical_reserve=5)
    calls = []
    def transport(*a, **k):
        calls.append(1)
        return Response({'version': len(calls)})
    get(gateway, opener=transport, ttl=900)
    get(gateway, URL+'&final', opener=transport, ttl=None)
    assert get(gateway, opener=transport, ttl=900, refresh=True) == {'version': 3}
    # The reread replaced the cached body, so ordinary readers see it, not the older fill.
    assert get(gateway, opener=transport, ttl=900) == {'version': 3}
    # Settled permanent periods stay cached; a refresh cannot spend reads on them.
    assert get(gateway, URL+'&final', opener=transport, ttl=None, refresh=True) == {'version': 2}
    with pytest.raises(BudgetExceeded):
        get(gateway, opener=transport, ttl=900, refresh=True)
    assert len(calls) == 3
