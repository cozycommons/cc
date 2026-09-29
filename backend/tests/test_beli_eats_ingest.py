"""Tests for the ig_logger ingest pipeline (platform runner + Beli sink).

Covers timestamp normalization and the per-account fan-out with an
in-memory fake of the Supabase table API — no database required.
"""

import os

import pytest

os.environ.setdefault("BELI_CREDENTIALS_KEY", "")

from cryptography.fernet import Fernet

from ig_logger import models, runner
from ig_logger.sinks.beli import accounts
from ig_logger.sinks.beli import sink as beli_sink


@pytest.fixture()
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("BELI_CREDENTIALS_KEY", key)
    return key


class FakeTable:
    def __init__(self, store, updates):
        self._store = store
        self._updates = updates
        self._rows = None
        self._eq = []
        self._pending_update = None

    def select(self, *a):
        self._rows = list(self._store)
        return self

    def eq(self, k, v):
        self._eq.append((k, v))
        self._rows = [r for r in (self._rows or self._store) if r.get(k) == v]
        return self

    def in_(self, k, values):
        self._rows = [r for r in (self._rows or self._store) if r.get(k) in values]
        return self

    def update(self, values):
        self._pending_update = values
        return self

    def execute(self):
        rows = self._rows
        if self._pending_update is not None:
            for r in self._store:
                if all(r.get(k) == v for k, v in self._eq):
                    self._updates.append((r.get("id"), dict(self._pending_update)))
                    r.update(self._pending_update)

        class R:
            data = rows

        return R()


class FakeSupabase:
    def __init__(self, account_rows, source_rows):
        self._tables = {
            "beli_accounts": account_rows,
            "ig_sources": source_rows,
        }
        self.updates = []

    def table(self, name):
        assert name in self._tables, name
        return FakeTable(self._tables[name], self.updates)

    def watermark(self, account_id):
        for r in self._tables["ig_sources"]:
            if r["account_id"] == account_id:
                return r.get("last_seen_ts")
        return None


def _account_row(id, label, opted_in):
    return {
        "id": id,
        "label": label,
        "beli_id_enc": accounts.encrypt_secret("user@example.com"),
        "password_enc": accounts.encrypt_secret("s3cret"),
        "token_hash": "x",
        "watcher_opt_in": opted_in,
    }


def _source_row(account_id, enabled=True, last_seen=""):
    return {
        "account_id": account_id,
        "handle": "beli_eats",
        "enabled": enabled,
        "last_seen_ts": last_seen,
    }


def _sb(account_rows, source_rows=None):
    if source_rows is None:
        source_rows = [
            _source_row(r["id"], enabled=r["watcher_opt_in"]) for r in account_rows
        ]
    return FakeSupabase(account_rows, source_rows)


def _fake_process(monkeypatch, seen):
    def fake_process(self, posts, account):
        seen.append(account["label"])
        return {
            "account": account["label"],
            "checked": len(posts),
            "bookmarked": [],
            "already": [],
            "skipped": [],
            "newest_ts": "2026-09-26T17:14:52+00:00",
        }

    monkeypatch.setattr(beli_sink.BeliSink, "process", fake_process)


def test_normalize_ts():
    assert models.normalize_ts("2026-09-26T17:14:52+00:00") == "2026-09-26T17:14:52+00:00"
    assert models.normalize_ts("2026-09-26 17:14:52") == "2026-09-26T17:14:52"
    assert models.normalize_ts("") == ""
    assert models.normalize_ts(None) == ""


def test_run_ingest_only_opted_in(fernet_key, monkeypatch):
    sb = _sb(
        [_account_row("a1", "alice", True), _account_row("b2", "bob", False)],
        [_source_row("a1", enabled=True), _source_row("b2", enabled=True)],
    )
    seen = []
    _fake_process(monkeypatch, seen)
    posts = [{"shortcode": "x", "created_at": "2026-09-26 17:14:52", "post_caption": ""}]

    digests = runner.run_ingest(sb, posts, "beli_eats")

    # bob's sink is disabled (watcher_opt_in=False) but he still gets a
    # platform digest with no sink results
    assert seen == ["alice"]
    assert [d["account"] for d in digests] == ["alice", "bob"]
    alice = digests[0]
    assert alice["sinks"]["beli"]["checked"] == 1
    assert digests[1]["sinks"] == {}
    # space-separated timestamp normalized before the sink ran
    assert alice["sinks"]["beli"]["checked"] == 1
    # watermark advanced for the processed account only
    assert sb.watermark("a1") == "2026-09-26T17:14:52"
    assert sb.watermark("b2") == ""


def test_run_ingest_sink_decrypt_failure_reported(fernet_key, monkeypatch):
    enc = lambda s: "garbage-not-encrypted"  # noqa: E731
    rows = [
        {
            "id": "a1",
            "label": "alice",
            "beli_id_enc": enc("x"),
            "password_enc": enc("y"),
            "token_hash": "x",
            "watcher_opt_in": True,
        }
    ]
    sb = _sb(rows)
    posts = [{"shortcode": "x", "created_at": "2026-09-26T17:14:52+00:00"}]

    digests = runner.run_ingest(sb, posts, "beli_eats")

    assert len(digests) == 1
    beli = digests[0]["sinks"]["beli"]
    assert beli["checked"] == 1
    assert any("account error" in s for s in beli["skipped"])


def test_run_ingest_only_account_id(fernet_key, monkeypatch):
    sb = _sb(
        [_account_row("a1", "alice", True), _account_row("b2", "bob", True)],
    )
    seen = []
    _fake_process(monkeypatch, seen)

    digests = runner.run_ingest(sb, [], "beli_eats", only_account_id="b2")

    assert seen == []
    assert [d["account"] for d in digests] == ["bob"]


