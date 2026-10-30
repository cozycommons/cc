"""Unit + route tests for approval-gated ESPN roster edits (add/drop).

Everything is mocked — the ESPN wire (stateful fake client / stubbed
urlopen), Supabase (in-memory table fake), and account resolution. No
live ESPN calls.

Covers: propose validation (add target rostered / unknown, drop target
not owned, illegal roster size, add-only with an open slot), the
propose snapshot + preview, approve submitting ONE transaction with
both moves, the waiver-pending outcome, double-approve and expired
edits rejected without submitting, tenant isolation, the wire shape of
the new client method, and the HTTP routes.
"""

import copy
import json
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from espn import espn_client, roster_edits, routes
from espn.accounts import AccountError
from espn.espn_client import EspnClient, EspnError

PG, SG, SF, PF, C, G, F, UTIL, BE, IR = 0, 1, 2, 3, 4, 5, 6, 11, 12, 13
SWID = "{SWID-1}"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
ACCOUNT = {
    "id": "acc-1",
    "label": "warner",
    "league_id": 999,
    "season": 2027,
    "espn_s2": "s2-secret",
    "swid": SWID,
    "lineup_automation_enabled": True,
}
OTHER_ACCOUNT = {**ACCOUNT, "id": "acc-2", "swid": "{SWID-2}"}

FA_ID = 9001        # free agent in the pool
WAIVER_ID = 9002    # pool player sitting on waivers
OTHER_GUY_ID = 201  # rostered by the other team
DROP_ID = 105       # on the account's own roster


# --- fixture builders ----------------------------------------------------------


def _player(pid, name, pro_team=12, pos=PG, slots=(PG, G, UTIL, BE),
            status="ACTIVE"):
    return {
        "id": pid,
        "fullName": name,
        "proTeamId": pro_team,
        "defaultPositionId": pos,
        "eligibleSlots": list(slots),
        "injuryStatus": status,
        "stats": [],
    }


def _entry(pid, slot, player):
    return {
        "playerId": pid,
        "lineupSlotId": slot,
        "playerPoolEntry": {"player": player},
    }


def _payload(active_count=13):
    """League payload: own team 7 at the active cap (13) + 1 IR player,
    other team 8 holding OTHER_GUY_ID."""
    entries = []
    for i in range(active_count):
        pid = 101 + i
        entries.append(
            _entry(pid, BE, _player(pid, f"Roster {pid}", pos=SF,
                                    slots=(SF, F, UTIL, BE)))
        )
    entries.append(
        _entry(114, IR, _player(114, "Roster 114", pos=C,
                                slots=(C, UTIL, BE, IR), status="OUT"))
    )
    return {
        "id": 999,
        "seasonId": 2027,
        "status": {"currentScoringPeriod": 11, "firstScoringPeriod": 1},
        "settings": {
            "rosterSettings": {
                "lineupSlotCounts": {
                    "0": 1, "1": 1, "2": 1, "3": 1, "4": 1,
                    "5": 1, "6": 1, "11": 3, "12": 3, "13": 1,
                }
            },
            "scoringSettings": {"scoringItems": [{"statId": 0, "points": 1.0}]},
        },
        "teams": [
            {"id": 7, "owners": [SWID], "roster": {"entries": entries}},
            {
                "id": 8,
                "owners": ["{SWID-2}"],
                "roster": {
                    "entries": [
                        _entry(OTHER_GUY_ID, BE,
                               _player(OTHER_GUY_ID, "Other Guy", pos=PF,
                                       slots=(PF, F, UTIL, BE)))
                    ]
                },
            },
        ],
    }


def _pool():
    return [
        {"id": FA_ID, "onTeamId": 0,
         "player": _player(FA_ID, "Free Agent Star")},
        {"id": WAIVER_ID, "onTeamId": 0, "status": "WAIVERS",
         "player": _player(WAIVER_ID, "Waiver Wire Wing", pos=SF,
                           slots=(SF, F, UTIL, BE))},
        {"id": OTHER_GUY_ID, "onTeamId": 8,
         "player": _player(OTHER_GUY_ID, "Other Guy", pos=PF,
                           slots=(PF, F, UTIL, BE))},
    ]


# --- fakes ---------------------------------------------------------------------


