"""Tests for the poll-model scan-job queue (POST /beli/eats/scan, ...).

CC never touches Instagram and accepts no inbound connections from the
fetch box: the box polls GET /beli/eats/scan/pending for work, fetches
Instagram locally, and POSTs the posts back to
POST /beli/eats/scan/{job_id}/complete. CC runs the ingest pipeline under
the job's stored scope and keeps the digest on the job row.

The /beli/eats/* endpoints are thin wrappers over the ig_logger platform
(scan jobs for source 'beli_eats'); these tests pin the legacy response
shapes.

In-memory fakes of the Supabase table API — no database required.
"""

import os

import pytest

os.environ.setdefault("BELI_CREDENTIALS_KEY", "")

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ig_logger.sinks.beli import accounts
from ig_logger.sinks.beli import sink as beli_sink
from ig_logger.sinks.beli import routes as beli_routes


@pytest.fixture()
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("BELI_CREDENTIALS_KEY", key)
    return key


class FakeTable:
    def __init__(self, store, counter):
        self._store = store
        self._counter = counter
        self._rows = None
        self._eq = []
        self._order = None
        self._limit = None
        self._pending_update = None
        self._pending_insert = None

    def select(self, *a):
        self._rows = list(self._store)
        return self

    def eq(self, k, v):
        self._eq.append((k, v))
        base = self._rows if self._rows is not None else self._store
        self._rows = [r for r in base if r.get(k) == v]
        return self

    def in_(self, k, values):
        base = self._rows if self._rows is not None else self._store
        self._rows = [r for r in base if r.get(k) in values]
        return self

    def order(self, k, desc=False):
        self._order = (k, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def update(self, values):
        self._pending_update = values
        return self

    def insert(self, values):
        self._pending_insert = values
        return self

    def execute(self):
        if self._pending_insert is not None:
            self._counter[0] += 1
            row = dict(self._pending_insert)
            row.setdefault("id", f"job-{self._counter[0]}")
            row.setdefault(
                "created_at", f"2026-09-27T18:00:{self._counter[0]:02d}Z"
            )
            self._store.append(row)
            rows = [row]
        else:
            rows = self._rows if self._rows is not None else list(self._store)
            if self._order:
                k, desc = self._order
                rows = sorted(rows, key=lambda r: r.get(k) or "", reverse=desc)
            if self._limit is not None:
                rows = rows[: self._limit]
            if self._pending_update is not None:
                for r in self._store:
                    if all(r.get(k) == v for k, v in self._eq):
                        r.update(self._pending_update)

        class R:
            data = rows

        return R()


class FakeSupabase:
    def __init__(self, accounts_rows, source_rows, jobs_rows=None):
        self._tables = {
            "beli_accounts": accounts_rows,
            "ig_sources": source_rows,
            "ig_scan_jobs": jobs_rows if jobs_rows is not None else [],
        }
        self._counter = [0]

    def table(self, name):
        assert name in self._tables, name
        return FakeTable(self._tables[name], self._counter)

    @property
    def jobs(self):
        return self._tables["ig_scan_jobs"]

    def watermark(self, account_id):
        for r in self._tables["ig_sources"]:
            if r["account_id"] == account_id:
                return r.get("last_seen_ts")
        return None


def _account_row(id, label, token, opted_in=True):
    return {
        "id": id,
        "label": label,
        "beli_id_enc": accounts.encrypt_secret("user@example.com"),
        "password_enc": accounts.encrypt_secret("s3cret"),
        "token_hash": accounts.hash_token(token),
        "watcher_opt_in": opted_in,
    }


def _source_row(account_id, enabled=True, last_seen=""):
    return {
        "account_id": account_id,
        "handle": "beli_eats",
        "enabled": enabled,
        "last_seen_ts": last_seen,
    }


def _app(sb, monkeypatch, service_key="svc-key-123"):
    monkeypatch.setenv("BELI_EATS_INGEST_KEY", service_key)
    app = FastAPI()
    app.state.supabase = sb
    app.include_router(beli_routes.router, prefix="/beli")
    return TestClient(app)


@pytest.fixture()
def two_accounts(fernet_key):
    alice_token = "ccb_alice_token_1"
    bob_token = "ccb_bob_token_2"
    account_rows = [
        _account_row("a1", "alice", alice_token, True),
        _account_row("b2", "bob", bob_token, True),
    ]
    source_rows = [_source_row("a1"), _source_row("b2")]
    return FakeSupabase(account_rows, source_rows), alice_token, bob_token


def _posts():
    return [
        {
            "shortcode": "AbC123",
            "created_at": "2026-09-26T17:14:52+00:00",
            "post_caption": "hello",
        }
    ]


def _fake_process(monkeypatch):
    """Stub the Beli sink; exercises the real platform fan-out."""

    def fake_process(self, posts, account):
        return {
            "account": account["label"],
            "checked": len(posts),
            "bookmarked": ["Some Place"],
            "already": [],
            "skipped": [],
            "newest_ts": "2026-09-26T17:14:52+00:00",
        }

    monkeypatch.setattr(beli_sink.BeliSink, "process", fake_process)


# --- POST /beli/eats/scan --------------------------------------------------------

def test_scan_service_key_creates_all_job(two_accounts, monkeypatch):
    sb, _, _ = two_accounts
    client = _app(sb, monkeypatch)
    r = client.post("/beli/eats/scan", headers={"Authorization": "Bearer svc-key-123"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["job_id"]
    assert sb.jobs[0]["scope"] == "all"
    assert sb.jobs[0]["status"] == "pending"
    assert sb.jobs[0]["source_handle"] == "beli_eats"


def test_scan_personal_token_scoped_to_caller(two_accounts, monkeypatch):
    sb, alice_token, _ = two_accounts
    client = _app(sb, monkeypatch)
    r = client.post(
        "/beli/eats/scan", headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert r.status_code == 202
    assert sb.jobs[0]["scope"] == "a1"


def test_scan_rejects_bad_auth(two_accounts, monkeypatch):
    sb, _, _ = two_accounts
    client = _app(sb, monkeypatch)
    r = client.post("/beli/eats/scan", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    r = client.post("/beli/eats/scan")
    assert r.status_code == 401
    assert sb.jobs == []


# --- GET /beli/eats/scan/pending --------------------------------------------------

def test_pending_204_when_empty(two_accounts, monkeypatch):
    sb, alice_token, _ = two_accounts
    client = _app(sb, monkeypatch)
    r = client.get(
        "/beli/eats/scan/pending", headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert r.status_code == 204


def test_pending_returns_oldest_job(two_accounts, monkeypatch):
    sb, alice_token, bob_token = two_accounts
    client = _app(sb, monkeypatch)
    client.post("/beli/eats/scan", headers={"Authorization": "Bearer svc-key-123"})
    client.post("/beli/eats/scan", headers={"Authorization": f"Bearer {bob_token}"})
    r = client.get(
        "/beli/eats/scan/pending", headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert r.status_code == 200
    assert r.json()["scope"] == "all"  # the first enqueued job
    assert r.json()["source_handle"] == "beli_eats"


def test_pending_requires_auth(two_accounts, monkeypatch):
    sb, _, _ = two_accounts
    client = _app(sb, monkeypatch)
    assert client.get("/beli/eats/scan/pending").status_code == 401


# --- POST /beli/eats/scan/{job_id}/complete ---------------------------------------

def test_complete_runs_pipeline_and_stores_digest(two_accounts, monkeypatch):
    sb, alice_token, _ = two_accounts
    _fake_process(monkeypatch)
    client = _app(sb, monkeypatch)
    job_id = client.post(
        "/beli/eats/scan", headers={"Authorization": f"Bearer {alice_token}"}
    ).json()["job_id"]

    r = client.post(
        f"/beli/eats/scan/{job_id}/complete",
        json={"posts": _posts()},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["digests"][0]["account"] == "alice"
    assert body["digests"][0]["account_id"] == "a1"
    assert "scanned_at" in body["digests"][0]
    # legacy shape: no platform wrapper keys leak through
    assert "sinks" not in body["digests"][0]

    job = sb.jobs[0]
    assert job["status"] == "done"
    assert job["digest"][0]["sinks"]["beli"]["bookmarked"] == ["Some Place"]
    # watermark advanced on the platform subscription row
    assert sb.watermark("a1") == "2026-09-26T17:14:52+00:00"


def test_complete_all_scope_fans_out(two_accounts, monkeypatch):
    sb, alice_token, _ = two_accounts
    _fake_process(monkeypatch)
    client = _app(sb, monkeypatch)
    job_id = client.post(
        "/beli/eats/scan", headers={"Authorization": "Bearer svc-key-123"}
    ).json()["job_id"]

    # the poller only holds a personal token; the job's stored scope ('all')
    # still drives the fan-out via CC's internal authority
    r = client.post(
        f"/beli/eats/scan/{job_id}/complete",
        json={"posts": _posts()},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 200
    digests = r.json()["digests"]
    assert sorted(d["account_id"] for d in digests) == ["a1", "b2"]


def test_complete_unknown_job_404(two_accounts, monkeypatch):
    sb, alice_token, _ = two_accounts
    client = _app(sb, monkeypatch)
    r = client.post(
        "/beli/eats/scan/does-not-exist/complete",
        json={"posts": []},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 404


def test_complete_non_pending_409(two_accounts, monkeypatch):
    sb, alice_token, _ = two_accounts
    _fake_process(monkeypatch)
    client = _app(sb, monkeypatch)
    job_id = client.post(
        "/beli/eats/scan", headers={"Authorization": f"Bearer {alice_token}"}
    ).json()["job_id"]
    url = f"/beli/eats/scan/{job_id}/complete"
    auth = {"Authorization": f"Bearer {alice_token}"}
    assert client.post(url, json={"posts": []}, headers=auth).status_code == 200
    assert client.post(url, json={"posts": []}, headers=auth).status_code == 409


# --- GET /beli/eats/scan/{job_id} --------------------------------------------------

def test_scan_status_scoped_and_sliced(two_accounts, monkeypatch):
    sb, alice_token, bob_token = two_accounts
    _fake_process(monkeypatch)
    client = _app(sb, monkeypatch)

    # bob-scoped job: alice gets 403, bob gets his slice
    bob_job = client.post(
        "/beli/eats/scan", headers={"Authorization": f"Bearer {bob_token}"}
    ).json()["job_id"]
    assert (
        client.get(
            f"/beli/eats/scan/{bob_job}",
            headers={"Authorization": f"Bearer {alice_token}"},
        ).status_code
        == 403
    )
    client.post(
        f"/beli/eats/scan/{bob_job}/complete",
        json={"posts": _posts()},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    r = client.get(
        f"/beli/eats/scan/{bob_job}",
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    assert r.status_code == 200
    assert r.json()["digest"]["account_id"] == "b2"

    # 'all'-scoped job: alice sees only her own slice, not bob's
    all_job = client.post(
        "/beli/eats/scan", headers={"Authorization": "Bearer svc-key-123"}
    ).json()["job_id"]
    client.post(
        f"/beli/eats/scan/{all_job}/complete",
        json={"posts": _posts()},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    r = client.get(
        f"/beli/eats/scan/{all_job}",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert r.status_code == 200
    assert r.json()["digest"]["account_id"] == "a1"


def test_scan_status_unknown_404(two_accounts, monkeypatch):
    sb, alice_token, _ = two_accounts
    client = _app(sb, monkeypatch)
    r = client.get(
        "/beli/eats/scan/nope", headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert r.status_code == 404


# --- GET /beli/eats/digest ----------------------------------------------------------

def test_digest_404_before_any_scan(two_accounts, monkeypatch):
    sb, alice_token, _ = two_accounts
    client = _app(sb, monkeypatch)
    r = client.get(
        "/beli/eats/digest", headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert r.status_code == 404


def test_digest_returns_caller_slice_after_scan(two_accounts, monkeypatch):
    sb, alice_token, bob_token = two_accounts
    _fake_process(monkeypatch)
    client = _app(sb, monkeypatch)
    job_id = client.post(
        "/beli/eats/scan", headers={"Authorization": "Bearer svc-key-123"}
    ).json()["job_id"]
    client.post(
        f"/beli/eats/scan/{job_id}/complete",
        json={"posts": _posts()},
        headers={"Authorization": f"Bearer {alice_token}"},
    )

    r = client.get(
        "/beli/eats/digest", headers={"Authorization": f"Bearer {bob_token}"}
    )
    assert r.status_code == 200
    assert r.json()["account_id"] == "b2"
    assert r.json()["bookmarked"] == ["Some Place"]

    # a job scoped to someone else is invisible to alice's digest
    bob_job = client.post(
        "/beli/eats/scan", headers={"Authorization": f"Bearer {bob_token}"}
    ).json()["job_id"]
    client.post(
        f"/beli/eats/scan/{bob_job}/complete",
        json={"posts": _posts()},
        headers={"Authorization": f"Bearer {bob_token}"},
    )
    r = client.get(
        "/beli/eats/digest", headers={"Authorization": f"Bearer {alice_token}"}
    )
    assert r.status_code == 200
    assert r.json()["account_id"] == "a1"
