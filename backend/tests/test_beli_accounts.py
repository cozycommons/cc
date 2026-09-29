"""Unit tests for Beli account storage: encryption, tokens, isolation.

Uses an in-memory fake of the Supabase table API — no database required.
"""

import os

import pytest

os.environ.setdefault("BELI_CREDENTIALS_KEY", "")

from cryptography.fernet import Fernet

from ig_logger.sinks.beli import accounts


@pytest.fixture()
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("BELI_CREDENTIALS_KEY", key)
    return key


class FakeTable:
    def __init__(self, store):
        self._store = store
        self._rows = None

    def insert(self, row):
        row = dict(row, id=f"id-{len(self._store) + 1}")
        self._store.append(row)
        self._rows = [row]
        return self

    def select(self, *a):
        self._rows = list(self._store)
        return self

    def eq(self, k, v):
        self._rows = [r for r in (self._rows or self._store) if r.get(k) == v]
        return self

    def update(self, values):
        for r in self._store:
            r.update(values)
        return self

    def upsert(self, row, on_conflict=None):
        cols = [c.strip() for c in (on_conflict or "").split(",") if c.strip()]
        for r in self._store:
            if cols and all(r.get(c) == row.get(c) for c in cols):
                r.update(row)
                self._rows = [r]
                return self
        row = dict(row)
        self._store.append(row)
        self._rows = [row]
        return self

    def execute(self):
        class R:
            data = self._rows

        return R()


class FakeSupabase:
    def __init__(self):
        self._store = []
        self._sources = []

    def table(self, name):
        assert name in ("beli_accounts", "ig_sources"), name
        return FakeTable(self._sources if name == "ig_sources" else self._store)


def test_encrypt_decrypt_roundtrip(fernet_key):
    enc = accounts.encrypt_secret("+19178872335")
    assert enc != "+19178872335"
    assert accounts.decrypt_secret(enc) == "+19178872335"


def test_decrypt_with_wrong_key_fails(fernet_key, monkeypatch):
    enc = accounts.encrypt_secret("secret")
    monkeypatch.setenv("BELI_CREDENTIALS_KEY", Fernet.generate_key().decode())
    with pytest.raises(accounts.AccountError):
        accounts.decrypt_secret(enc)


def test_missing_key_raises(fernet_key, monkeypatch):
    monkeypatch.delenv("BELI_CREDENTIALS_KEY")
    with pytest.raises(accounts.AccountError):
        accounts.encrypt_secret("x")


def test_token_hashing():
    t = accounts.mint_token()
    assert t.startswith("ccb_")
    h1, h2 = accounts.hash_token(t), accounts.hash_token(t)
    assert h1 == h2 and len(h1) == 64
    assert accounts.hash_token(accounts.mint_token()) != h1


def _make_account(db, monkeypatch, label="a", beli_id="a@b.com", password="pw"):
    monkeypatch.setattr(
        accounts.BeliClient, "probe_credentials", staticmethod(lambda i, p: {"uuid": "u1"})
    )
    return accounts.create_account(db, label, beli_id, password)


def test_create_account_mints_single_use_token(fernet_key, monkeypatch):
    db = FakeSupabase()
    created = _make_account(db, monkeypatch)
    assert created["token"].startswith("ccb_")
    stored = db._store[0]
    assert stored["token_hash"] == accounts.hash_token(created["token"])
    assert created["token"] not in str(stored)  # plaintext never persisted
    assert accounts.decrypt_secret(stored["beli_id_enc"]) == "a@b.com"


def test_create_account_enables_watcher_by_default(fernet_key, monkeypatch):
    db = FakeSupabase()
    _make_account(db, monkeypatch)
    assert db._store[0]["watcher_opt_in"] is True


def test_create_account_rejects_bad_beli_login(fernet_key, monkeypatch):
    from ig_logger.sinks.beli.beli_client import BeliError

    def boom(i, p):
        raise BeliError("nope", status=400)

    monkeypatch.setattr(accounts.BeliClient, "probe_credentials", staticmethod(boom))
    with pytest.raises(accounts.AccountError):
        accounts.create_account(FakeSupabase(), "x", "bad", "bad")
    assert FakeSupabase()._store == []


def test_token_resolves_exactly_one_account(fernet_key, monkeypatch):
    db = FakeSupabase()
    a = _make_account(db, monkeypatch, label="alice", beli_id="alice@x.com")
    b = _make_account(db, monkeypatch, label="bob", beli_id="+15550001111", password="pw2")
    got_a = accounts.get_account_by_token(db, a["token"])
    got_b = accounts.get_account_by_token(db, b["token"])
    assert got_a["beli_id"] == "alice@x.com"
    assert got_b["beli_id"] == "+15550001111"
    # cross-account isolation: alice's token never yields bob's creds
    assert got_a["id"] != got_b["id"]
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, "ccb_wrong")
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, "not-a-token")
