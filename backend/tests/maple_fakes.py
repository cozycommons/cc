"""In-memory fake of the Supabase table API for Maple telemetry tests.

Supports the subset maple uses — insert, select, eq, order, limit,
upsert (on_conflict), update and delete — with PostgREST semantics:
filters apply at execute() regardless of chaining order. No database
required.
"""

import itertools


class _Result:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, store, ids):
        self._store = store
        self._ids = ids
        self._mode = "select"
        self._pending = None
        self._conflict = ""
        self._filters = []
        self._orders = []
        self._limit = None

    def insert(self, row):
        self._mode, self._pending = "insert", dict(row)
        return self

    def upsert(self, row, on_conflict=None):
        self._mode, self._pending = "upsert", dict(row)
        self._conflict = on_conflict or ""
        return self

    def update(self, values):
        self._mode, self._pending = "update", dict(values)
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def select(self, *a):
        self._mode = "select"
        return self

    def eq(self, key, value):
        self._filters.append((key, value))
        return self

    def order(self, key, desc=False):
        self._orders.append((key, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matched(self):
        rows = list(self._store)
        for key, value in self._filters:
            rows = [r for r in rows if r.get(key) == value]
        return rows

    def execute(self):
        if self._mode == "insert":
            row = dict(self._pending)
            row.setdefault("id", f"id-{next(self._ids)}")
            self._store.append(row)
            return _Result([row])
        if self._mode == "upsert":
            cols = [c.strip() for c in self._conflict.split(",") if c.strip()]
            for row in self._store:
                if cols and all(row.get(c) == self._pending.get(c) for c in cols):
                    row.update(self._pending)
                    return _Result([row])
            row = dict(self._pending)
            row.setdefault("id", f"id-{next(self._ids)}")
            self._store.append(row)
            return _Result([row])
        if self._mode == "update":
            rows = self._matched()
            for row in rows:
                row.update(self._pending)
            return _Result(rows)
        if self._mode == "delete":
            victims = self._matched()
            self._store[:] = [r for r in self._store if r not in victims]
            return _Result(victims)
        rows = self._matched()
        for key, desc in reversed(self._orders):
            rows.sort(key=lambda r: (r.get(key) is None, r.get(key)), reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        return _Result(rows)


class FakeSupabase:
    TABLES = ("maple_accounts", "maple_exp_runs")

    def __init__(self):
        self.stores = {name: [] for name in self.TABLES}
        self._ids = itertools.count(1)

    def table(self, name):
        assert name in self.TABLES, name
        return FakeTable(self.stores[name], self._ids)
