"""Unit + route tests for approval-gated ESPN trade proposals.

Everything is mocked — the ESPN wire (stateful fake client / stubbed
urlopen), Supabase (in-memory table fake), and account resolution. No
live ESPN calls, and NO trade is ever submitted outside the fakes.

Covers: propose validation (self-trade, unknown counterparty, give
player not owned, receive player not on the counterparty, roster
overflow on the caller's side and on the counterparty's side across
1-for-1 / 2-for-1 / 1-for-2 shapes, IR-slot accounting, past trade
deadline), the propose snapshot + preview, approve submitting ONE
TRADE transaction with the exact wire items, stale-proposal
fail-closed, double-approve and expired proposals rejected without
submitting, tenant isolation, the client wire shape, and the routes.
"""

import copy
import json
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from espn import espn_client, routes, trades
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

OWN_TEAM = 7
CP_TEAM = 8
GIVE_ID = 105        # on the account's own roster
GIVE2_ID = 106       # also on the account's own roster
OWN_IR_ID = 114      # on the account's own IR slot
CP_ID = 201          # on the counterparty's roster
CP2_ID = 202         # also on the counterparty's roster
FUTURE_DEADLINE_MS = 1803056400000   # 2027-02-19 (the live league's)
PAST_DEADLINE_MS = 1790000000000     # 2026-09-18, before NOW


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


def _cp_entries(full=False):
    if full:
        entries = [
            _entry(201 + i, BE, _player(201 + i, f"Rival {201 + i}",
                                        pos=PF, slots=(PF, F, UTIL, BE)))
            for i in range(13)
        ]
        entries.append(
            _entry(214, IR, _player(214, "Rival 214", pos=C,
                                    slots=(C, UTIL, BE, IR), status="OUT"))
        )
        return entries
    return [
        _entry(CP_ID, BE, _player(CP_ID, "Rival Star", pos=PF,
                                  slots=(PF, F, UTIL, BE))),
        _entry(CP2_ID, BE, _player(CP2_ID, "Rival Wing", pos=SF,
                                   slots=(SF, F, UTIL, BE))),
        _entry(203, BE, _player(203, "Rival Big", pos=C,
                                slots=(C, UTIL, BE))),
    ]


def _payload(own_active=13, cp_full=False, deadline_ms=FUTURE_DEADLINE_MS):
    """League payload: own team 7 (``own_active`` active + 1 IR player),
    counterparty team 8. Slot counts: 14 total, 13 active cap."""
    entries = []
    for i in range(own_active):
        pid = 101 + i
        entries.append(
            _entry(pid, BE, _player(pid, f"Roster {pid}", pos=SF,
                                    slots=(SF, F, UTIL, BE)))
        )
    entries.append(
        _entry(OWN_IR_ID, IR, _player(OWN_IR_ID, "Roster 114", pos=C,
                                      slots=(C, UTIL, BE, IR),
                                      status="OUT"))
    )
    settings = {
        "rosterSettings": {
            "lineupSlotCounts": {
                "0": 1, "1": 1, "2": 1, "3": 1, "4": 1,
                "5": 1, "6": 1, "11": 3, "12": 3, "13": 1,
            }
        },
        "scoringSettings": {"scoringItems": [{"statId": 0, "points": 1.0}]},
    }
    if deadline_ms is not None:
        settings["tradeSettings"] = {"deadlineDate": deadline_ms}
    return {
        "id": 999,
        "seasonId": 2027,
        "status": {"currentScoringPeriod": 11, "firstScoringPeriod": 1},
        "settings": settings,
        "teams": [
            {"id": OWN_TEAM, "name": "My Team", "owners": [SWID],
             "roster": {"entries": entries}},
            {"id": CP_TEAM, "name": "Rival Team",
             "owners": ["{SWID-2}"],
             "roster": {"entries": _cp_entries(full=cp_full)}},
        ],
    }


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
        row["id"] = f"prop-{len(self._store) + 1}"
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
        assert name == "espn_trade_proposals"
        return FakeTable(self._store)


