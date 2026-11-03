"""Offline regressions for ambiguous writes; all data below is synthetic."""

import copy
import urllib.error
import urllib.request

import pytest

from espn import espn_client, roster_edits, trades
from espn.espn_client import EspnClient, EspnError
from tests import test_espn_roster_edits as edits_fixture
from tests import test_espn_trades as trades_fixture

ACCOUNT = edits_fixture.ACCOUNT
NOW = edits_fixture.NOW
FA = edits_fixture.FA_ID
DROP = edits_fixture.DROP_ID


class Database:
    def __init__(self):
        self.rows = {"espn_roster_edits": [], "espn_trade_proposals": []}

    def table(self, name):
        return edits_fixture.FakeTable(self.rows[name])


class RosterClient(edits_fixture.FakeClient):
    def __init__(self):
        super().__init__()
        self.reads = []
        self.fail_verification = False

    def get_league(self, views, scoring_period_id=None):
        self.reads.append(views)
        if self.posts and self.fail_verification:
            raise EspnError("read unavailable")
        payload = super().get_league(views, scoring_period_id)
        payload.setdefault("transactions", [])
        return payload


class TradeClient(trades_fixture.FakeClient):
    def __init__(self):
        super().__init__()
        self.offers = []
        self.reads = []
        self.fail_verification = False

    def get_league(self, views, scoring_period_id=None):
        self.reads.append(views)
        if self.posts and self.fail_verification:
            raise EspnError("read unavailable")
        payload = super().get_league(views, scoring_period_id)
        payload["transactions"] = copy.deepcopy(self.offers)
        return payload


def propose_edit(db, client, **kwargs):
    return edits_fixture._propose(db, client, add_player_id=FA,
                                   drop_player_id=DROP, **kwargs)


def approve_edit(db, client, edit):
    return roster_edits.approve_edit(db, ACCOUNT, client, edit["id"], now=NOW)


def propose_trade(db, client):
    return trades_fixture._propose(db, client)


def approve_trade(db, client, proposal):
    return trades.approve_trade(db, ACCOUNT, client, proposal["id"], now=NOW)


def offer(**changes):
    return {
        "id": "new-offer", "type": "TRADE", "status": "PENDING",
        "teamId": 7, "memberId": ACCOUNT["swid"],
        "items": [
            {"playerId": DROP, "type": "TRADE", "fromTeamId": 7, "toTeamId": 8},
            {"playerId": trades_fixture.CP_ID, "type": "TRADE", "fromTeamId": 8, "toTeamId": 7},
        ], **changes,
    }


@pytest.mark.parametrize("before,after", [
    (None, "WAIVERS"), ("FREEAGENT", "WAIVERS"),
    ("WAIVERS", "FREEAGENT"), ("WAIVERS", None),
    ("FREEAGENT", None), (None, "FREEAGENT"),
])
def test_changed_waiver_state_requires_repreview(before, after):
    db, client = Database(), RosterClient()
    client.pool[0]["status"] = before
    edit = propose_edit(db, client)
    client.pool[0]["status"] = after
    with pytest.raises(roster_edits.EditStateError, match="preview|propos"):
        approve_edit(db, client, edit)
    assert client.posts == []
    assert db.rows["espn_roster_edits"][0]["status"] == "failed"


@pytest.mark.parametrize("apply", [False, True])
def test_empty_roster_response_requires_reread(apply):
    db, client = Database(), RosterClient()
    client.post_response = {}
    client.apply_posts = apply
    edit = propose_edit(db, client)
    before = len(client.reads)
    result = approve_edit(db, client, edit)
    assert len(client.reads) >= before + 2
    assert result["status"] == ("executed" if apply else "unknown")
    if not apply:
        assert result["executed_at"] is None
        with pytest.raises(roster_edits.EditStateError, match="unresolved|uncertain"):
            propose_edit(db, client)
        assert len(client.posts) == 1


