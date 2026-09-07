import pytest

from dice.virtual_currency import reconcile_match_winner_markets


class FakeClient:
    def __init__(self, markets):
        self.markets = markets
        self.table_name = None
        self.filters = []
        self.update_payload = None
        self.rpc_calls = []

    def table(self, name):
        self.table_name = name
        self.filters = []
        self.update_payload = None
        return self

    def select(self, *_args):
        return self

    def update(self, payload):
        self.update_payload = payload
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def rpc(self, name, params):
        self.table_name = None
        self.rpc_calls.append((name, params))
        return self

    def execute(self):
        if self.table_name == "dice_virtual_markets":
            selected = [
                market for market in self.markets
                if all(market.get(field) == value for field, value in self.filters)
            ]
            if self.update_payload is not None:
                for market in selected:
                    market.update(self.update_payload)
            return type("Response", (), {"data": selected})()
        return type("Response", (), {"data": {}})()


def market(status="open", settled_selection=None):
    return {
        "id": 7,
        "live_match_id": "match-1",
        "kind": "match_winner",
        "status": status,
        "settled_selection": settled_selection,
        "match_version": 0,
    }


def test_first_live_command_closes_offer_without_settling_it():
    client = FakeClient([market()])

    reconcile_match_winner_markets(client, "match-1", ["blue", "clay"], 1, None)

    assert client.markets[0]["status"] == "closed"
    assert client.rpc_calls == []


def test_official_finish_and_repeated_finish_delegate_to_idempotent_settlement():
    client = FakeClient([market()])
    result = {"state": "official", "winner_team": 1}

    reconcile_match_winner_markets(client, "match-1", ["blue", "clay"], 1, result)
    reconcile_match_winner_markets(client, "match-1", ["blue", "clay"], 1, result)

    assert client.markets[0]["status"] == "closed"
    assert client.rpc_calls == [
        ("dice_virtual_settle_market", {"p_market_id": 7, "p_winner_selection": "blue"}),
        ("dice_virtual_settle_market", {"p_market_id": 7, "p_winner_selection": "blue"}),
    ]


def test_reopen_voids_prior_settlement_and_refinish_can_revise_winner():
    client = FakeClient([market(status="settled", settled_selection="blue")])

    reconcile_match_winner_markets(client, "match-1", ["blue", "clay"], 2, None)
    reconcile_match_winner_markets(
        client, "match-1", ["blue", "clay"], 3,
        {"state": "official", "winner_team": 2},
    )

    assert client.rpc_calls == [
        ("dice_virtual_settle_market", {"p_market_id": 7, "p_winner_selection": None}),
        ("dice_virtual_settle_market", {"p_market_id": 7, "p_winner_selection": "clay"}),
    ]


def test_reopened_summary_also_voids_prior_settlement():
    client = FakeClient([market(status="settled", settled_selection="blue")])

    reconcile_match_winner_markets(
        client, "match-1", ["blue", "clay"], 2,
        {"state": "reopened", "winner_team": 1},
    )

    assert client.rpc_calls == [
        ("dice_virtual_settle_market", {"p_market_id": 7, "p_winner_selection": None}),
    ]

    raw = FakeClient([market(status="settled", settled_selection="blue")])
    reconcile_match_winner_markets(
        raw, "match-1", ["blue", "clay"], 2,
        {"live_result_state": "reopened", "winner_team": 1},
    )
    assert raw.rpc_calls == [
        ("dice_virtual_settle_market", {"p_market_id": 7, "p_winner_selection": None}),
    ]


def test_repository_result_state_name_is_supported():
    client = FakeClient([market(status="closed")])

    reconcile_match_winner_markets(
        client, "match-1", ["blue", "clay"], 2,
        {"live_result_state": "official", "winner_team": 2},
    )

    assert client.rpc_calls == [
        ("dice_virtual_settle_market", {"p_market_id": 7, "p_winner_selection": "clay"}),
    ]


def test_official_draw_voids_picks_through_settlement_rpc():
    client = FakeClient([market(status="closed")])

    reconcile_match_winner_markets(
        client, "match-1", ["blue", "clay"], 2,
        {"state": "official", "winner_team": None},
    )

    assert client.rpc_calls == [
        ("dice_virtual_settle_market", {"p_market_id": 7, "p_winner_selection": None}),
    ]


def test_no_linked_market_is_a_noop_and_invalid_winner_is_not_voided():
    empty = FakeClient([])
    reconcile_match_winner_markets(empty, "match-1", ["blue", "clay"], 1, None)
    assert empty.rpc_calls == []

    unknown = FakeClient([market(status="closed")])
    with pytest.raises(ValueError, match="invalid state"):
        reconcile_match_winner_markets(
            unknown, "match-1", ["blue", "clay"], 1,
            {"winner_team": 1},
        )
    assert unknown.rpc_calls == []

    client = FakeClient([market(status="closed")])
    with pytest.raises(ValueError, match="invalid winner_team"):
        reconcile_match_winner_markets(
            client, "match-1", ["blue", "clay"], 1,
            {"state": "official", "winner_team": True},
        )
    assert client.rpc_calls == []
