"""Bounded league-source reads; the season route ignores filter headers."""
import json
import pytest
from espn import espn_client, logic
from espn.espn_client import EspnClient, EspnError


def test_league_kona_omits_unsupported_limit_but_limits_result(monkeypatch):
    client = EspnClient("synthetic", "{SYNTHETIC}", 1, 2027)
    calls = []
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return {"players": [{"id": 1}, {"id": 2}, {"id": 3}]}
    monkeypatch.setattr(client, "_get", get)
    assert client.get_league_players(2) == [{"id": 1}, {"id": 2}]
    assert "/leagues/1?" in calls[0][0]
    assert "limit" not in json.loads(calls[0][1]["headers"]["X-Fantasy-Filter"])["players"]


def test_read_caps_body_before_decoding(monkeypatch):
    client = EspnClient("synthetic", "{SYNTHETIC}", 1, 2027)
    monkeypatch.setattr(client, "_pace", lambda: None)
    monkeypatch.setattr(espn_client, "MAX_READ_BYTES", 8)
    sizes = []
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            sizes.append(size)
            return b"x" * size
    monkeypatch.setattr(espn_client.urllib.request, "urlopen", lambda *a, **k: Response())
    with pytest.raises(EspnError, match="size limit"):
        client.get_league_players(2)
    assert sizes == [9]


def test_snapshot_uses_league_source_only():
    class Client:
        def get_league(self, *a, **k): return {}
        def get_league_players(self, limit, **kwargs):
            assert limit == 300
            return [{"id": 1, "player": {"id": 1, "fullName": "Synthetic"}}]
        def get_players(self, *a, **k):
            raise AssertionError("unfiltered season source must not be used")
    assert logic.build_snapshot(Client())["players"][0]["name"] == "Synthetic"