class FakeClient:
    """ESPN fake: reads from fixtures; records every trade submission."""

    league_id = 999
    season = 2027

    def __init__(self, payload=None):
        self.payload = payload if payload is not None else _payload()
        self.posts = []
        self.post_response = None
        self.post_error = None

    def get_league(self, views, scoring_period_id=None):
        return copy.deepcopy(self.payload)

    def post_trade_transaction(self, member_id, team_id,
                               counterparty_team_id, scoring_period_id,
                               give_player_ids, receive_player_ids):
        self.posts.append(
            {
                "member_id": member_id,
                "team_id": team_id,
                "counterparty_team_id": counterparty_team_id,
                "scoring_period_id": scoring_period_id,
                "give_player_ids": give_player_ids,
                "receive_player_ids": receive_player_ids,
            }
        )
        if self.post_error is not None:
            raise self.post_error
        if self.post_response is not None:
            return self.post_response
        return {"id": "txn-trade-1", "status": "PENDING", "type": "TRADE"}


def _propose(db, client, account=ACCOUNT, **kw):
    kw.setdefault("now", NOW)
    kw.setdefault("counterparty_team_id", CP_TEAM)
    kw.setdefault("give_player_ids", [GIVE_ID])
    kw.setdefault("receive_player_ids", [CP_ID])
    return trades.propose_trade(db, account, client, **kw)


# --- propose: happy paths --------------------------------------------------------


def test_propose_one_for_one_success_snapshot_and_preview():
    db, client = FakeSupabase(), FakeClient()
    prop = _propose(db, client)
    assert prop["status"] == "pending"
    assert prop["id"] == "prop-1"
    assert prop["team_id"] == OWN_TEAM
    assert prop["counterparty_team_id"] == CP_TEAM
    assert prop["give_player_ids"] == [GIVE_ID]
    assert prop["receive_player_ids"] == [CP_ID]
    assert prop["give_players"][0]["name"] == "Roster 105"
    assert prop["give_players"][0]["team_id"] == OWN_TEAM
    assert prop["receive_players"][0]["name"] == "Rival Star"
    assert prop["receive_players"][0]["team_id"] == CP_TEAM
    assert "Rival Team" in prop["preview"]
    assert "Roster 105" in prop["preview"]
    assert "Rival Star" in prop["preview"]
    assert "gives 1, receives 1" in prop["preview"]
    assert prop["expires_at"] == (NOW + timedelta(minutes=30)).isoformat()
    assert client.posts == []  # propose submits NOTHING


def test_propose_two_for_one_and_one_for_two_legal_with_room():
    db = FakeSupabase()
    client = FakeClient(payload=_payload(own_active=12))
    prop = _propose(db, client, give_player_ids=[GIVE_ID, GIVE2_ID],
                    receive_player_ids=[CP_ID])
    assert prop["status"] == "pending"
    assert "gives 2, receives 1" in prop["preview"]

    db2 = FakeSupabase()
    client2 = FakeClient(payload=_payload(own_active=12))
    prop2 = _propose(db2, client2, give_player_ids=[GIVE_ID],
                     receive_player_ids=[CP_ID, CP2_ID])
    assert prop2["status"] == "pending"
    assert "gives 1, receives 2" in prop2["preview"]


def test_propose_no_deadline_setting_still_valid():
    db = FakeSupabase()
    client = FakeClient(payload=_payload(deadline_ms=None))
    prop = _propose(db, client)
    assert prop["status"] == "pending"


# --- propose: validation ---------------------------------------------------------


def test_propose_self_trade_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(trades.TradeError, match="your own team"):
        _propose(db, client, counterparty_team_id=OWN_TEAM)
    assert db._store == []


def test_propose_unknown_counterparty_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(trades.TradeError, match="not in this league"):
        _propose(db, client, counterparty_team_id=99)


def test_propose_give_not_owned_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(trades.TradeError, match="not on your roster"):
        _propose(db, client, give_player_ids=[CP_ID],
                 receive_player_ids=[CP2_ID])  # theirs, not ours
    with pytest.raises(trades.TradeError, match="not on your roster"):
        _propose(db, client, give_player_ids=[424242])