class FakeTable:
    def __init__(self, store):
        self._store = store
        self._rows = None
        self._update = None

    def _base(self):
        return self._rows if self._rows is not None else list(self._store)

    def insert(self, row):
        row = dict(row)
        row["id"] = f"edit-{len(self._store) + 1}"
        row["created_at"] = (
            f"2026-10-30T00:00:{len(self._store):02d}+00:00"
        )
        self._store.append(row)
        self._rows = [row]
        return self

    def select(self, *a):
        self._rows = list(self._store)
        return self

    def update(self, fields):
        self._update = fields
        self._rows = list(self._store)
        return self

    def eq(self, k, v):
        self._rows = [r for r in self._base() if r.get(k) == v]
        return self

    def order(self, column, desc=False):
        self._rows = sorted(
            self._base(), key=lambda r: r.get(column) or "", reverse=desc
        )
        return self

    def limit(self, n):
        self._rows = self._base()[:n]
        return self

    def execute(self):
        if self._update is not None:
            for row in self._rows:
                row.update(self._update)
        rows = self._rows

        class R:
            data = rows

        return R()


class FakeSupabase:
    def __init__(self):
        self._store = []

    def table(self, name):
        assert name == "espn_roster_edits"
        return FakeTable(self._store)


class FakeClient:
    """ESPN fake: reads from fixtures; a posted transaction mutates the
    roster the way ESPN's would."""

    league_id = 999
    season = 2027

    def __init__(self, payload=None, pool=None):
        self.payload = payload if payload is not None else _payload()
        self.pool = pool if pool is not None else _pool()
        self.posts = []
        self.post_response = None
        self.post_error = None

    def get_league(self, views, scoring_period_id=None):
        return copy.deepcopy(self.payload)

    def get_league_players(self, limit=1000):
        return copy.deepcopy(self.pool)

    def post_roster_transaction(self, member_id, team_id,
                                scoring_period_id, moves, on_waivers=False):
        self.posts.append(
            {
                "member_id": member_id,
                "team_id": team_id,
                "scoring_period_id": scoring_period_id,
                "moves": moves,
                "on_waivers": on_waivers,
            }
        )
        if self.post_error is not None:
            raise self.post_error
        entries = self.payload["teams"][0]["roster"]["entries"]
        pool_by_id = {e["id"]: e["player"] for e in self.pool}
        for move in moves:
            if move["action"] == "DROP":
                entries[:] = [
                    e for e in entries if e["playerId"] != move["playerId"]
                ]
            elif move["action"] == "ADD":
                entries.append(
                    _entry(move["playerId"], BE, pool_by_id[move["playerId"]])
                )
        if self.post_response is not None:
            return self.post_response
        return {
            "id": "txn-1",
            "status": "EXECUTED",
            "type": "WAIVER" if on_waivers else "FREEAGENT",
        }


def _propose(db, client, account=ACCOUNT, **kw):
    kw.setdefault("now", NOW)
    return roster_edits.propose_edit(db, account, client, **kw)


# --- propose: validation ---------------------------------------------------------


def test_propose_swap_success_snapshot_and_preview():
    db, client = FakeSupabase(), FakeClient()
    edit = _propose(db, client, add_player_id=FA_ID, drop_player_id=DROP_ID)
    assert edit["status"] == "pending"
    assert edit["id"] == "edit-1"
    assert edit["team_id"] == 7
    assert edit["add_player"]["name"] == "Free Agent Star"
    assert "PG" in edit["add_player"]["positions"]
    assert edit["add_player"]["pro_team"] == "LAC"
    assert edit["add_player"]["on_waivers"] is None
    assert edit["drop_player"]["name"] == "Roster 105"
    assert "Free Agent Star" in edit["preview"]
    assert "Roster 105" in edit["preview"]
    assert edit["expires_at"] == (NOW + timedelta(minutes=30)).isoformat()
    assert client.posts == []  # propose submits NOTHING


def test_propose_add_rostered_player_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(roster_edits.EditError, match="already rostered"):
        _propose(db, client, add_player_id=OTHER_GUY_ID,
                 drop_player_id=DROP_ID)
    assert db._store == []


def test_propose_add_unknown_player_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(roster_edits.EditError, match="player pool"):
        _propose(db, client, add_player_id=424242, drop_player_id=DROP_ID)


def test_propose_drop_not_owned_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(roster_edits.EditError, match="not on your roster"):
        _propose(db, client, drop_player_id=OTHER_GUY_ID)
    with pytest.raises(roster_edits.EditError, match="not on your roster"):
        _propose(db, client, drop_player_id=FA_ID)


def test_propose_add_only_full_roster_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(roster_edits.EditError, match="roster would exceed"):
        _propose(db, client, add_player_id=FA_ID)


def test_propose_add_only_open_slot_success():
    db = FakeSupabase()
    client = FakeClient(payload=_payload(active_count=12))
    edit = _propose(db, client, add_player_id=FA_ID)
    assert edit["status"] == "pending"
    assert edit["drop_player_id"] is None


def test_propose_drop_only_success():
    db, client = FakeSupabase(), FakeClient()
    edit = _propose(db, client, drop_player_id=DROP_ID)
    assert edit["status"] == "pending"
    assert edit["add_player_id"] is None
    assert edit["preview"].startswith("drop Roster 105")