def test_run_ingest_unsubscribed_account_gets_nothing(fernet_key, monkeypatch):
    sb = _sb(
        [_account_row("a1", "alice", True)],
        [_source_row("a1", enabled=False)],
    )
    seen = []
    _fake_process(monkeypatch, seen)

    digests = runner.run_ingest(
        sb, [{"created_at": "2026-09-26T17:14:52+00:00"}], "beli_eats"
    )

    assert digests == []
    assert seen == []


# --- POST /beli/eats-ingest route (deprecated backfill path) -----------------

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ig_logger.sinks.beli import routes as beli_routes  # noqa: E402


def _platform_digest(account, account_id, bookmarked=None):
    return {
        "account": account,
        "account_id": account_id,
        "source": "beli_eats",
        "checked": 1,
        "sinks": {
            "beli": {
                "account": account,
                "checked": 1,
                "bookmarked": bookmarked or [],
                "already": [],
                "skipped": [],
                "newest_ts": "2026-09-26T17:14:52+00:00",
            }
        },
        "newest_ts": "2026-09-26T17:14:52+00:00",
        "scanned_at": "2026-09-27T18:00:00+00:00",
    }


def _ingest_client(monkeypatch, key="svc-key-123"):
    monkeypatch.setenv("BELI_EATS_INGEST_KEY", key)
    app = FastAPI()
    app.state.supabase = _sb([])
    app.include_router(beli_routes.router, prefix="/beli")
    return TestClient(app)


def test_eats_ingest_rejects_bad_key(monkeypatch):
    client = _ingest_client(monkeypatch)
    r = client.post(
        "/beli/eats-ingest",
        json={"posts": []},
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert r.status_code == 401
    r = client.post("/beli/eats-ingest", json={"posts": []})
    assert r.status_code == 401
    assert client.post("/beli/eats-ingest", json={"posts": []}).status_code == 401


def test_eats_ingest_fails_closed_without_server_key(monkeypatch):
    monkeypatch.delenv("BELI_EATS_INGEST_KEY", raising=False)
    app = FastAPI()
    app.state.supabase = _sb([])
    app.include_router(beli_routes.router, prefix="/beli")
    client = TestClient(app)
    r = client.post(
        "/beli/eats-ingest",
        json={"posts": []},
        headers={"Authorization": "Bearer anything"},
    )
    assert r.status_code == 401


def test_eats_ingest_ok(monkeypatch):
    client = _ingest_client(monkeypatch)
    captured = {}
    monkeypatch.setattr(
        runner,
        "run_ingest",
        lambda sb, posts, source, only_account_id=None: captured.update(
            posts=posts, source=source
        )
        or [],
    )
    body = {
        "posts": [
            {
                "shortcode": "AbC123",
                "created_at": "2026-09-26T17:14:52+00:00",
                "post_caption": "hello",
            }
        ]
    }
    r = client.post(
        "/beli/eats-ingest",
        json=body,
        headers={"Authorization": "Bearer svc-key-123"},
    )
    assert r.status_code == 200
    assert r.json() == {"accounts": 0, "digests": []}
    assert captured["posts"] == body["posts"]
    assert captured["source"] == "beli_eats"
    assert r.headers.get("deprecation") == "true"  # deprecated: prefer scan-job queue


def test_eats_ingest_flattens_platform_digest(monkeypatch):
    client = _ingest_client(monkeypatch)
    monkeypatch.setattr(
        runner,
        "run_ingest",
        lambda sb, posts, source, only_account_id=None: [
            _platform_digest("alice", "a1", bookmarked=["Some Place"])
        ],
    )
    r = client.post(
        "/beli/eats-ingest",
        json={"posts": []},
        headers={"Authorization": "Bearer svc-key-123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accounts"] == 1
    digest = body["digests"][0]
    # legacy shape: sink digest flattened, no platform wrapper keys
    assert digest["account_id"] == "a1"
    assert digest["bookmarked"] == ["Some Place"]
    assert digest["scanned_at"] == "2026-09-27T18:00:00+00:00"
    assert "sinks" not in digest
    assert "source" not in digest


def _user_token_client(monkeypatch):
    """App with two opted-in accounts; alice holds a real ccb_ token."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("BELI_CREDENTIALS_KEY", key)
    monkeypatch.setenv("BELI_EATS_INGEST_KEY", "svc-key-123")
    token = "ccb_testtoken123"
    rows = [
        {
            **_account_row("a1", "alice", True),
            "token_hash": accounts.hash_token(token),
        },
        {
            **_account_row("b2", "bob", True),
            "token_hash": accounts.hash_token("ccb_other"),
        },
    ]
    sb = _sb(rows)
    app = FastAPI()
    app.state.supabase = sb
    app.include_router(beli_routes.router, prefix="/beli")
    return TestClient(app), token


def test_eats_ingest_user_token_scoped_to_own_account(monkeypatch):
    client, token = _user_token_client(monkeypatch)
    seen = {}

    def fake_run(sb, posts, source, only_account_id=None):
        seen["only_account_id"] = only_account_id
        return [_platform_digest("alice", "a1")]

    monkeypatch.setattr(runner, "run_ingest", fake_run)
    r = client.post(
        "/beli/eats-ingest",
        json={"posts": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert seen["only_account_id"] == "a1"
    assert r.json()["accounts"] == 1


def test_eats_ingest_rejects_unknown_user_token(monkeypatch):
    client, _token = _user_token_client(monkeypatch)
    r = client.post(
        "/beli/eats-ingest",
        json={"posts": []},
        headers={"Authorization": "Bearer ccb_nonexistent"},
    )
    assert r.status_code == 401