def test_empty_waiver_response_is_not_proof_of_claim():
    db, client = Database(), RosterClient()
    client.pool[0]["status"] = "WAIVERS"
    client.post_response = {}
    client.apply_posts = False
    result = approve_edit(db, client, propose_edit(db, client))
    assert result["status"] == "unknown"


@pytest.mark.parametrize("body", [b"", b"{}"])
def test_client_preserves_empty_body_as_unknown(monkeypatch, body):
    monkeypatch.setattr(espn_client, "MIN_GAP_S", 0)
    # Use a raw body, including the HTTP 204-style empty response.
    class Response(edits_fixture._FakeHTTPResponse):
        def read(self):
            return body
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response({}))
    client = EspnClient("synthetic", ACCOUNT["swid"], 999, 2027)
    assert client.post_roster_transaction(ACCOUNT["swid"], 7, 11,
                                         [{"action": "DROP", "playerId": DROP}]) == {}


@pytest.mark.parametrize("error", [urllib.error.URLError("connection lost"),
                                   TimeoutError("timed out"),
                                   ConnectionResetError("reset")])
def test_client_marks_transport_failure_as_uncertain(monkeypatch, error):
    monkeypatch.setattr(espn_client, "MIN_GAP_S", 0)
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(urllib.request, "urlopen", fail)
    client = EspnClient("synthetic", ACCOUNT["swid"], 999, 2027)
    with pytest.raises(EspnError) as caught:
        client.post_roster_transaction(ACCOUNT["swid"], 7, 11,
                                      [{"action": "DROP", "playerId": DROP}])
    assert getattr(caught.value, "uncertain", False)


def test_roster_network_error_reconciles_without_resubmitting():
    db, client = Database(), RosterClient()
    client.post_error = EspnError("network error")
    edit = propose_edit(db, client)
    result = approve_edit(db, client, edit)
    assert result["status"] == "uncertain"
    assert result["executed_at"] is None
    # A later read shows the complete swap; approval now only reconciles.
    entries = client.payload["teams"][0]["roster"]["entries"]
    entries[:] = [entry for entry in entries if entry["playerId"] != DROP]
    entries.append(edits_fixture._entry(FA, edits_fixture.BE,
                                       edits_fixture._player(FA, "Synthetic")))
    result = approve_edit(db, client, edit)
    assert result["status"] == "executed"
    assert len(client.posts) == 1


def test_roster_partial_swap_and_failed_read_stay_uncertain():
    db, client = Database(), RosterClient()
    client.post_response = {}
    client.apply_posts = False
    edit = propose_edit(db, client)
    client.fail_verification = True
    assert approve_edit(db, client, edit)["status"] == "unknown"
    client.fail_verification = False
    client.payload["teams"][0]["roster"]["entries"].append(
        edits_fixture._entry(FA, edits_fixture.BE, edits_fixture._player(FA, "Synthetic")))
    assert approve_edit(db, client, edit)["status"] == "unknown"
    assert len(client.posts) == 1


@pytest.mark.parametrize("mode", ["empty", "network"])
def test_ambiguous_trade_rereads_offers_and_blocks_replacement(mode):
    db, client = Database(), TradeClient()
    if mode == "empty":
        client.post_response = {}
    else:
        client.post_error = EspnError("network error")
    prop = propose_trade(db, client)
    before = len(client.reads)
    result = approve_trade(db, client, prop)
    assert len(client.reads) >= before + 2
    assert result["status"] == ("unknown" if mode == "empty" else "uncertain")
    assert result["executed_at"] is None
    with pytest.raises(trades.TradeStateError, match="unresolved|uncertain"):
        propose_trade(db, client)
    client.offers = [offer()]
    result = approve_trade(db, client, prop)
    assert result["status"] == "offered"
    assert result["espn_transaction_id"] == "new-offer"
    assert len(client.posts) == 1


@pytest.mark.parametrize("change", [{"items": []}, {"teamId": 8},
                                     {"status": "MYSTERY"}])
