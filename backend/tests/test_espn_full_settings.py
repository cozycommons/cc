"""Roster-view truncation preserves all standalone league rules."""
import pytest
from espn.espn_client import EspnClient


@pytest.mark.parametrize("max_age", [0, 30])
def test_partial_roster_settings_refetch_preserves_rules_and_cache_policy(monkeypatch, max_age):
    client = EspnClient("synthetic", "{SYNTHETIC}", 1, 2027)
    calls = []
    full = {"acquisitionSettings": {"matchupAcquisitionLimit": 3},
            "rosterSettings": {"lineupSlotCounts": {"0": 1}}, "scoringSettings": {}}
    def get(url, **kwargs):
        calls.append((url, kwargs))
        if "mRoster" in url:
            return {"settings": {"isPublic": False, "scoringSettings": {}}, "teams": [{"id": 1}]}
        return {"settings": full}
    monkeypatch.setattr(client, "_get", get)
    result = client.get_league(["mSettings", "mRoster"], max_age=max_age)
    assert result["settings"] == {"isPublic": False, **full}
    assert result["teams"] == [{"id": 1}]
    assert len(calls) == 2 and calls[-1][0].endswith("?view=mSettings")
    assert all(call[1]["max_age"] == max_age for call in calls)


def test_complete_roster_settings_need_no_second_request(monkeypatch):
    client = EspnClient("synthetic", "{SYNTHETIC}", 1, 2027)
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return {"settings": {"acquisitionSettings": {}, "rosterSettings": {}, "scoringSettings": {}}}
    monkeypatch.setattr(client, "_get", get)
    client.get_league(["mSettings", "mRoster"])
    assert len(calls) == 1
