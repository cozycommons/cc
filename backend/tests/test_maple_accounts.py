"""Unit tests for Maple telemetry account storage: tokens and isolation.

Uses an in-memory fake of the Supabase table API — no database required.
"""

import pytest

from maple import accounts
from tests.maple_fakes import FakeSupabase


def test_token_minting_and_hashing():
    token = accounts.mint_token()
    assert token.startswith("ccm_")
    assert accounts.hash_token(token) == accounts.hash_token(token)
    assert len(accounts.hash_token(token)) == 64
    assert accounts.hash_token(accounts.mint_token()) != accounts.hash_token(token)


def test_create_account_mints_single_use_token():
    db = FakeSupabase()
    created = accounts.create_account(db, "warner")
    assert created["token"].startswith("ccm_")
    assert created["label"] == "warner"
    stored = db.stores["maple_accounts"][0]
    assert stored["token_hash"] == accounts.hash_token(created["token"])
    assert created["token"] not in str(stored)  # plaintext never persisted


def test_create_account_default_label():
    db = FakeSupabase()
    created = accounts.create_account(db, None)
    assert created["label"] == "maple"


def test_token_resolves_exactly_one_account():
    db = FakeSupabase()
    first = accounts.create_account(db, "first")
    second = accounts.create_account(db, "second")
    resolved = accounts.get_account_by_token(db, first["token"])
    assert resolved == {"id": first["id"], "label": "first"}
    assert accounts.get_account_by_token(db, second["token"])["id"] == second["id"]


def test_unknown_and_malformed_tokens_rejected():
    db = FakeSupabase()
    accounts.create_account(db, "warner")
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, "ccm_" + "x" * 43)
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, "cce_" + "x" * 43)  # ESPN prefix
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, "")
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, None)


def test_delete_account_retires_token():
    db = FakeSupabase()
    created = accounts.create_account(db, "warner")
    accounts.delete_account(db, created["id"])
    with pytest.raises(accounts.AccountError):
        accounts.get_account_by_token(db, created["token"])
