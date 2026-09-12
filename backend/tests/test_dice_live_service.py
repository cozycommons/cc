import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from postgrest import SyncPostgrestClient
from pydantic import ValidationError

from dice import repository
from dice.live_projector import project_dice_live
from dice.live_service import LiveCommand, append_command, translate_command
from dice.live_types import DiceLiveError, DiceLiveErrorCode, SavedRules
from dice.schemas import LiveReceiptOut, VirtualMarketCreateRequest
from tests.dice_test_database import is_isolated_dice_test_database


RESULT_MIGRATION = Path(__file__).parents[1] / "migrations/0045_dice_live_results.sql"
USER = "p1"
ROW = {
    "id": "match-1", "team_order": ["team1", "team2"], "teams": {"team1": ["p1"], "team2": ["p2"]},
    "score": [0, 0], "rules_snapshot": {
        "contract_version": 1, "ruleset_version": 1, "scoring_version": 1, "target_score": 5, "win_by": 1,
        "call_policy": {"low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
        "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
        "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss"},
    },
}


def command(kind, **fields):
    return LiveCommand(kind=kind, client_command_id=fields.pop("client_command_id", "c1"), expected_version=fields.pop("expected_version", 0), **fields)


def test_append_command_clears_shared_reads_after_rpc(monkeypatch):
    class Query:
        data = []
        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: self
        def execute(self):
            return self
    class Client:
        cleared = 0
        def table(self, _name):
            return Query()
        def rpc(self, _name, _payload):
            query = Query()
            query.data = {"accepted_version": 1, "projection": {"score": [1, 0]}, "official_result": {"id": "game-1"}}
            return query
        def clear_cache(self):
            self.cleared += 1
    client = Client()
    monkeypatch.setattr("dice.live_service._row", lambda *_args: ROW)
    monkeypatch.setattr("dice.live_service._events", lambda *_args: [])

    append_command(client, "match-1", USER, command("record_throw", thrower_id="p1", outcome="point"))

    assert client.cleared == 1


def test_create_rejects_invalid_rules_before_profile_lookup_or_persistence():
    class ExplodingClient:
        def table(self, _name):
            raise AssertionError("invalid rules must be rejected before persistence work")

    with pytest.raises(DiceLiveError) as caught:
        from dice.live_service import create_live_match

        create_live_match(ExplodingClient(), USER, ROW["team_order"], ROW["teams"], {})

    assert caught.value.code == DiceLiveErrorCode.INVALID_RULES
    assert caught.value.message.startswith("saved rules are invalid:")


def test_prediction_profile_source_fails_closed_for_an_inconsistent_snapshot():
    class Client:
        def __init__(self, rating):
            self.rating = rating

        def rpc(self, _name):
            data = {
                "snapshot_version": "dice-rating-analytics/v1",
                "profiles": [{"user_id": "p1", "display_name": "Player", "elo_rating": self.rating,
                              "rating_deviation": 350.0, "elo_model_version": "1.1.0",
                              "ranked_games_played": 0, "games_played": 0,
                              "wins": 0, "losses": 0, "ranked_wins": 0,
                              "ranked_losses": 0, "normal_wins": 0,
                              "normal_losses": 0, "self_sinks": 0, "sinks": 0,
                              "hide_from_leaderboard": False}],
                "games": [], "players": [],
            }
            return type("Query", (), {"execute": lambda _self: type("Response", (), {"data": data})()})()

    from dice.live_service import _validated_prediction_profiles

    assert _validated_prediction_profiles(Client(1500))[0]["ranked_wins"] == 0
    with pytest.raises(DiceLiveError, match="canonical rating snapshot is inconsistent"):
        _validated_prediction_profiles(Client(1501))


