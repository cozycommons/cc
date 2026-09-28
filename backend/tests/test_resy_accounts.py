"""Unit tests for Resy account storage: encryption, tokens, isolation.

Uses an in-memory fake of the Supabase table API — no database required.
The live Resy login is stubbed.
"""

import os

import pytest

os.environ.setdefault("RESY_CREDENTIALS_KEY", "")
os.environ.setdefault("RESY_API_KEY", "test-public-key")

from cryptography.fernet import Fernet

from resy import accounts
from resy.resy_client import ResyAuthError


@pytest.fixture()
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("RESY_CREDENTIALS_KEY", key)
    return key


class FakeTable:
    def __init__(self, store, name):
        self._store = store
        self._name = name
        self._rows = None

    def insert(self, row):
        assert self._name == "resy_accounts"
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
        for r in self._rows or self._store:
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
        return FakeTable(self._store, name)


class FakeClient:
    _auth_token = "tok-live"


def _stub_login(monkeypatch, token="tok-live", fail=False):
    def login_with(email, password):
        if fail:
            raise ResyAuthError("bad credentials")
        c = FakeClient()
        c._auth_token = token
        return c

    monkeypatch.setattr("resy.accounts.ResyClient.login_with", staticmethod(login_with))


def test_encrypt_decrypt_roundtrip(fernet_key):
    enc = accounts.encrypt_secret("s3cret-pw")
    assert enc != "s3cret-pw"
    assert accounts.decrypt_secret(enc) == "s3cret-pw"


def test_decrypt_with_wrong_key_fails(fernet_key, monkeypatch):
    enc = accounts.encrypt_secret("secret")
    monkeypatch.setenv("RESY_CREDENTIALS_KEY", Fernet.generate_key().decode())
    with pytest.raises(accounts.AccountError):
        accounts.decrypt_secret(enc)


def test_missing_key_raises(fernet_key, monkeypatch):
    monkeypatch.delenv("RESY_CREDENTIALS_KEY")
    with pytest.raises(accounts.AccountError):
        accounts.encrypt_secret("x")


def test_create_account_stores_encrypted_creds(fernet_key, monkeypatch):
    _stub_login(monkeypatch)
    sb = FakeSupabase()
    out = accounts.create_account(sb, "warner", "w@example.com", "pw123")
    assert out["token"].startswith("ccr_")
    assert out["label"] == "warner"
    row = sb._store[0]
    assert row["email_enc"] != "w@example.com"
    assert row["password_enc"] != "pw123"
    assert row["auth_token_enc"] != "tok-live"
    assert row["token_hash"] != out["token"]  # hash, not plaintext
    assert row["token_prefix"] == out["token"][:12]


def test_create_account_rejects_bad_login(fernet_key, monkeypatch):
    _stub_login(monkeypatch, fail=True)
    with pytest.raises(accounts.AccountError, match="Resy login failed"):
        accounts.create_account(FakeSupabase(), "x", "w@example.com", "nope")


def test_create_account_validates_email(fernet_key, monkeypatch):
    with pytest.raises(accounts.AccountError, match="valid email"):
        accounts.create_account(FakeSupabase(), "x", "not-an-email", "pw")


def test_token_resolves_to_own_account_only(fernet_key, monkeypatch):
    _stub_login(monkeypatch)
    sb = FakeSupabase()
    a = accounts.create_account(sb, "alice", "a@example.com", "pw-a")
    b = accounts.create_account(sb, "bob", "b@example.com", "pw-b")
    got = accounts.get_account_by_token(sb, a["token"])
    assert got["email"] == "a@example.com"
    assert got["password"] == "pw-a"
    assert got["auth_token"] == "tok-live"
    got_b = accounts.get_account_by_token(sb, b["token"])
    assert got_b["email"] == "b@example.com"
    # unknown / wrong-prefix tokens are rejected
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(sb, "ccr_" + "x" * 43)
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(sb, "ccp_faketoken")


def test_make_client_persists_refreshed_token(fernet_key, monkeypatch):
    _stub_login(monkeypatch)
    sb = FakeSupabase()
    out = accounts.create_account(sb, "warner", "w@example.com", "pw123")
    account = accounts.get_account_by_token(sb, out["token"])
    client = accounts.make_client_for_account(sb, account)
    assert isinstance(client._auth_token, str)
    # simulate a rotation: the new token is persisted encrypted
    client._on_token_refresh("tok-rotated")
    row = sb._store[0]
    assert accounts.decrypt_secret(row["auth_token_enc"]) == "tok-rotated"
