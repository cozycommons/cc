"""Unit tests for ESPN account storage: encryption, tokens, isolation.

Uses an in-memory fake of the Supabase table API — no database required.
"""

import os

import pytest

os.environ.setdefault("ESPN_CREDENTIALS_KEY", "")

from cryptography.fernet import Fernet

from espn import accounts
from espn.espn_client import EspnAuthError, EspnError


@pytest.fixture()
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ESPN_CREDENTIALS_KEY", key)
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
        assert name == "espn_accounts"
        return FakeTable(self._store)


def test_encrypt_decrypt_roundtrip(fernet_key):
    enc = accounts.encrypt_secret("espn-s2-abc")
    assert enc != "espn-s2-abc"
    assert accounts.decrypt_secret(enc) == "espn-s2-abc"


def test_decrypt_with_wrong_key_fails(fernet_key, monkeypatch):
    enc = accounts.encrypt_secret("secret")
    monkeypatch.setenv("ESPN_CREDENTIALS_KEY", Fernet.generate_key().decode())
    with pytest.raises(accounts.AccountError):
        accounts.decrypt_secret(enc)


def test_missing_key_raises(fernet_key, monkeypatch):
    monkeypatch.delenv("ESPN_CREDENTIALS_KEY")
    with pytest.raises(accounts.AccountError):
        accounts.encrypt_secret("x")


def test_token_hashing():
    t = accounts.mint_token()
    assert t.startswith("cce_")
    h1, h2 = accounts.hash_token(t), accounts.hash_token(t)
    assert h1 == h2 and len(h1) == 64
    assert accounts.hash_token(accounts.mint_token()) != h1


def _probe_ok(monkeypatch, calls=None):
    def probe(espn_s2, swid, league_id, season):
        if calls is not None:
            calls.append((espn_s2, swid, league_id, season))
        return {}

    monkeypatch.setattr(accounts.EspnClient, "probe", staticmethod(probe))


def _make_account(
    db,
    monkeypatch,
    label="a",
    league_id=111,
    season=2027,
    espn_s2="s2-1",
    swid="{SWID-1}",
):
    _probe_ok(monkeypatch)
    return accounts.create_account(db, label, league_id, season, espn_s2, swid)


def test_create_account_stores_encrypted_cookies_and_mints_token(
    fernet_key, monkeypatch
):
    db = FakeSupabase()
    calls = []
    _probe_ok(monkeypatch, calls)
    created = accounts.create_account(
        db, "  warner  ", "222", "2027", "s2-secret-value", "{SWID-secret-value}"
    )
    # probe ran first, with the coerced league/season values
    assert calls == [("s2-secret-value", "{SWID-secret-value}", 222, 2027)]
    assert created["token"].startswith("cce_")
    assert created["label"] == "warner"
    assert created["league_id"] == 222
    assert created["season"] == 2027
    stored = db._store[0]
    assert stored["label"] == "warner"
    assert stored["league_id"] == 222
    assert stored["season"] == 2027
    assert stored["token_hash"] == accounts.hash_token(created["token"])
    assert stored["token_prefix"] == created["token"][:12]
    # plaintext token and cookies are nowhere in the stored row
    assert created["token"] not in str(stored)
    assert "s2-secret-value" not in str(stored)
    assert "{SWID-secret-value}" not in str(stored)
    assert accounts.decrypt_secret(stored["espn_s2_enc"]) == "s2-secret-value"
    assert accounts.decrypt_secret(stored["swid_enc"]) == "{SWID-secret-value}"


def test_create_account_defaults_label(fernet_key, monkeypatch):
    db = FakeSupabase()
    created = _make_account(db, monkeypatch, label="  ")
    assert created["label"] == "espn"
    assert db._store[0]["label"] == "espn"


@pytest.mark.parametrize("league_id", [0, -5, "abc", "", None, 1.5])
def test_create_account_rejects_bad_league_id(fernet_key, monkeypatch, league_id):
    _probe_ok(monkeypatch)
    db = FakeSupabase()
    with pytest.raises(accounts.AccountError):
        accounts.create_account(db, "x", league_id, 2027, "s2", "{SWID}")
    assert db._store == []


@pytest.mark.parametrize("season", [2018, 2200, "abc", "", None])
def test_create_account_rejects_bad_season(fernet_key, monkeypatch, season):
    _probe_ok(monkeypatch)
    db = FakeSupabase()
    with pytest.raises(accounts.AccountError):
        accounts.create_account(db, "x", 111, season, "s2", "{SWID}")
    assert db._store == []


@pytest.mark.parametrize(
    "espn_s2,swid", [("", "{SWID}"), ("   ", "{SWID}"), ("s2", ""), ("s2", "  "), ("", "")]
)
def test_create_account_rejects_empty_cookies(fernet_key, monkeypatch, espn_s2, swid):
    _probe_ok(monkeypatch)
    db = FakeSupabase()
    with pytest.raises(accounts.AccountError):
        accounts.create_account(db, "x", 111, 2027, espn_s2, swid)
    assert db._store == []


def test_create_account_probe_auth_error_stores_nothing(fernet_key, monkeypatch):
    def boom(espn_s2, swid, league_id, season):
        raise EspnAuthError("cookies rejected")

    monkeypatch.setattr(accounts.EspnClient, "probe", staticmethod(boom))
    db = FakeSupabase()
    with pytest.raises(accounts.AccountError, match="rejected"):
        accounts.create_account(db, "x", 111, 2027, "s2", "{SWID}")
    assert db._store == []


def test_create_account_probe_error_stores_nothing(fernet_key, monkeypatch):
    def boom(espn_s2, swid, league_id, season):
        raise EspnError("league not found", status=404)

    monkeypatch.setattr(accounts.EspnClient, "probe", staticmethod(boom))
    db = FakeSupabase()
    with pytest.raises(accounts.AccountError, match="ESPN verification failed"):
        accounts.create_account(db, "x", 111, 2027, "s2", "{SWID}")
    assert db._store == []


def test_token_resolves_exactly_one_account(fernet_key, monkeypatch):
    db = FakeSupabase()
    a = _make_account(
        db, monkeypatch, label="alice", league_id=111, espn_s2="s2-a", swid="{SWID-A}"
    )
    b = _make_account(
        db, monkeypatch, label="bob", league_id=222, espn_s2="s2-b", swid="{SWID-B}"
    )
    got_a = accounts.get_account_by_token(db, a["token"])
    got_b = accounts.get_account_by_token(db, b["token"])
    assert got_a["label"] == "alice"
    assert got_b["label"] == "bob"
    # cross-account isolation: alice's token never yields bob's league/creds
    assert got_a["id"] != got_b["id"]
    assert got_a["league_id"] == 111
    assert got_b["league_id"] == 222
    assert got_a["season"] == got_b["season"] == 2027
    assert got_a["espn_s2"] == "s2-a"
    assert got_b["espn_s2"] == "s2-b"
    assert got_a["swid"] == "{SWID-A}"
    assert got_b["swid"] == "{SWID-B}"
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, "cce_wrong")
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, "ccp_not-espn")


def test_make_client_for_account_passes_account_fields(fernet_key, monkeypatch):
    db = FakeSupabase()
    created = _make_account(
        db, monkeypatch, league_id=333, season=2026, espn_s2="s2-x", swid="{SWID-X}"
    )
    account = accounts.get_account_by_token(db, created["token"])
    client = accounts.make_client_for_account(account)
    assert isinstance(client, accounts.EspnClient)
    assert client._espn_s2 == "s2-x"
    assert client._swid == "{SWID-X}"
    assert client.league_id == 333
    assert client.season == 2026