def test_create_captures_server_rating_snapshot_at_match_start(monkeypatch):
    class Client:
        def __init__(self):
            self.inserted = None

        def rpc(self, name, payload):
            assert name == "dice_live_create_match"
            self.inserted = payload
            return self

        def execute(self):
            return type("Response", (), {"data": {
                "id": "match-1",
                "rating_snapshot": self.inserted["p_rating_snapshot"],
                "prediction_snapshot": self.inserted["p_prediction_snapshot"],
            }})()

    client = Client()
    from dice.live_service import create_live_match
    monkeypatch.setattr("dice.live_service._validated_prediction_profiles", lambda _client: [
        {"user_id": "p1", "elo_rating": 1600, "ranked_wins": 6, "ranked_games_played": 8},
        {"user_id": "p2", "elo_rating": 1400, "ranked_wins": 2, "ranked_games_played": 8},
    ])

    row = create_live_match(client, "p1", ROW["team_order"], ROW["teams"], ROW["rules_snapshot"])
    assert row["rating_snapshot"] == {
        "team1": [{"user_id": "p1", "rating": 1600, "system_version": "1.1.0"}],
        "team2": [{"user_id": "p2", "rating": 1400, "system_version": "1.1.0"}],
    }
    assert row["prediction_snapshot"]["model_id"] == "dice-pregame-logistic"
    assert row["prediction_snapshot"]["model_version"] == "1.0.0"
    assert row["prediction_snapshot"]["team1_probability"] > 0.5
    assert "captured_at" in row["prediction_snapshot"]
    assert client.inserted["p_created_by"] == "p1"
    assert client.inserted["p_ranked"] is True
    assert uuid.UUID(client.inserted["p_match_id"])


def test_create_retries_same_id_after_dropped_response(monkeypatch):
    from dice.live_service import create_live_match

    class Client:
        def __init__(self):
            self.calls = []

        def rpc(self, name, payload):
            assert name == "dice_live_create_match"
            self.calls.append(payload)
            return self

        def execute(self):
            if len(self.calls) == 1:
                raise RuntimeError("connection dropped")
            return type("Response", (), {"data": {"id": self.calls[-1]["p_match_id"]}})()

    client = Client()
    monkeypatch.setattr("dice.live_service._validated_prediction_profiles", lambda _client: [
        {"user_id": "p1", "elo_rating": 1500, "ranked_wins": 0, "ranked_games_played": 0},
        {"user_id": "p2", "elo_rating": 1500, "ranked_wins": 0, "ranked_games_played": 0},
    ])
    creation_id = "71000000-0000-0000-0000-000000000001"

    row = create_live_match(
        client, "p1", ROW["team_order"], ROW["teams"], ROW["rules_snapshot"],
        creation_id=creation_id,
    )

    assert row["id"] == creation_id
    assert len(client.calls) == 2
    assert client.calls[0] == client.calls[1]


