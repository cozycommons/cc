"""Unit tests for ESPN league snapshot storage (capture-on-read).

Uses an in-memory fake of the Supabase table API — no database required.
"""

from datetime import datetime, timedelta, timezone

import pytest

from espn import snapshots


class FakeTable:
    def __init__(self, store):
        self._store = store
        self._rows = None

    def insert(self, row):
        row = dict(row, id=f"id-{len(self._store) + 1}")
        row.setdefault(
            "captured_at", datetime.now(timezone.utc).isoformat()
        )
        self._store.append(row)
        self._rows = [row]
        return self

    def select(self, *a):
        self._rows = list(self._store)
        return self

    def eq(self, k, v):
        self._rows = [r for r in (self._rows or self._store) if r.get(k) == v]
        return self

    def order(self, column, desc=False):
        self._rows = sorted(
            self._rows or list(self._store),
            key=lambda r: r.get(column),
            reverse=desc,
        )
        return self

    def limit(self, n):
        self._rows = (self._rows or list(self._store))[:n]
        return self

    def execute(self):
        class R:
            data = self._rows

        return R()


class FakeSupabase:
    def __init__(self):
        self._store = []

    def table(self, name):
        assert name == "espn_snapshots"
        return FakeTable(self._store)


ACCOUNT = {"id": "acct-1", "league_id": 111, "season": 2027}


def _row(payload, captured_at, account_id="acct-1"):
    return {
        "account_id": account_id,
        "league_id": 111,
        "season": 2027,
        "payload": payload,
        "captured_at": captured_at,
    }


def _iso(dt):
    return dt.isoformat()


def test_record_and_latest_roundtrip_newest_first_with_limit():
    db = FakeSupabase()
    now = datetime.now(timezone.utc)
    db._store.extend(
        [
            _row({"n": 1}, _iso(now - timedelta(hours=2))),
            _row({"n": 3}, _iso(now)),
            _row({"n": 2}, _iso(now - timedelta(hours=1))),
            # another account's (newer) snapshot must never leak in
            _row({"n": 99}, _iso(now + timedelta(hours=1)), account_id="acct-2"),
        ]
    )
    rows = snapshots.latest_snapshots(db, "acct-1", limit=2)
    assert [r["payload"] for r in rows] == [{"n": 3}, {"n": 2}]
    assert rows[0]["captured_at"] == _iso(now)

    snapshots.record_snapshot(db, "acct-1", 111, 2027, {"n": 4})
    rows = snapshots.latest_snapshots(db, "acct-1")
    assert rows[0]["payload"] == {"n": 4}
    stored = db._store[-1]
    assert stored["account_id"] == "acct-1"
    assert stored["league_id"] == 111
    assert stored["season"] == 2027
    assert stored["payload"] == {"n": 4}


def test_ensure_snapshot_captures_when_empty(monkeypatch):
    db = FakeSupabase()
    canned = {"teams": ["a", "b"]}
    monkeypatch.setattr(
        snapshots.logic, "build_snapshot", lambda client: canned
    )
    result = snapshots.ensure_snapshot(db, ACCOUNT, client=object())
    assert result["current"] == canned
    assert result["previous"] is None
    assert result["fresh_capture"] is True
    assert result["captured_at"]
    # the capture was persisted for the account's league/season
    assert len(db._store) == 1
    assert db._store[0]["payload"] == canned
    assert db._store[0]["league_id"] == 111
    assert db._store[0]["season"] == 2027


def test_ensure_snapshot_reuses_fresh_snapshot(monkeypatch):
    db = FakeSupabase()
    now = datetime.now(timezone.utc)
    newest = _iso(now - timedelta(minutes=5))
    db._store.extend(
        [
            _row({"n": "old"}, _iso(now - timedelta(hours=3))),
            _row({"n": "new"}, newest),
        ]
    )

    def boom(client):
        raise AssertionError("build_snapshot must not be called for a fresh snapshot")

    monkeypatch.setattr(snapshots.logic, "build_snapshot", boom)
    result = snapshots.ensure_snapshot(db, ACCOUNT, client=object())
    assert result["current"] == {"n": "new"}
    assert result["previous"] == {"n": "old"}
    assert result["captured_at"] == newest
    assert result["fresh_capture"] is False
    assert len(db._store) == 2


def test_ensure_snapshot_recaptures_when_stale(monkeypatch):
    db = FakeSupabase()
    now = datetime.now(timezone.utc)
    # newest is older than the default max age (CAPTURE_MIN_INTERVAL_S = 3600)
    db._store.append(_row({"n": "stale"}, _iso(now - timedelta(hours=2))))
    canned = {"n": "fresh"}
    monkeypatch.setattr(
        snapshots.logic, "build_snapshot", lambda client: canned
    )
    result = snapshots.ensure_snapshot(db, ACCOUNT, client=object())
    assert result["current"] == canned
    assert result["previous"] == {"n": "stale"}
    assert result["fresh_capture"] is True
    assert len(db._store) == 2
    assert db._store[-1]["payload"] == canned


def test_ensure_snapshot_recaptures_with_custom_max_age(monkeypatch):
    db = FakeSupabase()
    now = datetime.now(timezone.utc)
    db._store.append(_row({"n": "recent"}, _iso(now - timedelta(minutes=10))))
    canned = {"n": "newer"}
    monkeypatch.setattr(
        snapshots.logic, "build_snapshot", lambda client: canned
    )
    result = snapshots.ensure_snapshot(db, ACCOUNT, client=object(), max_age_s=60)
    assert result["fresh_capture"] is True
    assert result["previous"] == {"n": "recent"}
    assert result["current"] == canned
