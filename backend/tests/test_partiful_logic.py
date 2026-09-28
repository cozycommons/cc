"""Unit tests for Partiful event-listing logic: scopes, dedupe, date filters."""

import pytest

from partiful import logic


def _event(eid, start, guest_status=None, title=None):
    e = {"id": eid, "title": title or eid, "startDate": start}
    if guest_status is not None:
        e["guest"] = {"status": guest_status}
    return e


class FakeClient:
    def __init__(self, hosted, rsvps):
        self._hosted = hosted
        self._rsvps = rsvps

    def get_published_events(self):
        return self._hosted

    def get_my_rsvps(self):
        return self._rsvps

    def get_event_info(self, event_id):
        for e in self._hosted + self._rsvps:
            if e["id"] == event_id:
                return {"event": e, "passwordRequired": False}
        raise AssertionError("unknown event")


@pytest.fixture()
def client():
    hosted = [_event("h1", "2026-09-26T18:00:00.000Z", title="Hosted Party")]
    rsvps = [
        _event("r1", "2026-09-27T19:00:00.000Z", "GOING", title="RSVPd Dinner"),
        _event("r2", "2026-09-28T19:00:00.000Z", "SENT", title="Invite Pending"),
        _event("h1", "2026-09-26T18:00:00.000Z", "GOING", title="Hosted Party"),
        _event("tbd", "TBD", "MAYBE", title="TBD Thing"),
    ]
    return FakeClient(hosted, rsvps)


def test_scope_all_merges_and_dedupes(client):
    res = logic.list_events(client, "all")
    assert res["count"] == 4
    by_id = {e["id"]: e for e in res["events"]}
    assert by_id["h1"]["scopes"] == ["hosted", "invited", "rsvp"]
    assert by_id["r1"]["scopes"] == ["invited", "rsvp"]
    assert by_id["r2"]["scopes"] == ["invited"]
    assert by_id["r1"]["rsvp_status"] == "GOING"
    assert by_id["r2"]["rsvp_status"] == "SENT"


def test_scope_hosted(client):
    res = logic.list_events(client, "hosted")
    assert [e["id"] for e in res["events"]] == ["h1"]
    assert res["events"][0]["scopes"] == ["hosted"]


def test_scope_rsvps_excludes_unresponded(client):
    res = logic.list_events(client, "rsvps")
    assert {e["id"] for e in res["events"]} == {"h1", "r1", "tbd"}


def test_scope_invited_includes_everything(client):
    res = logic.list_events(client, "invited")
    assert res["count"] == 4


def test_date_filter_weekend(client):
    res = logic.list_events(client, "all", start="2026-09-26", end="2026-09-27")
    assert [e["id"] for e in res["events"]] == ["h1", "r1"]


def test_date_filter_excludes_tbd_when_filtering(client):
    res = logic.list_events(client, "all", start="2026-01-01", end="2026-12-31")
    assert "tbd" not in [e["id"] for e in res["events"]]


def test_sort_order_dated_then_tbd(client):
    res = logic.list_events(client, "all")
    assert [e["id"] for e in res["events"]] == ["h1", "r1", "r2", "tbd"]


def test_invalid_scope_rejected(client):
    with pytest.raises(ValueError):
        logic.list_events(client, "bogus")


def test_invalid_dates_rejected(client):
    with pytest.raises(ValueError):
        logic.list_events(client, "all", start="09/26/2026")
    with pytest.raises(ValueError):
        logic.list_events(client, "all", start="2026-09-28", end="2026-09-26")


def test_get_event(client):
    res = logic.get_event(client, "r1")
    assert res["event"]["id"] == "r1"
    assert res["event"]["title"] == "RSVPd Dinner"
    assert res["password_required"] is False


def test_get_event_requires_id(client):
    with pytest.raises(ValueError):
        logic.get_event(client, "  ")