def test_live_delete_uses_one_canonical_lifecycle_mutation(monkeypatch):
    captured = []
    client = object()
    monkeypatch.setattr(
        repository,
        "apply_game_rating_mutation",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    mutation_id = "72000000-0000-0000-0000-000000000001"
    repository.delete_live_match(
        client, "match-1", "game-1", "user-1", mutation_id=mutation_id
    )

    args, kwargs = captured[0]
    assert args[0] is client
    assert args[1:] == ("delete", {"id": "game-1"}, [])
    assert kwargs == {
        "mutation_id": mutation_id,
        "actor_id": "user-1",
        "request_fingerprint": repository._game_delete_fingerprint("game-1", "user-1"),
        "rpc_name": "dice_live_delete_with_rating_mutation",
        "rpc_parameters": {"p_match_id": "match-1", "p_deleted_by": "user-1"},
    }


def test_valid_rules_remain_projectable_for_the_first_point():
    rules = SavedRules.model_validate(ROW["rules_snapshot"])
    event = translate_command(ROW, [], command("record_throw", thrower_id="p1", outcome="point"), USER)[0]

    projection = project_dice_live(
        {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
        rules,
        [event],
    )

    assert projection.score == [1, 0]


def test_append_command_clears_shared_reads_after_rpc(monkeypatch):
    class Query:
        data = []
        def __getattr__(self, _name):
            return lambda *_args, **_kwargs: self
        def execute(self):
            return self
    class Client:
        cleared = 0
        def table(self, _name):
            return Query()
        def rpc(self, _name, _payload):
            query = Query()
            query.data = {"accepted_version": 1, "projection": {"score": [1, 0]}, "official_result": {"id": "game-1"}}
            return query
        def clear_cache(self):
            self.cleared += 1
    client = Client()
    monkeypatch.setattr("dice.live_service._row", lambda *_args: ROW)
    monkeypatch.setattr("dice.live_service._events", lambda *_args: [])

    append_command(client, "match-1", USER, command("record_throw", thrower_id="p1", outcome="point"))

    assert client.cleared == 1


def test_record_throw_derives_team_and_score_from_roster_and_outcome():
    event = translate_command(ROW, [], command("record_throw", thrower_id="p1", outcome="point"), USER)[0]
    assert event["throwing_team_id"] == "team1"
    assert event["score_delta"] == [1, 0]
    assert project_dice_live({"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]}, ROW["rules_snapshot"], [event]).score == [1, 0]


def test_table_hit_without_a_catcher_scores_nothing_and_credits_no_catch():
    event = translate_command(
        ROW,
        [],
        command("record_throw", thrower_id="p1", outcome="caught"),
        USER,
    )[0]
    projection = project_dice_live(
        {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
        ROW["rules_snapshot"],
        [event],
    )

    assert event["catcher_id"] is None
    assert projection.score == [0, 0]
    assert projection.player_stats["p1"].outcomes.caught == 1
    assert sum(player.table_catches for player in projection.player_stats.values()) == 0


def test_caught_throw_preserves_receiving_player():

    event = translate_command(
        ROW,
        [],
        command("record_throw", thrower_id="p1", outcome="caught", catcher_id="p2"),
        USER,
    )[0]
    projection = project_dice_live(
        {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
        ROW["rules_snapshot"],
        [event],
    )

    assert event["catcher_id"] == "p2"
    assert projection.player_stats["p1"].outcomes.caught == 1
    assert projection.player_stats["p2"].table_catches == 1


def test_table_hit_catcher_must_be_on_receiving_team():
    event = translate_command(
        ROW,
        [],
        command("record_throw", thrower_id="p1", outcome="caught", catcher_id="p1"),
        USER,
    )[0]

    with pytest.raises(DiceLiveError, match="receiving team"):
        project_dice_live(
            {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
            ROW["rules_snapshot"],
            [event],
        )


def test_non_caught_throw_rejects_catcher_attribution():
    with pytest.raises(ValidationError, match="only for caught throws"):
        command("record_throw", thrower_id="p1", outcome="miss", catcher_id="p2")


def test_saved_fifa_goal_is_server_derived_as_no_point():
    event = translate_command(
        ROW,
        [],
        command(
            "record_throw",
            thrower_id="p1",
            outcome="fifa",
            fifa={"finish": "goal_saved", "kicker_id": "p2", "saver_id": "p1"},
        ),
        USER,
    )[0]

    assert event["score_delta"] == [0, 0]
    projection = project_dice_live(
        {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
        ROW["rules_snapshot"],
        [event],
    )
    assert projection.score == [0, 0]
    assert projection.player_stats["p1"].fifa_saves == 1


def test_record_throw_links_physical_replay_and_completes_pending_retoss():
    decision = translate_command(ROW, [], command("retoss", thrower_id="p1", decision_basis="courtesy"), USER)[0]
    replay = translate_command(
        ROW, [decision], command("record_throw", client_command_id="replay", expected_version=1,
                                 thrower_id="p1", outcome="point", replay_of=decision["id"]), USER
    )[0]

    assert replay["replay_of"] == decision["id"]
    projection = project_dice_live(
        {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
        ROW["rules_snapshot"], [decision, replay]
    )
    assert projection.status == "active" and projection.score == [1, 0]


@pytest.mark.parametrize("target_id, events, message", [
    ("", [], "non-empty"),
    ("missing", [], "not in this match prefix"),
])
def test_record_throw_replay_target_rejections_are_stable(target_id, events, message):
    with pytest.raises(DiceLiveError) as caught:
        translate_command(ROW, events, command("record_throw", thrower_id="p1", outcome="point", replay_of=target_id), USER)

    assert caught.value.code == DiceLiveErrorCode.INVALID_REPLAY
    assert caught.value.event_id == target_id
    assert message in caught.value.message


def test_record_throw_rejects_nondecision_and_fulfilled_replay_targets():
    observation = translate_command(ROW, [], command("record_throw", thrower_id="p1", outcome="miss"), USER)[0]
    decision = translate_command(ROW, [observation], command("retoss", thrower_id="p1", decision_basis="courtesy"), USER)[0]
    replay = translate_command(ROW, [observation, decision], command("record_throw", client_command_id="replay",
        expected_version=2, thrower_id="p1", outcome="point", replay_of=decision["id"]), USER)[0]
    corrected_decision = translate_command(ROW, [decision], command("reopen", target_event_id=decision["id"]), USER)

    for events, target, message in (
        ([observation], observation["id"], "must be a retoss_decision"),
        ([observation, decision, replay], decision["id"], "already fulfilled"),
        ([decision, *corrected_decision], decision["id"], "inactive"),
    ):
        with pytest.raises(DiceLiveError, match=message) as caught:
            translate_command(ROW, events, command("record_throw", thrower_id="p1", outcome="point", replay_of=target), USER)
        assert caught.value.event_id == target


def test_corrected_replay_restores_pending_decision_for_a_new_replay():
    decision = translate_command(
        ROW, [], command("retoss", thrower_id="p1", decision_basis="courtesy"), USER
    )[0]
    replay = translate_command(
        ROW,
        [decision],
        command(
            "record_throw",
            client_command_id="replay-1",
            expected_version=1,
            thrower_id="p1",
            outcome="miss",
            replay_of=decision["id"],
        ),
        USER,
    )[0]
    correction = translate_command(
        ROW,
        [decision, replay],
        command(
            "remove_mistake",
            client_command_id="remove-replay",
            expected_version=2,
            target_event_id=replay["id"],
        ),
        USER,
    )[0]
    events = [decision, replay, correction]

    replacement_replay = translate_command(
        ROW,
        events,
        command(
            "record_throw",
            client_command_id="replay-2",
            expected_version=3,
            thrower_id="p1",
            outcome="point",
            replay_of=decision["id"],
        ),
        USER,
    )[0]
    projection = project_dice_live(
        {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
        ROW["rules_snapshot"],
        [*events, replacement_replay],
    )

    assert projection.status == "active"
    assert projection.score == [1, 0]
    assert projection.observations == 1


def test_change_throw_is_an_adjacent_hard_correction_pair_and_retoss_is_distinct():
    observation = translate_command(ROW, [], command("record_throw", thrower_id="p1", outcome="point"), USER)[0]
    changed = translate_command(ROW, [observation], command("change_throw", target_event_id=observation["id"], thrower_id="p1", outcome="miss"), USER)
    assert [event["kind"] for event in changed] == ["correction", "observation"]
    assert changed[1]["replacement_for"] == observation["id"]
    retoss = translate_command(ROW, [observation], command("retoss", target_event_id=observation["id"], thrower_id="p1", decision_basis="teams_agreed"), USER)[0]
    assert retoss["kind"] == "retoss_decision" and "score_delta" not in retoss


def test_retoss_target_is_validated_by_the_existing_projector():
    decision = translate_command(ROW, [], command("retoss", target_event_id="missing", thrower_id="p1", decision_basis="teams_agreed"), USER)[0]
    with pytest.raises(DiceLiveError) as caught:
        project_dice_live({"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]}, ROW["rules_snapshot"], [decision])
    assert caught.value.code == DiceLiveErrorCode.INVALID_REPLAY


def test_fix_score_and_partial_finish_do_not_invent_observations():
    checkpoint = translate_command(ROW, [], command("fix_score", score=[3, 2], coverage="partial"), USER)[0]
    assert checkpoint["kind"] == "score_checkpoint" and checkpoint["coverage"] == "partial"
    finish = translate_command({**ROW, "score": [3, 2]}, [checkpoint], command("finish", client_command_id="c2", coverage="partial", termination_reason="time_limit"), USER)[0]
    projection = project_dice_live({"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]}, ROW["rules_snapshot"], [checkpoint, finish])
    assert projection.status == "completed" and projection.observations == 0 and projection.coverage == "partial"


def test_reopen_preserves_the_completion_coverage_chain():
    checkpoint = translate_command(ROW, [], command("fix_score", score=[3, 2], coverage="partial"), USER)[0]
    finish = translate_command({**ROW, "score": [3, 2]}, [checkpoint], command("finish", client_command_id="c2", expected_version=1, coverage="partial", termination_reason="time_limit"), USER)[0]
    reopened = translate_command({**ROW, "score": [3, 2]}, [checkpoint, finish], command("reopen", client_command_id="c3", expected_version=2), USER)

    assert reopened[1]["coverage_after"] == checkpoint["id"]
    projection = project_dice_live(
        {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
        ROW["rules_snapshot"],
        [checkpoint, finish, *reopened],
    )
    assert projection.status == "active" and projection.score == [3, 2]


def test_fix_score_after_reopen_continues_from_the_active_checkpoint():
    checkpoint = translate_command(ROW, [], command("fix_score", score=[3, 2], coverage="partial"), USER)[0]
    finish = translate_command(
        {**ROW, "score": [3, 2]},
        [checkpoint],
        command("finish", client_command_id="c2", expected_version=1, coverage="partial", termination_reason="time_limit"),
        USER,
    )[0]
    reopened = translate_command(
        {**ROW, "score": [3, 2]},
        [checkpoint, finish],
        command("reopen", client_command_id="c3", expected_version=2),
        USER,
    )
    corrected = translate_command(
        {**ROW, "score": [3, 2]},
        [checkpoint, finish, *reopened],
        command("fix_score", client_command_id="c4", expected_version=3, score=[2, 3], coverage="partial"),
        USER,
    )[0]

    assert corrected["coverage_after"] == finish["id"]
    projection = project_dice_live(
        {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
        ROW["rules_snapshot"],
        [checkpoint, finish, *reopened, corrected],
    )
    assert projection.status == "active" and projection.score == [2, 3]


def test_change_throw_after_reopen_preserves_the_authoritative_score():
    point = translate_command(
        ROW, [], command("record_throw", thrower_id="p1", outcome="point"), USER
    )[0]
    finish = translate_command(
        {**ROW, "score": [1, 0]},
        [point],
        command(
            "finish", client_command_id="c2", expected_version=1,
            coverage="complete", termination_reason="mutual_end",
        ),
        USER,
    )[0]
    reopened = translate_command(
        {**ROW, "score": [1, 0]},
        [point, finish],
        command("reopen", client_command_id="c3", expected_version=2),
        USER,
    )
    correction = translate_command(
        {**ROW, "score": [1, 0]},
        [point, finish, *reopened],
        command(
            "change_throw", client_command_id="c4", expected_version=3,
            target_event_id=point["id"], thrower_id="p1", outcome="miss",
        ),
        USER,
    )

    projection = project_dice_live(
        {"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]},
        ROW["rules_snapshot"],
        [point, finish, *reopened, *correction],
    )

    assert projection.status == "active"
    assert projection.score == [1, 0]


def test_off_roof_is_attributed_immediately_and_reopen_is_append_only():
    off_roof = translate_command(ROW, [], command("off_roof", responsible_player_id="p1"), USER)[0]
    assert off_roof["losing_team_id"] == "team1"
    reopened = translate_command({**ROW, "score": [0, 5]}, [off_roof], command("reopen", client_command_id="c2", expected_version=1, target_event_id=off_roof["id"]), USER)[0]
    assert reopened["kind"] == "correction" and reopened["target_event_id"] == off_roof["id"]
    projection = project_dice_live({"match_id": "match-1", "team_order": ROW["team_order"], "teams": ROW["teams"]}, ROW["rules_snapshot"], [off_roof, reopened])
    assert projection.status == "active" and projection.score == [0, 0]


def test_result_bridge_is_one_reopenable_materialization_and_never_touches_ledger_rows():
    sql = RESULT_MIGRATION.read_text(encoding="utf-8")
    for reason in ("target_reached", "off_roof", "forfeit", "time_limit", "mutual_end", "other"):
        assert reason in sql
    assert "source_live_match_id uuid" in sql
    assert "add column if not exists live_result_state text," in sql
    assert "live_result_state text not null" not in sql
    assert "live_result_state text default" not in sql
    assert "live_result_state in ('official', 'reopened')" in sql
    assert "stats_complete" in sql and "detail_coverage" in sql
    assert "dice_live_materialize_result" in sql
    assert "on conflict (game_id, user_id) do nothing" in sql
    assert "delete from public.dice_live_events" not in sql
    assert "using (live_result_state is null or live_result_state = 'official')" in sql


def test_shared_game_reads_and_stats_exclude_reopened_results():
    source = Path(repository.__file__).read_text(encoding="utf-8")
    assert 'def _official_games' in source
    # `not.is.reopened` is not a legal PostgREST `is` filter (only
    # null/true/false/unknown are) and gets rejected outright, taking down
    # every caller. The filter must instead keep null/official rows and
    # drop only 'reopened', matching the RLS policy's own shape.
    assert 'query.or_("live_result_state.is.null,live_result_state.eq.official")' in source
    assert "game_rows = (\n        _official_games(supabase.table(GAMES_TABLE).select(" in source


def test_official_game_filter_serializes_through_real_postgrest_client():
    """Lock the HTTP query contract, not the behavior of our in-memory fake."""
    with SyncPostgrestClient("http://postgrest.invalid") as client:
        query = repository._official_games(client.from_("dice_games").select("id"))

    assert query.params.get("or") == "(live_result_state.is.null,live_result_state.eq.official)"
    assert "not.is.reopened" not in str(query.params)


def test_live_receipt_preserves_official_result_without_polluting_market_requests():
    receipt = LiveReceiptOut(
        accepted_version=1,
        first_sequence=1,
        last_sequence=1,
        projection={},
        official_result={"id": "game-1"},
    )
    assert receipt.official_result == {"id": "game-1"}
    assert "official_result" not in VirtualMarketCreateRequest.model_fields


def test_finish_command_accepts_partial_detail_without_synthesizing_observations():
    finish = translate_command(ROW, [], command("finish", coverage="unknown", termination_reason="other"), USER)[0]
    assert finish["kind"] == "completion" and finish["score"] == [0, 0]
    assert finish["coverage"] == "unknown" and finish["termination_reason"] == "other"


def test_command_kinds_reject_known_irrelevant_fields_with_field_identity():
    with pytest.raises(ValidationError, match="score.*not allowed for reopen"):
        command("reopen", score=[1, 0])


def test_result_bridge_materializes_ties_as_draws_without_win_loss_changes():
    sql = RESULT_MIGRATION.read_text(encoding="utf-8")
    assert "alter column winner_team drop not null" in sql
    assert "else null" in sql
    assert sql.count("winner is not null") >= 4


def test_loopback_bridge_publishes_partial_result_reopens_and_reuses_identity():
    if not is_isolated_dice_test_database(os.environ):
        pytest.skip("requires an explicitly isolated Dice test database")
    match_id = str(uuid.uuid4())
    p1, p2, p3, p4 = [f"10000000-0000-0000-0000-00000000000{i}" for i in range(1, 5)]
    teams = {"team1": [p1, p2], "team2": [p3, p4]}
    finish_event = {"id": str(uuid.uuid4()), "kind": "completion", "score": [3, 2], "coverage": "partial", "coverage_after": None, "replay_resolution_for": None, "replay_disposition": None, "termination_reason": "time_limit"}
    projection = {"score": [3, 2], "status": "completed", "termination_reason": "time_limit", "coverage": "partial", "observations": 0, "stats": {}}
    reopen_event = {"id": str(uuid.uuid4()), "kind": "correction", "target_event_id": finish_event["id"], "reason": "mistaken_entry"}
    retry_event = {**reopen_event, "id": str(uuid.uuid4())}
    finish_again_event = {**finish_event, "id": str(uuid.uuid4())}
    def encoded(value):
        return json.dumps(value, separators=(",", ":")).replace("'", "''")
    sql = f"""
      insert into public.dice_live_matches (id, created_by, team_order, teams, rules_snapshot)
        values ('{match_id}', '{p1}', '[\"team1\",\"team2\"]', '{encoded(teams)}', '{{}}');
      insert into public.dice_live_referees (match_id, user_id) values ('{match_id}', '{p1}');
      set request.jwt.claims = '{{"role":"service_role"}}';
      select public.dice_live_append_command('{match_id}', '{p1}', 'finish', 0, '{{}}', '{encoded([finish_event])}', '{encoded(projection)}', array[3,2]::smallint[], 'completed', 'partial');
      select public.dice_live_append_command('{match_id}', '{p1}', 'reopen', 1, '{{}}', '{encoded([reopen_event])}', '{{"score":[0,0],"status":"active","coverage":"unknown","observations":0,"stats":{{}}}}', array[0,0]::smallint[], 'active', 'unknown');
      select public.dice_live_append_command('{match_id}', '{p1}', 'reopen', 1, '{{}}', '{encoded([retry_event])}', '{{"score":[0,0],"status":"active","coverage":"unknown","observations":0,"stats":{{}}}}', array[0,0]::smallint[], 'active', 'unknown');
      select public.dice_live_append_command('{match_id}', '{p1}', 'finish-again', 2, '{{}}', '{encoded([finish_again_event])}', '{encoded(projection)}', array[3,2]::smallint[], 'completed', 'partial');
      select (select id::text from public.dice_games where source_live_match_id = '{match_id}'), (select live_result_state from public.dice_games where source_live_match_id = '{match_id}'), (select count(*) from public.dice_game_players where game_id = (select id from public.dice_games where source_live_match_id = '{match_id}')), (select stats_complete from public.dice_games where source_live_match_id = '{match_id}'), (select count(*) from public.dice_live_events where match_id = '{match_id}');
    """
    result = subprocess.run(["psql", os.environ["DB_URL"], "--no-psqlrc", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    result_id, state, players, stats_complete, event_count = result.stdout.strip().splitlines()[-1].split("|")
    assert result_id and state == "official" and players == "4" and stats_complete == "f" and event_count == "3"