def test_trade_reconciliation_requires_exact_confirmed_offer(change):
    db, client = Database(), TradeClient()
    client.post_response = {}
    prop = propose_trade(db, client)
    approve_trade(db, client, prop)
    client.offers = [offer(**change)]
    assert approve_trade(db, client, prop)["status"] == "unknown"
    assert len(client.posts) == 1


def test_existing_identical_trade_does_not_confirm_new_submission():
    db, client = Database(), TradeClient()
    client.offers = [offer()]
    client.post_response = {}
    prop = propose_trade(db, client)
    assert approve_trade(db, client, prop)["status"] == "unknown"
    assert approve_trade(db, client, prop)["status"] == "unknown"


def test_uncertain_roster_blocks_trade_using_same_player_and_other_account_isolated():
    db, roster = Database(), RosterClient()
    roster.post_response = {}
    roster.apply_posts = False
    approve_edit(db, roster, propose_edit(db, roster))
    client = TradeClient()
    with pytest.raises(trades.TradeStateError, match="unresolved|uncertain"):
        propose_trade(db, client)
    # Unrelated players are allowed.
    trades_fixture._propose(db, client, give_player_ids=[trades_fixture.GIVE2_ID])
    other = {**ACCOUNT, "id": "other-account"}
    edits_fixture._propose(db, roster, account=other, add_player_id=FA, drop_player_id=DROP)


def test_uncertain_trade_blocks_roster_and_preexisting_pending_approval():
    db, roster, client = Database(), RosterClient(), TradeClient()
    edit = propose_edit(db, roster)
    client.post_response = {}
    approve_trade(db, client, propose_trade(db, client))
    with pytest.raises(roster_edits.EditStateError, match="unresolved|uncertain"):
        propose_edit(db, roster)
    with pytest.raises(roster_edits.EditStateError, match="unresolved|uncertain"):
        approve_edit(db, roster, edit)
    assert roster.posts == []


@pytest.mark.parametrize("kind", ["roster", "trade"])
@pytest.mark.parametrize("status", ["unknown", "uncertain", "executing"])
def test_unresolved_states_and_get_reread_do_not_submit_again(kind, status):
    db = Database()
    if kind == "roster":
        client = RosterClient()
        client.post_response = {}
        client.apply_posts = False
        row = propose_edit(db, client)
        approve_edit(db, client, row)
        stored = db.rows["espn_roster_edits"][0]
        getter = roster_edits.get_edit
    else:
        client = TradeClient()
        client.post_response = {}
        row = propose_trade(db, client)
        approve_trade(db, client, row)
        stored = db.rows["espn_trade_proposals"][0]
        getter = trades.get_proposal
    stored["status"] = status
    result = getter(db, ACCOUNT["id"], row["id"], account=ACCOUNT, client=client)
    assert result["status"] == status
    assert len(client.posts) == 1
    with pytest.raises((roster_edits.EditStateError, trades.TradeStateError), match="unresolved"):
        (propose_edit if kind == "roster" else propose_trade)(db, client)


def test_roster_next_period_confirms_delayed_swap_on_get(monkeypatch):
    db, client = Database(), RosterClient()
    client.post_response = {}
    client.apply_posts = False
    row = propose_edit(db, client)
    approve_edit(db, client, row)
    read = client.get_league
    periods = []
    def delayed(views, scoring_period_id=None):
        payload = read(views, scoring_period_id)
        periods.append(scoring_period_id)
        if scoring_period_id == 12:
            entries = payload["teams"][0]["roster"]["entries"]
            entries[:] = [e for e in entries if e["playerId"] != DROP]
            entries.append(edits_fixture._entry(FA, edits_fixture.BE,
                                                edits_fixture._player(FA, "Synthetic")))
        return payload
    monkeypatch.setattr(client, "get_league", delayed)
    result = roster_edits.get_edit(db, ACCOUNT["id"], row["id"], account=ACCOUNT, client=client)
    assert result["status"] == "executed"
    assert periods == [11, 12]
    assert len(client.posts) == 1


