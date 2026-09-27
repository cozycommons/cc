"""Tests for session-first Instagram login in the @beli_eats watcher."""

import base64

from beli.eats_watcher import _login_instaloader


class FakeLoader:
    def __init__(self, fail_session: bool = False):
        self.calls = []
        self.fail_session = fail_session

    def load_session_from_file(self, username, path):
        if self.fail_session:
            raise RuntimeError("session expired")
        with open(path, "rb") as f:
            assert f.read() == b"fake-session-bytes"
        self.calls.append(("load_session_from_file", username))

    def login(self, username, password):
        self.calls.append(("login", username, password))


def test_session_login_preferred(monkeypatch):
    monkeypatch.setenv(
        "BELI_EATS_IG_SESSION", base64.b64encode(b"fake-session-bytes").decode()
    )
    loader = FakeLoader()
    _login_instaloader(loader, "burner", "pw")
    assert loader.calls == [("load_session_from_file", "burner")]


def test_password_fallback_when_no_session(monkeypatch):
    monkeypatch.delenv("BELI_EATS_IG_SESSION", raising=False)
    loader = FakeLoader()
    _login_instaloader(loader, "burner", "pw")
    assert loader.calls == [("login", "burner", "pw")]


def test_password_fallback_when_session_corrupt(monkeypatch):
    monkeypatch.setenv("BELI_EATS_IG_SESSION", "not-valid-base64!!!")
    loader = FakeLoader()
    _login_instaloader(loader, "burner", "pw")
    assert loader.calls == [("login", "burner", "pw")]


def test_password_fallback_when_session_rejected(monkeypatch):
    monkeypatch.setenv(
        "BELI_EATS_IG_SESSION", base64.b64encode(b"fake-session-bytes").decode()
    )
    loader = FakeLoader(fail_session=True)
    _login_instaloader(loader, "burner", "pw")
    assert loader.calls == [("login", "burner", "pw")]


def test_no_login_without_credentials(monkeypatch):
    monkeypatch.delenv("BELI_EATS_IG_SESSION", raising=False)
    loader = FakeLoader()
    _login_instaloader(loader, None, None)
    assert loader.calls == []
