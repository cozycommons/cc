"""Synthetic provider failure text never becomes a saved/displayed secret."""
import io
import urllib.error
import urllib.request
import pytest
from espn.espn_client import EspnClient, EspnError, EspnWriteUncertain
from espn.errors import failure_reason
from espn.scoreboard import ScoreboardClient


@pytest.mark.parametrize("method", ["GET", "POST", "scoreboard"])
def test_transport_scrubs_echoed_credentials_and_preserves_http_status(monkeypatch, method):
    client = EspnClient("dummy", "{DUMMY}", 1, 2027)
    monkeypatch.setattr(client, "_pace", lambda: None)
    body = b'Provider rejected request at https://example.test/private Cookie: dummy short multiword secret'
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test", 409, "conflict", {}, io.BytesIO(body))
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(EspnError) as caught:
        if method == "GET":
            client._get("https://example.test")
        elif method == "POST":
            client._post("https://example.test", {})
        else:
            ScoreboardClient()._fetch({"dates": "20261104"})
    assert caught.value.status == 409
    assert not any(value in str(caught.value) for value in ("example.test", "dummy", "short", "multiword", "secret"))


def test_uncertain_write_stays_uncertain_when_scrubbed(monkeypatch):
    client = EspnClient("dummy", "{DUMMY}", 1, 2027)
    monkeypatch.setattr(client, "_pace", lambda: None)
    def fail(*args, **kwargs):
        raise urllib.error.URLError("Authorization: Bearer short secret")
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(EspnWriteUncertain) as caught:
        client._post("https://example.test", {})
    assert "secret" not in failure_reason(caught.value)
    assert "Bearer" not in failure_reason(caught.value)


def test_post_keeps_late_lock_marker_for_lineup_retry(monkeypatch):
    client = EspnClient("dummy", "{DUMMY}", 1, 2027)
    monkeypatch.setattr(client, "_pace", lambda: None)
    marker = "Synthetic Player is locked"
    body = ("message " * 21 + marker + " Cookie: short secret").encode()

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test", 409, "conflict", {}, io.BytesIO(body))

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(EspnError) as caught:
        client._post("https://example.test", {})
    assert caught.value.status == 409
    assert marker in str(caught.value)
    assert "short secret" not in str(caught.value)