def test_next_proposal_reconciles_prior_cross_type_write():
    db, client = Database(), TradeClient()
    client.post_response = {}
    prop = propose_trade(db, client)
    approve_trade(db, client, prop)
    roster = RosterClient()
    roster.payload["transactions"] = [offer()]
    result = propose_edit(db, roster)
    assert result["status"] == "pending"
    assert db.rows["espn_trade_proposals"][0]["status"] == "offered"
    assert roster.posts == []
    assert len(client.posts) == 1


@pytest.mark.parametrize("kind", ["roster", "trade"])
@pytest.mark.parametrize("status", [400, 500])
def test_only_http_rejection_is_failed(kind, status):
    db = Database()
    client = RosterClient() if kind == "roster" else TradeClient()
    client.post_error = EspnError("synthetic HTTP failure", status=status)
    row = (propose_edit if kind == "roster" else propose_trade)(db, client)
    result = (approve_edit if kind == "roster" else approve_trade)(db, client, row)
    assert result["status"] == ("failed" if status == 400 else "uncertain")


@pytest.mark.parametrize("kind", ["roster", "trade"])
def test_lost_response_after_espn_applies_write_reconciles_immediately(kind, monkeypatch):
    db = Database()
    client = RosterClient() if kind == "roster" else TradeClient()
    method = "post_roster_transaction" if kind == "roster" else "post_trade_transaction"
    post = getattr(client, method)
    def lost(**kwargs):
        post(**kwargs)
        if kind == "trade":
            client.offers = [offer()]
        raise EspnError("lost acknowledgment")
    monkeypatch.setattr(client, method, lost)
    row = (propose_edit if kind == "roster" else propose_trade)(db, client)
    result = (approve_edit if kind == "roster" else approve_trade)(db, client, row)
    assert result["status"] == ("executed" if kind == "roster" else "offered")
    assert len(client.posts) == 1