def test_propose_neither_or_same_player_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(roster_edits.EditError, match="add_player_id and/or"):
        _propose(db, client)
    with pytest.raises(roster_edits.EditError, match="same player"):
        _propose(db, client, add_player_id=DROP_ID, drop_player_id=DROP_ID)


def test_propose_waiver_target_flagged():
    db, client = FakeSupabase(), FakeClient()
    edit = _propose(db, client, add_player_id=WAIVER_ID,
                    drop_player_id=DROP_ID)
    assert edit["add_player"]["on_waivers"] is True
    assert "waiver claim" in edit["preview"]


# --- approve ---------------------------------------------------------------------


def test_approve_swap_submits_one_transaction_with_both_moves():
    db, client = FakeSupabase(), FakeClient()
    edit = _propose(db, client, add_player_id=FA_ID, drop_player_id=DROP_ID)
    result = roster_edits.approve_edit(db, ACCOUNT, client, edit["id"],
                                       now=NOW)
    assert result["status"] == "executed"
    assert result["espn_transaction"]["id"] == "txn-1"
    assert result["executed_at"] == NOW.isoformat()
    assert len(client.posts) == 1
    post = client.posts[0]
    assert post["team_id"] == 7
    assert post["scoring_period_id"] == 11
    assert post["on_waivers"] is False
    assert post["moves"] == [
        {"action": "ADD", "playerId": FA_ID},
        {"action": "DROP", "playerId": DROP_ID},
    ]
    assert db._store[0]["status"] == "executed"


def test_approve_waiver_claim_recorded_waiver_pending():
    db, client = FakeSupabase(), FakeClient()
    client.post_response = {"id": "txn-2", "status": "PENDING",
                            "type": "WAIVER"}
    edit = _propose(db, client, add_player_id=WAIVER_ID,
                    drop_player_id=DROP_ID)
    result = roster_edits.approve_edit(db, ACCOUNT, client, edit["id"],
                                       now=NOW)
    assert result["status"] == "waiver_pending"
    assert client.posts[0]["on_waivers"] is True
    assert db._store[0]["status"] == "waiver_pending"


def test_double_approve_rejected_no_second_submit():
    db, client = FakeSupabase(), FakeClient()
    edit = _propose(db, client, add_player_id=FA_ID, drop_player_id=DROP_ID)
    roster_edits.approve_edit(db, ACCOUNT, client, edit["id"], now=NOW)
    with pytest.raises(roster_edits.EditStateError, match="not pending"):
        roster_edits.approve_edit(db, ACCOUNT, client, edit["id"], now=NOW)
    assert len(client.posts) == 1


def test_expired_edit_rejected_and_marked():
    db, client = FakeSupabase(), FakeClient()
    edit = _propose(db, client, add_player_id=FA_ID, drop_player_id=DROP_ID)
    with pytest.raises(roster_edits.EditStateError, match="expired"):
        roster_edits.approve_edit(
            db, ACCOUNT, client, edit["id"],
            now=NOW + timedelta(minutes=31),
        )
    assert db._store[0]["status"] == "expired"
    assert client.posts == []


def test_approve_submit_failure_recorded_as_failed_edit():
    db, client = FakeSupabase(), FakeClient()
    client.post_error = EspnError("ESPN exploded", status=500)
    edit = _propose(db, client, add_player_id=FA_ID, drop_player_id=DROP_ID)
    result = roster_edits.approve_edit(db, ACCOUNT, client, edit["id"],
                                       now=NOW)
    assert result["status"] == "failed"
    assert "ESPN exploded" in result["error"]
    assert db._store[0]["status"] == "failed"


def test_approve_stale_add_fails_closed():
    db, client = FakeSupabase(), FakeClient()
    edit = _propose(db, client, add_player_id=FA_ID, drop_player_id=DROP_ID)
    # The add target gets rostered by team 8 after the proposal.
    client.payload["teams"][1]["roster"]["entries"].append(
        _entry(FA_ID, BE, _player(FA_ID, "Free Agent Star"))
    )
    with pytest.raises(roster_edits.EditStateError, match="no longer valid"):
        roster_edits.approve_edit(db, ACCOUNT, client, edit["id"], now=NOW)
    assert client.posts == []
    assert db._store[0]["status"] == "failed"


def test_tenant_isolation():
    db, client = FakeSupabase(), FakeClient()
    edit = _propose(db, client, add_player_id=FA_ID, drop_player_id=DROP_ID)
    assert roster_edits.get_edit(db, "acc-2", edit["id"]) is None
    assert roster_edits.list_edits(db, "acc-2")["count"] == 0
    with pytest.raises(roster_edits.EditNotFound):
        roster_edits.approve_edit(db, OTHER_ACCOUNT, client, edit["id"],
                                  now=NOW)
    assert client.posts == []
    # The owner's view still works.
    assert roster_edits.get_edit(db, "acc-1", edit["id"])["id"] == edit["id"]
    assert roster_edits.list_edits(db, "acc-1")["count"] == 1


