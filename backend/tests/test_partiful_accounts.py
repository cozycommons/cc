"""Unit tests for Partiful account storage: encryption, tokens, isolation.

Uses an in-memory fake of the Supabase table API — no database required.
"""

import os

import pytest

os.environ.setdefault("PARTIFUL_CREDENTIALS_KEY", "")

from cryptography.fernet import Fernet

from partiful import accounts


@pytest.fixture()
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PARTIFUL_CREDENTIALS_KEY", key)
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

    def execute(self):
        class R:
            data = self._rows

        return R()


class FakeSupabase:
    def __init__(self):
        self._store = []

    def table(self, name):
        assert name == "partiful_accounts"
        return FakeTable(self._store)


def test_encrypt_decrypt_roundtrip(fernet_key):
    enc = accounts.encrypt_secret("refresh-token-abc")
    assert enc != "refresh-token-abc"
    assert accounts.decrypt_secret(enc) == "refresh-token-abc"


def test_decrypt_with_wrong_key_fails(fernet_key, monkeypatch):
    enc = accounts.encrypt_secret("secret")
    monkeypatch.setenv("PARTIFUL_CREDENTIALS_KEY", Fernet.generate_key().decode())
    with pytest.raises(accounts.AccountError):
        accounts.decrypt_secret(enc)


def test_missing_key_raises(fernet_key, monkeypatch):
    monkeypatch.delenv("PARTIFUL_CREDENTIALS_KEY")
    with pytest.raises(accounts.AccountError):
        accounts.encrypt_secret("x")


def test_token_hashing():
    t = accounts.mint_token()
    assert t.startswith("ccp_")
    h1, h2 = accounts.hash_token(t), accounts.hash_token(t)
    assert h1 == h2 and len(h1) == 64
    assert accounts.hash_token(accounts.mint_token()) != h1


def _make_account(db, monkeypatch, label="a", phone="8185551234", code="123456"):
    monkeypatch.setattr(
        accounts.PartifulClient,
        "verify_auth_code",
        staticmethod(lambda p, c: {"refresh_token": "rt-1", "uid": "uid-1"}),
    )
    return accounts.create_account(db, label, phone, code)


def test_create_account_mints_single_use_token(fernet_key, monkeypatch):
    db = FakeSupabase()
    created = _make_account(db, monkeypatch)
    assert created["token"].startswith("ccp_")
    stored = db._store[0]
    assert stored["token_hash"] == accounts.hash_token(created["token"])
    assert created["token"] not in str(stored)  # plaintext never persisted
    assert accounts.decrypt_secret(stored["refresh_token_enc"]) == "rt-1"
    assert accounts.decrypt_secret(stored["uid_enc"]) == "uid-1"


def test_create_account_rejects_bad_phone(fernet_key, monkeypatch):
    with pytest.raises(accounts.AccountError):
        accounts.create_account(FakeSupabase(), "x", "not-a-phone", "123456")


def test_create_account_rejects_bad_sms_code(fernet_key, monkeypatch):
    from partiful.partiful_client import PartifulError

    def boom(p, c):
        raise PartifulError("wrong or expired SMS code")

    monkeypatch.setattr(accounts.PartifulClient, "verify_auth_code", staticmethod(boom))
    db = FakeSupabase()
    with pytest.raises(accounts.AccountError):
        accounts.create_account(db, "x", "8185551234", "000000")
    assert db._store == []


def test_token_resolves_exactly_one_account(fernet_key, monkeypatch):
    db = FakeSupabase()
    a = _make_account(db, monkeypatch, label="alice", phone="8185551111")
    b = _make_account(db, monkeypatch, label="bob", phone="8185552222")
    got_a = accounts.get_account_by_token(db, a["token"])
    got_b = accounts.get_account_by_token(db, b["token"])
    assert got_a["label"] == "alice"
    assert got_b["label"] == "bob"
    # cross-account isolation: alice's token never yields bob's creds
    assert got_a["id"] != got_b["id"]
    assert got_a["refresh_token"] == got_b["refresh_token"] == "rt-1"
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, "ccp_wrong")
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, "ccb_not-partiful")


def test_make_client_persists_rotated_refresh_token(fernet_key, monkeypatch):
    db = FakeSupabase()
    created = _make_account(db, monkeypatch)
    account = accounts.get_account_by_token(db, created["token"])
    client = accounts.make_client_for_account(db, account)
    # simulate Google rotating the refresh token
    client._on_refresh("rt-rotated")
    assert accounts.decrypt_secret(db._store[0]["refresh_token_enc"]) == "rt-rotated"