def test_unknown_status_list_filters_and_get_route(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from espn import routes
    db, client = Database(), RosterClient()
    client.post_response = {}
    client.apply_posts = False
    row = propose_edit(db, client)
    approve_edit(db, client, row)
    assert roster_edits.list_edits(db, ACCOUNT["id"], status="unknown")["count"] == 1
    assert roster_edits.list_edits(db, ACCOUNT["id"], status="uncertain")["count"] == 0
    app = FastAPI()
    app.include_router(routes.router, prefix="/espn")
    app.state.supabase = db
    monkeypatch.setattr(routes.accounts, "get_account_by_token", lambda *a: ACCOUNT)
    monkeypatch.setattr(routes.accounts, "make_client_for_account", lambda *a: client)
    http = TestClient(app)
    headers = {"Authorization": "Bearer synthetic-token"}
    response = http.get(f"/espn/roster/edits/{row['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "unknown"
    # Proposing an overlap maps to a conflict, including cross-type writes.
    response = http.post("/espn/roster/edits", headers=headers,
                         json={"add_player_id": FA, "drop_player_id": DROP})
    assert response.status_code == 409
    response = http.post("/espn/trades", headers=headers,
                         json={"counterparty_team_id": 8, "give_player_ids": [DROP],
                               "receive_player_ids": [trades_fixture.CP_ID]})
    assert response.status_code == 409
    client.post_response = None
    client.apply_posts = True
    # Simulate delayed application without another POST from our implementation.
    entries = client.payload["teams"][0]["roster"]["entries"]
    entries[:] = [e for e in entries if e["playerId"] != DROP]
    entries.append(edits_fixture._entry(FA, edits_fixture.BE,
                                       edits_fixture._player(FA, "Synthetic")))
    response = http.get(f"/espn/roster/edits/{row['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "executed"
    assert len(client.posts) == 1


def test_trade_unknown_get_route_and_list_filters(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from espn import routes
    db, client = Database(), TradeClient()
    client.post_response = {}
    row = propose_trade(db, client)
    approve_trade(db, client, row)
    assert trades.list_proposals(db, ACCOUNT["id"], status="unknown")["count"] == 1
    app = FastAPI()
    app.include_router(routes.router, prefix="/espn")
    app.state.supabase = db
    monkeypatch.setattr(routes.accounts, "get_account_by_token", lambda *a: ACCOUNT)
    monkeypatch.setattr(routes.accounts, "make_client_for_account", lambda *a: client)
    http = TestClient(app)
    headers = {"Authorization": "Bearer synthetic-token"}
    client.fail_verification = True
    response = http.get(f"/espn/trades/{row['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "unknown"
    client.fail_verification = False
    client.offers = [offer()]
    response = http.get(f"/espn/trades/{row['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "offered"
    assert len(client.posts) == 1


def test_missing_transaction_baseline_cannot_confirm_an_old_offer(monkeypatch):
    db, client = Database(), TradeClient()
    client.post_response = {}
    read = client.get_league
    def incomplete_baseline(views, scoring_period_id=None):
        if not client.posts and views == ["mTransactions2"]:
            return {}
        return read(views, scoring_period_id)
    monkeypatch.setattr(client, "get_league", incomplete_baseline)
    prop = propose_trade(db, client)
    approve_trade(db, client, prop)
    client.offers = [offer()]
    assert approve_trade(db, client, prop)["status"] == "unknown"


def test_roster_drop_only_empty_roster_is_not_confirmation():
    db, client = Database(), RosterClient()
    row = edits_fixture._propose(db, client, drop_player_id=DROP)
    client.post_response = {}
    client.apply_posts = False
    original_get = client.get_league
    def empty_after_write(views, scoring_period_id=None):
        payload = original_get(views, scoring_period_id)
        if client.posts:
            payload["teams"][0]["roster"]["entries"] = []
        return payload
    client.get_league = empty_after_write
    assert approve_edit(db, client, row)["status"] == "unknown"


@pytest.mark.parametrize("kind", ["roster", "trade"])
def test_mcp_get_by_id_reconciles_without_resubmitting(kind, monkeypatch):
    import json
    from espn import mcp_server
    db = Database()
    client = RosterClient() if kind == "roster" else TradeClient()
    client.post_response = {}
    if kind == "roster":
        client.apply_posts = False
    row = (propose_edit if kind == "roster" else propose_trade)(db, client)
    (approve_edit if kind == "roster" else approve_trade)(db, client, row)
    monkeypatch.setattr(mcp_server, "_account_and_client", lambda token: (db, ACCOUNT, client))
    if kind == "roster":
        get = lambda: json.loads(mcp_server.get_roster_edits("synthetic-token", edit_id=row["id"]))
    else:
        get = lambda: json.loads(mcp_server.get_trades("synthetic-token", proposal_id=row["id"]))
    assert get()["status"] == "unknown"
    if kind == "roster":
        entries = client.payload["teams"][0]["roster"]["entries"]
        entries[:] = [e for e in entries if e["playerId"] != DROP]
        entries.append(edits_fixture._entry(FA, edits_fixture.BE,
                                           edits_fixture._player(FA, "Synthetic")))
    else:
        client.offers = [offer()]
    assert get()["status"] == ("executed" if kind == "roster" else "offered")
    assert len(client.posts) == 1


@pytest.mark.parametrize("body", [b"not-json", b"[]"])
def test_malformed_success_acknowledgment_is_unknown_not_transport_uncertain(monkeypatch, body):
    monkeypatch.setattr(espn_client, "MIN_GAP_S", 0)
    class Response(edits_fixture._FakeHTTPResponse):
        def read(self):
            return body
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response({}))
    client = EspnClient("synthetic", ACCOUNT["swid"], 999, 2027)
    with pytest.raises(EspnError) as caught:
        client.post_roster_transaction(ACCOUNT["swid"], 7, 11,
                                      [{"action": "DROP", "playerId": DROP}])
    assert getattr(caught.value, "unknown", False)
    db, roster = Database(), RosterClient()
    roster.post_error = caught.value
    result = approve_edit(db, roster, propose_edit(db, roster))
    assert result["status"] == "unknown"
