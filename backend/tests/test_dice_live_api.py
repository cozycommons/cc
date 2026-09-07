import pytest
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import dice.routes as routes
from dice.routes import router
from dice.schemas import LiveCreateRequest, LiveCommandRequest
from dice.live_types import DiceLiveError, DiceLiveErrorCode
from dice.prediction_model import ACCEPTED_MODEL, predict_features
from runtime_policy import initialize_runtime_policy


TOKEN = "live-token"
USER = "10000000-0000-0000-0000-000000000001"


def _prediction_snapshot(captured_at, prior1=0.65, prior2=0.35):
    return {
        "model_id": ACCEPTED_MODEL.model_id,
        "model_version": ACCEPTED_MODEL.model_version,
        "dataset_version": ACCEPTED_MODEL.dataset_version,
        "captured_at": captured_at,
        "team1_prior_win_rate": prior1,
        "team2_prior_win_rate": prior2,
        "team1_probability": predict_features(ACCEPTED_MODEL, prior1 - prior2),
    }


class _Auth:
    def get_user(self, token):
        if token != TOKEN:
            raise ValueError("bad token")
        user = type("User", (), {"id": USER, "email": "referee@example.com", "user_metadata": {}})()
        return type("Response", (), {"user": user})()


class _Supabase:
    auth = _Auth()

    def table(self, _name):
        return self

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def in_(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        return type("Response", (), {"data": []})()


def _client(monkeypatch, enabled=False):
    app = FastAPI()
    app.include_router(router, prefix="/dice")
    app.state.supabase = _Supabase()
    app.state.supabase_admin = _Supabase()
    app.state.runtime_policy = initialize_runtime_policy({}, lambda: None)
    monkeypatch.setattr(routes, "get_profile", lambda *_args: object())
    monkeypatch.setattr(routes, "is_feature_enabled", lambda *_args: enabled)
    return TestClient(app)


def test_only_the_six_live_endpoints_are_exposed():
    paths = {(route.path, tuple(sorted(route.methods or ()))) for route in router.routes if "/live/" in route.path}
    assert paths == {
        ("/live/games", ("GET",)), ("/live/games", ("POST",)),
        ("/live/games/{match_id}", ("GET",)),
        ("/live/games/{match_id}/prediction", ("GET",)),
        ("/live/games/{match_id}/pulse", ("GET",)),
        ("/live/games/{match_id}/referees/me", ("PUT",)),
        ("/live/games/{match_id}/referees/me", ("DELETE",)),
        ("/live/games/{match_id}/commands", ("POST",)),
    }


def test_prediction_is_derived_from_canonical_snapshot(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {
        "id": "m1", "version": 4,
        "projection": {"score": [7, 3], "status": "active", "coverage": "complete", "observations": 2, "stats": {}},
        "rules_snapshot": {
            "contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
            "target_score": 11, "win_by": 2,
            "call_policy": {
                "low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
                "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
                "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss",
            },
        },
    })
    response = client.get("/dice/live/games/m1/prediction", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["match_version"] == 4
    assert payload["team1_win_probability"] > 0.5
    assert payload["pregame_source"] == "neutral_fallback"
    assert payload["pregame_model_id"] == "neutral"


def test_prediction_uses_independent_creation_snapshot_when_present(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    captured_at = datetime.now(timezone.utc).isoformat()
    row = {
        "id": "m1", "version": 4,
        "created_at": captured_at,
        "projection": {"score": [0, 0], "status": "active", "coverage": "complete", "observations": 0, "stats": {}},
        "rules_snapshot": {
            "contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
            "target_score": 11, "win_by": 2,
            "call_policy": {
                "low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
                "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
                "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss",
            },
        },
        "team_order": ["blue", "clay"],
        "prediction_snapshot": _prediction_snapshot(captured_at),
    }
    monkeypatch.setattr(routes, "_live_row", lambda *_args: row)
    payload = client.get("/dice/live/games/m1/prediction", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert payload["pregame_source"] == "independent_model_snapshot"
    assert payload["pregame_model_id"] == "dice-pregame-logistic"
    assert payload["input_timestamp"] is not None
    assert payload["team1_win_probability"] == pytest.approx(
        _prediction_snapshot(captured_at)["team1_probability"]
    )


def test_prediction_rejects_a_probability_that_does_not_match_its_saved_inputs(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    captured_at = datetime.now(timezone.utc).isoformat()
    snapshot = _prediction_snapshot(captured_at)
    snapshot["team1_probability"] = 0.99
    row = {
        "id": "m1", "version": 1, "created_at": captured_at,
        "projection": {"score": [0, 0], "status": "active", "coverage": "complete", "observations": 0, "stats": {}},
        "rules_snapshot": {"contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
            "target_score": 11, "win_by": 2, "call_policy": {"low_call_deadline": "before_surface_contact",
            "low_call_exceptions": [], "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
            "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss"}},
        "prediction_snapshot": snapshot,
    }
    monkeypatch.setattr(routes, "_live_row", lambda *_args: row)
    payload = client.get("/dice/live/games/m1/prediction", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert payload["pregame_source"] == "neutral_fallback"
    assert payload["team1_win_probability"] == 0.5


def test_prediction_rejects_stale_creation_snapshot_to_neutral(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    created_at = datetime.now(timezone.utc)
    row = {
        "id": "m1", "version": 1, "created_at": created_at.isoformat(),
        "projection": {"score": [0, 0], "status": "active", "coverage": "complete", "observations": 0, "stats": {}},
        "rules_snapshot": {"contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
            "target_score": 11, "win_by": 2, "call_policy": {"low_call_deadline": "before_surface_contact",
            "low_call_exceptions": [], "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
            "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss"}},
        "prediction_snapshot": _prediction_snapshot((created_at - timedelta(hours=1)).isoformat()),
    }
    monkeypatch.setattr(routes, "_live_row", lambda *_args: row)
    payload = client.get("/dice/live/games/m1/prediction", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert payload["pregame_source"] == "neutral_fallback"
    assert payload["team1_win_probability"] == 0.5


def test_prediction_rejects_unknown_dataset_contract(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": "m1", "version": 1, "created_at": now,
        "projection": {"score": [0, 0], "status": "active", "coverage": "complete", "observations": 0, "stats": {}},
        "rules_snapshot": {"contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
            "target_score": 11, "win_by": 2, "call_policy": {"low_call_deadline": "before_surface_contact",
            "low_call_exceptions": [], "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
            "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss"}},
        "prediction_snapshot": {"model_id": "dice-pregame-logistic", "model_version": "1.0.0",
            "dataset_version": "future", "captured_at": now, "team1_probability": 0.9},
    }
    monkeypatch.setattr(routes, "_live_row", lambda *_args: row)
    payload = client.get("/dice/live/games/m1/prediction", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert payload["pregame_source"] == "neutral_fallback"


def test_legacy_active_match_keeps_its_immutable_elo_prior(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": "m1", "version": 1, "created_at": now, "team_order": ["blue", "clay"],
        "projection": {"score": [0, 0], "status": "active", "coverage": "complete", "observations": 0, "stats": {}},
        "rules_snapshot": {"contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
            "target_score": 11, "win_by": 2, "call_policy": {"low_call_deadline": "before_surface_contact",
            "low_call_exceptions": [], "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
            "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss"}},
        "rating_snapshot": {"blue": [{"user_id": "a", "rating": 1700, "system_version": "1.0.0"}],
                            "clay": [{"user_id": "b", "rating": 1500, "system_version": "1.0.0"}]},
    }
    monkeypatch.setattr(routes, "_live_row", lambda *_args: row)
    payload = client.get("/dice/live/games/m1/prediction", headers={"Authorization": f"Bearer {TOKEN}"}).json()
    assert payload["pregame_source"] == "legacy_elo_snapshot"
    assert payload["team1_win_probability"] > 0.5


def test_live_pulse_exposes_server_derived_story_and_personal_pick(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    row = {
        "id": "m1", "version": 0, "team_order": ["blue", "clay"],
        "teams": {"blue": ["a", "b"], "clay": ["c", "d"]},
        "rules_snapshot": {
            "contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
            "target_score": 11, "win_by": 2,
            "call_policy": {
                "low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
                "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
                "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss",
            },
        },
        "rating_snapshot": {},
    }
    virtual = routes.LivePulseVirtualOut(
        tournament_id="30000000-0000-0000-0000-000000000001",
        market=routes.VirtualMarketOut(
            id=4, tournament_id="30000000-0000-0000-0000-000000000001",
            live_match_id="m1", kind="match_winner", status="open",
            model_id="elo-score-composition", model_version="1.0.0", match_version=0,
            selections={"blue": {"probability_millionths": 600000}, "clay": {"probability_millionths": 400000}},
        ),
        pick=routes.VirtualPickOut(
            id=8, tournament_id="30000000-0000-0000-0000-000000000001",
            market_id=4, user_id=USER, client_pick_id="mobile-1", selection="blue",
            stake=200, potential_return=333, locked_probability_millionths=600000,
            quote_model_id="elo-score-composition", quote_model_version="1.0.0",
            quote_match_version=0, status="open",
        ),
        balance=800, rank=2, field_size=5,
    )
    monkeypatch.setattr(routes, "_live_row", lambda *_args: row)
    monkeypatch.setattr(routes, "_live_events", lambda *_args: [])
    monkeypatch.setattr(routes, "_live_pulse_virtual", lambda *_args: virtual)

    response = client.get("/dice/live/games/m1/pulse", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["points"] == [{
        "match_version": 0, "score": [0, 0], "team1_win_probability": 0.5,
            "team2_win_probability": 0.5, "swing": 0.0, "kind": "start",
            "outcome": None, "thrower_id": None, "fifa_finish": None, "fifa_actor_id": None,
        }]
    assert payload["virtual"]["pick"]["selection"] == "blue"
    assert payload["virtual"]["balance"] == 800
    assert payload["virtual"]["rank"] == 2


def test_live_pulse_accepts_result_reopen_story_point(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    row = {
        "id": "m1", "version": 3, "team_order": ["blue", "clay"],
        "teams": {"blue": ["a", "b"], "clay": ["c", "d"]},
        "rules_snapshot": {
            "contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
            "target_score": 11, "win_by": 2,
            "call_policy": {
                "low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
                "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
                "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss",
            },
        },
        "rating_snapshot": {},
    }
    common = {
        "match_id": "m1", "recorded_by": "ref", "recorded_at": "2026-08-24T12:00:00Z",
        "match_elapsed_ms": 0,
    }
    events = [
        {**common, "id": "finish", "match_version": 1, "sequence": 1,
         "client_command_id": "c1", "command_index": 0, "kind": "completion",
         "score": [1, 0], "coverage": "partial", "coverage_after": None,
         "replacement_for": None, "replay_resolution_for": None, "replay_disposition": None,
         "termination_reason": "other"},
        {**common, "id": "reopen", "match_version": 2, "sequence": 2,
         "client_command_id": "c2", "command_index": 0, "kind": "correction",
         "target_event_id": "finish", "reason": "mistaken_entry"},
        {**common, "id": "score", "match_version": 2, "sequence": 3,
         "client_command_id": "c2", "command_index": 1, "kind": "score_checkpoint",
         "score": [0, 1], "coverage": "partial", "coverage_after": None,
         "replacement_for": "finish", "replay_resolution_for": None, "replay_disposition": None},
    ]
    monkeypatch.setattr(routes, "_live_row", lambda *_args: row)
    monkeypatch.setattr(routes, "_live_events", lambda *_args: events)
    monkeypatch.setattr(routes, "_live_pulse_virtual", lambda *_args: None)

    response = client.get("/dice/live/games/m1/pulse", headers={"Authorization": f"Bearer {TOKEN}"})

    assert response.status_code == 200
    assert response.json()["points"][-1]["kind"] == "reopen"


def test_create_schema_is_strict_2v2_and_commands_are_strict():
    with pytest.raises(ValidationError):
        LiveCreateRequest(team_order=["a", "b"], teams={"a": ["1"], "b": ["2"]}, rules_snapshot={})
    with pytest.raises(ValidationError):
        LiveCommandRequest(kind="record_throw", client_command_id="c", expected_version=0, thrower_id="p", outcome="point", extra="nope")


def test_virtual_bankroll_and_pick_are_tournament_scoped_and_server_quoted(monkeypatch):
    class VirtualAdmin(_Supabase):
        calls = []

        def rpc(self, name, params):
            self.calls.append((name, params))
            self.rpc_name = name
            self.params = params
            return self

        def execute(self):
            if self.rpc_name == "dice_virtual_open_bankroll":
                data = 1000
            else:
                data = {
                    "id": 8, "tournament_id": self.params["p_tournament_id"],
                    "market_id": self.params["p_market_id"], "user_id": self.params["p_user_id"],
                    "client_pick_id": self.params["p_client_pick_id"], "selection": self.params["p_selection"],
                    "stake": self.params["p_stake"], "potential_return": 500,
                    "locked_probability_millionths": 600000, "quote_model_id": "elo-score-composition",
                    "quote_model_version": "1.0.0", "quote_match_version": 0, "status": "open",
                }
            return type("Response", (), {"data": data})()

    client = _client(monkeypatch, enabled=True)
    admin = VirtualAdmin()
    client.app.state.supabase_admin = admin
    tournament = "30000000-0000-0000-0000-000000000001"

    bankroll = client.post(f"/dice/virtual/tournaments/{tournament}/bankroll", headers={"Authorization": f"Bearer {TOKEN}"})
    pick = client.post(
        f"/dice/virtual/tournaments/{tournament}/markets/4/picks",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"client_pick_id": "mobile-1", "selection": "blue", "stake": 300},
    )

    assert bankroll.json() == {"tournament_id": tournament, "balance": 1000}
    assert pick.status_code == 200
    assert pick.json()["potential_return"] == 500
    assert admin.calls[1] == ("dice_virtual_place_pick", {
        "p_tournament_id": tournament, "p_market_id": 4, "p_user_id": USER,
        "p_client_pick_id": "mobile-1", "p_selection": "blue", "p_stake": 300,
    })


def test_virtual_portfolio_returns_only_callers_tournament_picks(monkeypatch):
    class PickAdmin(_Supabase):
        filters = []

        def eq(self, column, value):
            self.filters.append((column, value))
            return self

        def execute(self):
            return type("Response", (), {"data": [{
                "id": 8, "tournament_id": tournament, "market_id": 4, "user_id": USER,
                "client_pick_id": "mobile-1", "selection": "blue", "stake": 300,
                "potential_return": 500, "locked_probability_millionths": 600000,
                "quote_model_id": "elo-score-composition", "quote_model_version": "1.0.0",
                "quote_match_version": 0, "status": "won", "settled_at": "2026-08-16T12:00:00Z",
            }]})()

    tournament = "30000000-0000-0000-0000-000000000001"
    client = _client(monkeypatch, enabled=True)
    admin = PickAdmin()
    client.app.state.supabase_admin = admin

    response = client.get(
        f"/dice/virtual/tournaments/{tournament}/picks",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == "won"
    assert admin.filters == [("tournament_id", tournament), ("user_id", USER)]


def test_virtual_leaderboard_is_beta_gated_and_returns_authoritative_ranking(monkeypatch):
    tournament = "30000000-0000-0000-0000-000000000001"
    ranking = [{"rank": 1, "user_id": USER, "display_name": "Referee", "balance": 1200}]
    calls = []
    monkeypatch.setattr(
        routes,
        "tournament_virtual_leaderboard",
        lambda client, tournament_id: calls.append((client, tournament_id)) or ranking,
    )

    disabled = _client(monkeypatch, enabled=False).get(
        f"/dice/virtual/tournaments/{tournament}/leaderboard",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    client = _client(monkeypatch, enabled=True)
    response = client.get(
        f"/dice/virtual/tournaments/{tournament}/leaderboard",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert disabled.status_code == 403
    assert response.status_code == 200
    assert response.json() == ranking
    assert calls == [(client.app.state.supabase_admin, tournament)]


def test_virtual_market_quote_comes_from_saved_ratings_not_client_input(monkeypatch):
    class MarketAdmin(_Supabase):
        inserted = None
        table_name = None

        def table(self, name):
            self.table_name = name
            return self

        def insert(self, payload):
            self.inserted = payload
            return self

        def execute(self):
            if self.table_name == "dice_tournament_enrollments":
                data = [{"user_id": user_id} for user_id in (USER, "p1", "p2", "p3", "p4")]
            else:
                data = [{"id": 4, "status": "open", **self.inserted}]
            return type("Response", (), {"data": data})()

    client = _client(monkeypatch, enabled=True)
    admin = MarketAdmin()
    client.app.state.supabase_admin = admin
    captured_at = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {
        "id": "10000000-0000-0000-0000-000000000099", "version": 0, "status": "active",
        "created_at": captured_at,
        "team_order": ["blue", "clay"], "teams": {"blue": ["p1", "p2"], "clay": ["p3", "p4"]},
        "prediction_snapshot": _prediction_snapshot(captured_at, 0.7, 0.3),
    })
    tournament = "30000000-0000-0000-0000-000000000001"

    response = client.post(
        f"/dice/virtual/tournaments/{tournament}/markets",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"live_match_id": "10000000-0000-0000-0000-000000000099"},
    )

    assert response.status_code == 200, response.text
    probabilities = [item["probability_millionths"] for item in response.json()["selections"].values()]
    assert sum(probabilities) == 1_000_000
    assert response.json()["selections"]["blue"]["probability_millionths"] > 500_000


def test_live_output_adds_registered_roster_display_names():
    class Admin(_Supabase):
        current_table = ""

        def table(self, name):
            self.current_table = name
            return self

        def execute(self):
            data = {
                "dice_live_referees": [],
                "dice_profiles": [
                    {"user_id": "p1", "display_name": "Alice", "avatar_url": "https://img.test/alice.jpg"},
                    {"user_id": "p2", "display_name": "Bea", "avatar_url": None},
                    {"user_id": "p3", "display_name": "Cam", "avatar_url": "https://img.test/cam.jpg"},
                    {"user_id": "p4", "display_name": "Dev", "avatar_url": None},
                ],
            }[self.current_table]
            return type("Response", (), {"data": data})()

    request = type("Request", (), {"app": type("App", (), {"state": type("State", (), {"supabase_admin": Admin()})()})()})()
    created_at = datetime.now(timezone.utc)
    output = routes._live_output(request, {
        "id": "m1", "created_by": USER, "team_order": ["blue", "clay"],
        "created_at": created_at,
        "teams": {"blue": ["p1", "p2"], "clay": ["p3", "p4"]},
        "rules_snapshot": {}, "version": 0, "status": "active", "score": [0, 0],
        "detail_coverage": "complete", "projection": {},
    })

    assert output.player_names == {"p1": "Alice", "p2": "Bea", "p3": "Cam", "p4": "Dev"}
    assert output.player_avatars == {"p1": "https://img.test/alice.jpg", "p3": "https://img.test/cam.jpg"}
    assert output.created_at == created_at
    assert output.player_stats["p1"] == {
        "elo_rating": 0, "games_played": 0, "wins": 0,
        "losses": 0, "sinks": 0, "self_sinks": 0,
    }


def test_live_creation_rejects_roster_members_without_profiles(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "create_live_match", lambda *_args: (_ for _ in ()).throw(
        DiceLiveError(DiceLiveErrorCode.INVALID_ROSTER, "all live-match roster members must have registered profiles")
    ))
    response = client.post(
        "/dice/live/games",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={
            "team_order": ["team1", "team2"],
            "teams": {"team1": ["p1", "p2"], "team2": ["p3", "p4"]},
            "rules_snapshot": {},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "dice_live.invalid_roster",
        "message": "all live-match roster members must have registered profiles",
    }


def test_live_creation_rejects_invalid_rules_before_persistence_and_lobby_visibility(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    payload = {
        "team_order": ["team1", "team2"],
        "teams": {"team1": ["p1", "p2"], "team2": ["p3", "p4"]},
        "rules_snapshot": {},
    }

    for _ in range(2):
        response = client.post("/dice/live/games", headers={"Authorization": f"Bearer {TOKEN}"}, json=payload)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "dice_live.invalid_rules"

    lobby = client.get("/dice/live/games", headers={"Authorization": f"Bearer {TOKEN}"})
    assert lobby.status_code == 200
    assert lobby.json() == []


def test_authentication_and_effective_access_fail_closed(monkeypatch):
    client = _client(monkeypatch, enabled=False)
    assert client.get("/dice/live/games").status_code == 401
    response = client.get("/dice/live/games", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 403 and response.json()["detail"] == "dice_live.feature_disabled"


def test_command_validation_uses_stable_domain_error_with_field_identity(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {})
    response = client.post(
        "/dice/live/games/m1/commands",
        headers={"Authorization": f"Bearer {TOKEN}"},
        json={"kind": "reopen", "client_command_id": "c", "expected_version": 0, "score": [1, 0]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "dice_live.invalid_command"
    assert "score" in response.json()["detail"]["message"]


def test_replay_target_is_irrelevant_to_non_record_commands(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {})
    response = client.post("/dice/live/games/m1/commands", headers={"Authorization": f"Bearer {TOKEN}"}, json={
        "kind": "reopen", "client_command_id": "c", "expected_version": 0,
        "replay_of": "decision-1",
    })

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "dice_live.invalid_command",
        "message": "field 'replay_of' is not allowed for reopen",
    }


def test_malformed_replay_target_is_a_stable_domain_error(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {})
    response = client.post("/dice/live/games/m1/commands", headers={"Authorization": f"Bearer {TOKEN}"}, json={
        "kind": "record_throw", "client_command_id": "c", "expected_version": 0,
        "thrower_id": "p1", "outcome": "point", "replay_of": 123,
    })

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "dice_live.invalid_replay", "message": "replay_of must be a string event ID",
        "event_id": None, "sequence": None,
    }


def test_authenticated_record_throw_passes_replay_target_to_service(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {})
    captured = {}

    def append(_client, _match_id, _user_id, command):
        captured["command"] = command
        return {"accepted_version": 1, "first_sequence": 1, "last_sequence": 1,
                "projection": {"score": [0, 0], "status": "active", "coverage": "unknown", "observations": 0, "stats": {}}}

    monkeypatch.setattr(routes, "append_command", append)
    response = client.post("/dice/live/games/m1/commands", headers={"Authorization": f"Bearer {TOKEN}"}, json={
        "kind": "record_throw", "client_command_id": "c", "expected_version": 0,
        "thrower_id": "p1", "outcome": "point", "replay_of": "decision-1",
    })

    assert response.status_code == 200
    assert captured["command"].replay_of == "decision-1"


def test_virtual_reconciliation_failure_cannot_reject_accepted_command(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {
        "team_order": ["blue", "clay"], "version": 1,
    })
    monkeypatch.setattr(routes, "get_live_result", lambda *_args: None)
    receipt = {
        "accepted_version": 1,
        "first_sequence": 1,
        "last_sequence": 1,
        "projection": {
            "score": [1, 0], "status": "active", "coverage": "complete",
            "observations": 1, "stats": {},
        },
    }
    monkeypatch.setattr(routes, "append_command", lambda *_args: receipt)
    monkeypatch.setattr(
        routes,
        "reconcile_match_winner_markets",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("market unavailable")),
    )

    response = client.post("/dice/live/games/m1/commands", headers={"Authorization": f"Bearer {TOKEN}"}, json={
        "kind": "record_throw", "client_command_id": "c", "expected_version": 0,
        "thrower_id": "p1", "outcome": "point",
    })

    assert response.status_code == 200
    assert response.json()["accepted_version"] == 1


def test_accepted_command_reconciles_market_from_saved_team_order(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {
        "team_order": ["blue", "clay"], "version": 4,
    })
    receipt = {
        "accepted_version": 4,
        "first_sequence": 4,
        "last_sequence": 4,
        "projection": {
            "score": [5, 3], "status": "completed", "coverage": "partial",
            "observations": 3, "stats": {},
        },
        "official_result": {"state": "official", "winner_team": 1},
    }
    monkeypatch.setattr(routes, "append_command", lambda *_args: receipt)
    monkeypatch.setattr(routes, "get_live_result", lambda *_args: {
        "live_result_state": "official", "winner_team": 1,
    })
    captured = []
    monkeypatch.setattr(routes, "reconcile_match_winner_markets", lambda *args: captured.append(args[1:]))

    response = client.post("/dice/live/games/m1/commands", headers={"Authorization": f"Bearer {TOKEN}"}, json={
        "kind": "finish", "client_command_id": "finish-1", "expected_version": 3,
        "coverage": "partial", "termination_reason": "other",
    })

    assert response.status_code == 200
    assert captured == [(
        "m1", ["blue", "clay"], 4,
        {"live_result_state": "official", "winner_team": 1},
    )]


@pytest.mark.parametrize(("old_receipt_result", "current_result", "current_version"), [
    (None, {"live_result_state": "official", "winner_team": 1}, 5),
    (
        {"state": "official", "winner_team": 1},
        {"live_result_state": "reopened", "winner_team": 1},
        6,
    ),
])
def test_command_retry_reconciles_current_state_not_stored_receipt(
    monkeypatch, old_receipt_result, current_result, current_version,
):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {
        "team_order": ["blue", "clay"], "version": current_version,
    })
    monkeypatch.setattr(routes, "append_command", lambda *_args: {
        "accepted_version": 1,
        "first_sequence": 1,
        "last_sequence": 1,
        "projection": {
            "score": [1, 0], "status": "active", "coverage": "complete",
            "observations": 1, "stats": {},
        },
        "official_result": old_receipt_result,
    })
    monkeypatch.setattr(routes, "get_live_result", lambda *_args: current_result)
    captured = []
    monkeypatch.setattr(routes, "reconcile_match_winner_markets", lambda *args: captured.append(args[1:]))

    response = client.post("/dice/live/games/m1/commands", headers={"Authorization": f"Bearer {TOKEN}"}, json={
        "kind": "record_throw", "client_command_id": "old-command", "expected_version": 0,
        "thrower_id": "p1", "outcome": "point",
    })

    assert response.status_code == 200
    assert captured == [(
        "m1", ["blue", "clay"], current_version, current_result,
    )]


def test_authenticated_replay_domain_error_keeps_target_identity(monkeypatch):
    client = _client(monkeypatch, enabled=True)
    monkeypatch.setattr(routes, "_live_row", lambda *_args: {})
    monkeypatch.setattr(routes, "append_command", lambda *_args: (_ for _ in ()).throw(
        DiceLiveError(DiceLiveErrorCode.INVALID_REPLAY, "replay_of target is inactive", event_id="decision-1", sequence=3)
    ))
    response = client.post("/dice/live/games/m1/commands", headers={"Authorization": f"Bearer {TOKEN}"}, json={
        "kind": "record_throw", "client_command_id": "c", "expected_version": 0,
        "thrower_id": "p1", "outcome": "point", "replay_of": "decision-1",
    })

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "dice_live.invalid_replay", "message": "replay_of target is inactive",
        "event_id": "decision-1", "sequence": 3,
    }
