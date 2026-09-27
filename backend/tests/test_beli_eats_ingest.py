"""Tests for the @beli_eats ingest pipeline (POST /beli/eats-ingest backend).

Covers timestamp normalization and the per-account ingest loop with an
in-memory fake of the Supabase table API — no database required.
"""

import os

import pytest

os.environ.setdefault("BELI_CREDENTIALS_KEY", "")

from cryptography.fernet import Fernet

from beli import accounts
from beli import eats_watcher


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
    def __init__(self, rows):
        self._store = rows
        self.updates = []

    def table(self, name):
        assert name == "beli_accounts"
        return FakeTable(self._store, self.updates)


def _row(id, label, opted_in, last_scan, key_ok=True):
    enc = accounts.encrypt_secret if key_ok else (lambda s: "garbage-not-encrypted")
    return {
        "id": id,
        "label": label,
        "beli_id_enc": enc("user@example.com"),
        "password_enc": enc("s3cret"),
        "token_hash": "x",
        "watcher_opt_in": opted_in,
        "last_eats_scan": last_scan,
    }


def test_norm_ts():
    assert eats_watcher._norm_ts("2026-09-26T17:14:52+00:00") == "2026-09-26T17:14:52+00:00"
    assert eats_watcher._norm_ts("2026-09-26 17:14:52") == "2026-09-26T17:14:52"
    assert eats_watcher._norm_ts("") == ""
    assert eats_watcher._norm_ts(None) == ""


def test_run_eats_ingest_only_opted_in(fernet_key, monkeypatch):
    rows = [
        _row("a1", "alice", True, ""),
        _row("b2", "bob", False, ""),
    ]
    sb = FakeSupabase(rows)
    seen = []

    def fake_scan(account, posts):
        seen.append(account["label"])
        return {
            "account": account["label"],
            "checked": len(posts),
            "bookmarked": [],
            "already": [],
            "skipped": [],
            "newest_ts": "2026-09-26T17:14:52+00:00",
        }

    monkeypatch.setattr(eats_watcher, "scan_account_for_posts", fake_scan)
    posts = [{"shortcode": "x", "created_at": "2026-09-26 17:14:52", "post_caption": ""}]

    digests = eats_watcher.run_eats_ingest(posts, sb)

    assert seen == ["alice"]
    assert len(digests) == 1
    assert digests[0]["account"] == "alice"
    # space-separated timestamp normalized before the scan ran
    assert seen and digests[0]["checked"] == 1
    # watermark advanced for the processed account only
    assert sb.updates == [("a1", {"last_eats_scan": "2026-09-26T17:14:52+00:00"})]
    assert rows[0]["last_eats_scan"] == "2026-09-26T17:14:52+00:00"
    assert rows[1]["last_eats_scan"] == ""


def test_run_eats_ingest_decrypt_failure_reported(fernet_key, monkeypatch):
    rows = [_row("a1", "alice", True, "", key_ok=False)]
    sb = FakeSupabase(rows)

    def fake_scan(account, posts):  # pragma: no cover - must not be called
        raise AssertionError("scan must not run for undecryptable accounts")

    monkeypatch.setattr(eats_watcher, "scan_account_for_posts", fake_scan)

    digests = eats_watcher.run_eats_ingest([], sb)

    assert len(digests) == 1
    assert digests[0]["account"] == "alice"
    assert digests[0]["checked"] == 0
    assert any("account error" in s for s in digests[0]["skipped"])
    assert sb.updates == []


def test_run_eats_ingest_only_account_id(fernet_key, monkeypatch):
    rows = [
        _row("a1", "alice", True, ""),
        _row("b2", "bob", True, ""),
    ]
    sb = FakeSupabase(rows)
    seen = []

    def fake_scan(account, posts):
        seen.append(account["label"])
        return {
            "account": account["label"],
            "checked": 0,
            "bookmarked": [],
            "already": [],
            "skipped": [],
            "newest_ts": "",
        }

    monkeypatch.setattr(eats_watcher, "scan_account_for_posts", fake_scan)

    digests = eats_watcher.run_eats_ingest([], sb, only_account_id="b2")

    assert seen == ["bob"]
    assert [d["account"] for d in digests] == ["bob"]


# --- POST /beli/eats-ingest route -------------------------------------------

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from beli import routes as beli_routes  # noqa: E402


def _ingest_client(monkeypatch, key="svc-key-123"):
    monkeypatch.setenv("BELI_EATS_INGEST_KEY", key)
    app = FastAPI()
    app.state.supabase = FakeSupabase([])
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


def test_eats_ingest_fails_closed_without_server_key(monkeypatch):
    monkeypatch.delenv("BELI_EATS_INGEST_KEY", raising=False)
    app = FastAPI()
    app.state.supabase = FakeSupabase([])
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
        eats_watcher,
        "run_eats_ingest",
        lambda posts, sb, only_account_id=None: captured.update(posts=posts) or [],
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
    assert r.headers.get("deprecation") == "true"  # deprecated: prefer scan-job queue


def _user_token_client(monkeypatch):
    """App with two opted-in accounts; alice holds a real ccb_ token."""
    from cryptography.fernet import Fernet as _F

    key = _F.generate_key().decode()
    monkeypatch.setenv("BELI_CREDENTIALS_KEY", key)
    monkeypatch.setenv("BELI_EATS_INGEST_KEY", "svc-key-123")
    token = "ccb_testtoken123"
    rows = [
        {**_row("a1", "alice", True, ""), "token_hash": accounts.hash_token(token)},
        {**_row("b2", "bob", True, ""), "token_hash": accounts.hash_token("ccb_other")},
    ]
    sb = FakeSupabase(rows)
    app = FastAPI()
    app.state.supabase = sb
    app.include_router(beli_routes.router, prefix="/beli")
    return TestClient(app), token


def test_eats_ingest_user_token_scoped_to_own_account(monkeypatch):
    client, token = _user_token_client(monkeypatch)
    seen = {}

    def fake_run(posts, sb, only_account_id=None):
        seen["only_account_id"] = only_account_id
        return [{"account": "alice", "checked": 0, "bookmarked": [],
                 "already": [], "skipped": [], "newest_ts": ""}]

    monkeypatch.setattr(eats_watcher, "run_eats_ingest", fake_run)
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