# --- the client wire shape ---------------------------------------------------------


class _FakeHTTPResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_post_roster_transaction_wire_shape(monkeypatch):
    monkeypatch.setattr(espn_client, "MIN_GAP_S", 0)
    requests = []

    def fake_urlopen(req, timeout=None):
        requests.append(req)
        return _FakeHTTPResponse({"id": "txn-9", "status": "EXECUTED"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = EspnClient("s2", SWID, 999, 2027)
    out = client.post_roster_transaction(
        member_id=SWID,
        team_id=7,
        scoring_period_id=11,
        moves=[
            {"action": "ADD", "playerId": FA_ID},
            {"action": "DROP", "playerId": DROP_ID},
        ],
    )
    assert out["status"] == "EXECUTED"
    assert requests[0].full_url == client.transactions_url()
    body = json.loads(requests[0].data.decode("utf-8"))
    assert body["type"] == "FREEAGENT"
    assert "bidAmount" not in body
    assert body["items"] == [
        {"playerId": FA_ID, "type": "ADD", "fromTeamId": 0, "toTeamId": 7},
        {"playerId": DROP_ID, "type": "DROP", "fromTeamId": 7,
         "toTeamId": 0},
    ]

    requests.clear()
    client.post_roster_transaction(
        member_id=SWID,
        team_id=7,
        scoring_period_id=11,
        moves=[{"action": "ADD", "playerId": WAIVER_ID}],
        on_waivers=True,
    )
    body = json.loads(requests[0].data.decode("utf-8"))
    assert body["type"] == "WAIVER"
    assert body["bidAmount"] == 0

    with pytest.raises(EspnError, match="unsupported roster move"):
        client.post_roster_transaction(
            member_id=SWID,
            team_id=7,
            scoring_period_id=11,
            moves=[{"action": "TRADE", "playerId": 1}],
        )


# --- HTTP routes -------------------------------------------------------------------


@pytest.fixture()
def edits_app(monkeypatch):
    application = FastAPI()
    application.include_router(routes.router, prefix="/espn")
    db = FakeSupabase()
    application.state.supabase = db
    client = FakeClient()

    def fake_get_account(supabase, token):
        if token == "good-token":
            return dict(ACCOUNT)
        raise AccountError("invalid token")

    monkeypatch.setattr(
        routes.accounts, "get_account_by_token", fake_get_account
    )
    monkeypatch.setattr(
        routes.accounts, "make_client_for_account", lambda account: client
    )
    return application, client, db


def _auth(token="good-token"):
    return {"Authorization": f"Bearer {token}"}


def test_roster_edit_routes_round_trip(edits_app):
    application, client, _db = edits_app
    http = TestClient(application)

    r = http.post(
        "/espn/roster/edits",
        json={"add_player_id": FA_ID, "drop_player_id": DROP_ID},
        headers=_auth(),
    )
    assert r.status_code == 200
    edit = r.json()
    assert edit["status"] == "pending"
    assert "Free Agent Star" in edit["preview"]
    assert client.posts == []

    r = http.post(f"/espn/roster/edits/{edit['id']}/approve",
                  headers=_auth())
    assert r.status_code == 200
    assert r.json()["status"] == "executed"
    assert len(client.posts) == 1

    # Second approval is a 409, not a second submission.
    r = http.post(f"/espn/roster/edits/{edit['id']}/approve",
                  headers=_auth())
    assert r.status_code == 409
    assert len(client.posts) == 1

    r = http.get("/espn/roster/edits", headers=_auth())
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r = http.get(f"/espn/roster/edits/{edit['id']}", headers=_auth())
    assert r.status_code == 200
    assert r.json()["status"] == "executed"


def test_roster_edit_routes_errors(edits_app):
    application, _client, _db = edits_app
    http = TestClient(application)

    # No auth.
    r = http.post("/espn/roster/edits", json={"drop_player_id": DROP_ID})
    assert r.status_code == 401

    # Invalid proposal (add target rostered) is a 400.
    r = http.post(
        "/espn/roster/edits",
        json={"add_player_id": OTHER_GUY_ID, "drop_player_id": DROP_ID},
        headers=_auth(),
    )
    assert r.status_code == 400

    # Unknown edit ids are 404 on read and approve.
    r = http.get("/espn/roster/edits/edit-99", headers=_auth())
    assert r.status_code == 404
    r = http.post("/espn/roster/edits/edit-99/approve", headers=_auth())
    assert r.status_code == 404
