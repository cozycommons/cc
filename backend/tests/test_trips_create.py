"""Deterministic concurrent retries at the create-trip HTTP command boundary."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier, Lock
from types import SimpleNamespace
from uuid import uuid4

from postgrest.exceptions import APIError

from trips import routes


def test_simultaneous_creation_reopens_one_row_without_overwriting(monkeypatch):
    barrier, lock = Barrier(2), Lock()
    saved = {}

    class Query:
        def __init__(self, payload=None):
            self.payload = payload

        def select(self, _columns):
            return self

        def eq(self, _column, value):
            self.id = value
            return self

        def insert(self, payload):
            return Query(payload)

        def execute(self):
            if self.payload is None:
                with lock:
                    rows = [deepcopy(saved[self.id])] if self.id in saved else []
                if not rows:
                    barrier.wait(timeout=5)  # Both requests observe the initial absence.
                return SimpleNamespace(data=rows)
            with lock:
                if self.payload['id'] in saved:
                    raise APIError({'message': 'duplicate key', 'code': '23505', 'details': None, 'hint': None})
                saved[self.payload['id']] = deepcopy(self.payload)
                return SimpleNamespace(data=[deepcopy(self.payload)])

    client = SimpleNamespace(table=lambda _table: Query())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(trips_supabase=client)))
    monkeypatch.setattr(routes, 'render_group', lambda _client, row: row)
    payload = routes.CreateTrip(id=uuid4(), name='Retry check', display_name='Owner')
    user = SimpleNamespace(id='owner')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: routes.create_trip(payload, request, user), range(2)))
    assert len(saved) == 1
    assert results[0] == results[1] == next(iter(saved.values()))