def test_propose_receive_not_on_counterparty_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(trades.TradeError, match="not on team 8's roster"):
        _propose(db, client, give_player_ids=[GIVE2_ID],
                 receive_player_ids=[GIVE_ID])  # ours, not theirs
    with pytest.raises(trades.TradeError, match="not on team 8's roster"):
        _propose(db, client, receive_player_ids=[424242])


def test_propose_bad_player_lists_rejected():
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(trades.TradeError, match="non-empty"):
        _propose(db, client, give_player_ids=[])
    with pytest.raises(trades.TradeError, match="same player twice"):
        _propose(db, client, give_player_ids=[GIVE_ID, GIVE_ID])
    with pytest.raises(trades.TradeError, match="both given and received"):
        _propose(db, client, give_player_ids=[GIVE_ID],
                 receive_player_ids=[GIVE_ID])


def test_propose_own_roster_overflow_rejected():
    # Own team is at the active cap: net +1 (give 1, receive 2) is illegal.
    db, client = FakeSupabase(), FakeClient()
    with pytest.raises(trades.TradeError, match="your roster would exceed"):
        _propose(db, client, give_player_ids=[GIVE_ID],
                 receive_player_ids=[CP_ID, CP2_ID])


def test_propose_counterparty_roster_overflow_rejected():
    # Counterparty is full: net +1 for them (we give 2, receive 1) is illegal.
    db = FakeSupabase()
    client = FakeClient(payload=_payload(cp_full=True))
    with pytest.raises(trades.TradeError, match="team 8's roster would exceed"):
        _propose(db, client, give_player_ids=[GIVE_ID, GIVE2_ID],
                 receive_player_ids=[CP_ID])


def test_propose_ir_accounting():
    db, client = FakeSupabase(), FakeClient()
    # Giving the IR player frees NO active slot: at the active cap,
    # receiving an active player for him still overflows.
    with pytest.raises(trades.TradeError, match="your roster would exceed"):
        _propose(db, client, give_player_ids=[OWN_IR_ID],
                 receive_player_ids=[CP_ID])
    # A size-neutral active swap at the cap is legal.
    prop = _propose(db, client, give_player_ids=[GIVE_ID],
                    receive_player_ids=[CP_ID])
    assert prop["status"] == "pending"


def test_propose_past_trade_deadline_rejected():
    db = FakeSupabase()
    client = FakeClient(payload=_payload(deadline_ms=PAST_DEADLINE_MS))
    with pytest.raises(trades.TradeError, match="trade deadline has passed"):
        _propose(db, client)
    assert db._store == []


# --- approve ---------------------------------------------------------------------


def test_approve_submits_one_trade_transaction():
    db, client = FakeSupabase(), FakeClient()
    prop = _propose(db, client)
    result = trades.approve_trade(db, ACCOUNT, client, prop["id"], now=NOW)
    assert result["status"] == "offered"
    assert result["espn_transaction_id"] == "txn-trade-1"
    assert result["espn_transaction"]["type"] == "TRADE"
    assert result["executed_at"] == NOW.isoformat()
    assert len(client.posts) == 1
    post = client.posts[0]
    assert post["team_id"] == OWN_TEAM
    assert post["counterparty_team_id"] == CP_TEAM
    assert post["scoring_period_id"] == 11
    assert post["give_player_ids"] == [GIVE_ID]
    assert post["receive_player_ids"] == [CP_ID]
    assert db._store[0]["status"] == "offered"


def test_approve_two_for_one_passes_both_give_ids():
    db = FakeSupabase()
    client = FakeClient(payload=_payload(own_active=12))
    prop = _propose(db, client, give_player_ids=[GIVE_ID, GIVE2_ID],
                    receive_player_ids=[CP_ID])
    result = trades.approve_trade(db, ACCOUNT, client, prop["id"], now=NOW)
    assert result["status"] == "offered"
    assert client.posts[0]["give_player_ids"] == [GIVE_ID, GIVE2_ID]
    assert client.posts[0]["receive_player_ids"] == [CP_ID]


def test_double_approve_rejected_no_second_submit():
    db, client = FakeSupabase(), FakeClient()
    prop = _propose(db, client)
    trades.approve_trade(db, ACCOUNT, client, prop["id"], now=NOW)
    with pytest.raises(trades.TradeStateError, match="not pending"):
        trades.approve_trade(db, ACCOUNT, client, prop["id"], now=NOW)
    assert len(client.posts) == 1


def test_expired_proposal_rejected_and_marked():
    db, client = FakeSupabase(), FakeClient()
    prop = _propose(db, client)
    with pytest.raises(trades.TradeStateError, match="expired"):
        trades.approve_trade(
            db, ACCOUNT, client, prop["id"],
            now=NOW + timedelta(minutes=31),
        )
    assert db._store[0]["status"] == "expired"
    assert client.posts == []


def test_approve_submit_failure_recorded_as_failed():
    db, client = FakeSupabase(), FakeClient()
    client.post_error = EspnError("ESPN exploded", status=500)
    prop = _propose(db, client)
    result = trades.approve_trade(db, ACCOUNT, client, prop["id"], now=NOW)
    assert result["status"] == "failed"
    assert "ESPN exploded" in result["error"]
    assert db._store[0]["status"] == "failed"


def test_approve_espn_rejection_recorded_as_failed():
    db, client = FakeSupabase(), FakeClient()
    client.post_response = {"id": "txn-x", "status": "FAILED",
                            "error": "INVALIDROSTER"}
    prop = _propose(db, client)
    result = trades.approve_trade(db, ACCOUNT, client, prop["id"], now=NOW)
    assert result["status"] == "failed"
    assert "INVALIDROSTER" in result["error"]


def test_approve_stale_receive_fails_closed():
    db, client = FakeSupabase(), FakeClient()
    prop = _propose(db, client)
    # The receive target leaves the counterparty's roster after proposal.
    entries = client.payload["teams"][1]["roster"]["entries"]
    entries[:] = [e for e in entries if e["playerId"] != CP_ID]
    with pytest.raises(trades.TradeStateError, match="no longer valid"):
        trades.approve_trade(db, ACCOUNT, client, prop["id"], now=NOW)
    assert client.posts == []
    assert db._store[0]["status"] == "failed"


def test_approve_stale_give_fails_closed():
    db, client = FakeSupabase(), FakeClient()
    prop = _propose(db, client)
    entries = client.payload["teams"][0]["roster"]["entries"]
    entries[:] = [e for e in entries if e["playerId"] != GIVE_ID]
    with pytest.raises(trades.TradeStateError, match="no longer valid"):
        trades.approve_trade(db, ACCOUNT, client, prop["id"], now=NOW)
    assert client.posts == []
    assert db._store[0]["status"] == "failed"


def test_approve_deadline_passing_fails_closed():
    db = FakeSupabase()
    soon_ms = int(
        (NOW + timedelta(minutes=15)).timestamp() * 1000
    )
    client = FakeClient(payload=_payload(deadline_ms=soon_ms))
    prop = _propose(db, client)
    with pytest.raises(trades.TradeStateError, match="no longer valid"):
        trades.approve_trade(
            db, ACCOUNT, client, prop["id"],
            now=NOW + timedelta(minutes=20),
        )
    assert client.posts == []
    assert db._store[0]["status"] == "failed"


def test_tenant_isolation():
    db, client = FakeSupabase(), FakeClient()
    prop = _propose(db, client)
    assert trades.get_proposal(db, "acc-2", prop["id"]) is None
    assert trades.list_proposals(db, "acc-2")["count"] == 0
    assert trades.list_proposals(db, "acc-1", status="pending")["count"] == 1
    assert trades.list_proposals(db, "acc-1", status="offered")["count"] == 0
    with pytest.raises(trades.TradeNotFound):
        trades.approve_trade(db, OTHER_ACCOUNT, client, prop["id"], now=NOW)
    assert client.posts == []
    assert trades.get_proposal(db, "acc-1", prop["id"])["id"] == prop["id"]


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


def test_post_trade_transaction_wire_shape(monkeypatch):
    monkeypatch.setattr(espn_client, "MIN_GAP_S", 0)
    requests = []

    def fake_urlopen(req, timeout=None):
        requests.append(req)
        return _FakeHTTPResponse({"id": "txn-9", "status": "PENDING"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    client = EspnClient("s2", SWID, 999, 2027)
    out = client.post_trade_transaction(
        member_id=SWID,
        team_id=OWN_TEAM,
        counterparty_team_id=CP_TEAM,
        scoring_period_id=11,
        give_player_ids=[GIVE_ID, GIVE2_ID],
        receive_player_ids=[CP_ID],
    )
    assert out["status"] == "PENDING"
    assert requests[0].full_url == client.transactions_url()
    body = json.loads(requests[0].data.decode("utf-8"))
    assert body["type"] == "TRADE"
    assert body["teamId"] == OWN_TEAM
    assert body["memberId"] == SWID
    assert body["scoringPeriodId"] == 11
    assert body["isLeagueManager"] is False
    assert "bidAmount" not in body
    # One TRADE item per player, each in the direction he moves — the
    # item shape the mTransactions2 read payload reports for an
    # executed trade (see the t-trade fixture in test_espn_logic.py).
    assert body["items"] == [
        {"playerId": GIVE_ID, "type": "TRADE",
         "fromTeamId": OWN_TEAM, "toTeamId": CP_TEAM},
        {"playerId": GIVE2_ID, "type": "TRADE",
         "fromTeamId": OWN_TEAM, "toTeamId": CP_TEAM},
        {"playerId": CP_ID, "type": "TRADE",
         "fromTeamId": CP_TEAM, "toTeamId": OWN_TEAM},
    ]

    with pytest.raises(EspnError, match="no players"):
        client.post_trade_transaction(
            member_id=SWID,
            team_id=OWN_TEAM,
            counterparty_team_id=CP_TEAM,
            scoring_period_id=11,
            give_player_ids=[],
            receive_player_ids=[],
        )


# --- HTTP routes -------------------------------------------------------------------


@pytest.fixture()
def trades_app(monkeypatch):
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


def test_trade_routes_round_trip(trades_app):
    application, client, _db = trades_app
    http = TestClient(application)

    r = http.post(
        "/espn/trades",
        json={"counterparty_team_id": CP_TEAM,
              "give_player_ids": [GIVE_ID],
              "receive_player_ids": [CP_ID]},
        headers=_auth(),
    )
    assert r.status_code == 200
    prop = r.json()
    assert prop["status"] == "pending"
    assert "Rival Star" in prop["preview"]
    assert client.posts == []

    r = http.post(f"/espn/trades/{prop['id']}/approve", headers=_auth())
    assert r.status_code == 200
    assert r.json()["status"] == "offered"
    assert len(client.posts) == 1

    # Second approval is a 409, not a second submission.
    r = http.post(f"/espn/trades/{prop['id']}/approve", headers=_auth())
    assert r.status_code == 409
    assert len(client.posts) == 1

    r = http.get("/espn/trades", headers=_auth())
    assert r.status_code == 200
    assert r.json()["count"] == 1

    r = http.get(f"/espn/trades/{prop['id']}", headers=_auth())
    assert r.status_code == 200
    assert r.json()["status"] == "offered"


def test_trade_routes_errors(trades_app):
    application, _client, _db = trades_app
    http = TestClient(application)

    # No auth.
    r = http.post(
        "/espn/trades",
        json={"counterparty_team_id": CP_TEAM,
              "give_player_ids": [GIVE_ID],
              "receive_player_ids": [CP_ID]},
    )
    assert r.status_code == 401

    # Self-trade is a 400.
    r = http.post(
        "/espn/trades",
        json={"counterparty_team_id": OWN_TEAM,
              "give_player_ids": [GIVE_ID],
              "receive_player_ids": [CP_ID]},
        headers=_auth(),
    )
    assert r.status_code == 400

    # Give player not owned is a 400.
    r = http.post(
        "/espn/trades",
        json={"counterparty_team_id": CP_TEAM,
              "give_player_ids": [CP_ID],
              "receive_player_ids": [CP2_ID]},
        headers=_auth(),
    )
    assert r.status_code == 400

    # Unknown proposal ids are 404 on read and approve.
    r = http.get("/espn/trades/prop-99", headers=_auth())
    assert r.status_code == 404
    r = http.post("/espn/trades/prop-99/approve", headers=_auth())
    assert r.status_code == 404
