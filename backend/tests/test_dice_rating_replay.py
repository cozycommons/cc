from copy import deepcopy

import pytest

from dice.rating_replay import build_rating_plan, project_game_mutation


USERS = [f"u{index}" for index in range(1, 5)]


def _game(game_id, *, ranked, winner, played_at, state=None):
    return {
        "id": game_id,
        "created_by": USERS[0],
        "ranked": ranked,
        "team1_score": 21 if winner == 1 else 15,
        "team2_score": 21 if winner == 2 else 15,
        "winner_team": winner,
        "played_at": played_at,
        "created_at": played_at,
        "tournament_id": None,
        "source_live_match_id": None,
        "live_result_state": state,
        "termination_reason": None,
        "detail_coverage": "complete",
        "stats_complete": True,
    }


def _players(game_id, prefix, *, sinks=0):
    return [
        {
            "id": f"{prefix}{index}",
            "game_id": game_id,
            "user_id": user_id,
            "team": 1 if index < 3 else 2,
            "counts_for_group_stage": True,
            "self_sinks": index - 1,
            "sinks": sinks + index - 1,
        }
        for index, user_id in enumerate(USERS, 1)
    ]


def _source():
    games = [
        _game("g1", ranked=True, winner=1, played_at="2026-01-01T00:00:00Z"),
        _game("g2", ranked=False, winner=2, played_at="2026-01-02T00:00:00Z"),
        _game("g3", ranked=True, winner=None, played_at="2026-01-03T00:00:00Z"),
        _game("g4", ranked=False, winner=1, played_at="2026-01-04T00:00:00Z", state="reopened"),
    ]
    return {
        "profiles": [{"user_id": user_id} for user_id in USERS],
        "games": games,
        "players": [
            *_players("g1", "a"), *_players("g2", "b", sinks=2),
            *_players("g3", "c"), *_players("g4", "d"),
        ],
    }


def test_rating_plan_is_deterministic_and_materializes_one_canonical_state():
    source = _source()
    plan = build_rating_plan(source)
    assert plan == build_rating_plan(deepcopy(source))
    source["games"][0]["ranked"] = False
    assert plan.source["games"][0]["ranked"] is True
    assert plan.eligible_ranked_games == 1
    assert len(plan.player_snapshots) == 16

    snapshots = {row["id"]: row for row in plan.player_snapshots}
    assert snapshots["a1"]["elo_before"] == 1500
    assert snapshots["a1"]["elo_after"] > 1500
    assert snapshots["a3"]["elo_after"] < 1500
    assert snapshots["b1"]["elo_before"] is None
    assert snapshots["c1"]["elo_before"] is None
    assert snapshots["d1"]["elo_before"] is None

    profiles = {row["user_id"]: row for row in plan.profile_states}
    assert profiles["u1"]["games_played"] == 3
    assert profiles["u1"]["wins"] == 1
    assert profiles["u1"]["losses"] == 1
    assert profiles["u1"]["ranked_wins"] == 1
    assert profiles["u1"]["normal_losses"] == 1
    assert profiles["u1"]["ranked_games_played"] == 1
    assert profiles["u1"]["self_sinks"] == 0
    assert profiles["u4"]["sinks"] == 11


def test_projection_replaces_exact_game_generation_without_mutating_input():
    source = _source()
    original = deepcopy(source)
    game = _game("g2", ranked=True, winner=1, played_at="2026-01-05T00:00:00Z")
    players = [{key: value for key, value in row.items() if key != "game_id"}
               for row in _players("g2", "z")]
    projected = project_game_mutation(source, "update", game, players)
    assert source == original
    assert next(row for row in projected["games"] if row["id"] == "g2") == game
    assert {row["id"] for row in projected["players"] if row["game_id"] == "g2"} == {
        "z1", "z2", "z3", "z4"
    }
    deleted = project_game_mutation(projected, "delete", game, [])
    assert all(row["id"] != "g2" for row in deleted["games"])
    with pytest.raises(ValueError, match="already exists"):
        project_game_mutation(source, "create", source["games"][0], [])
    with pytest.raises(ValueError, match="not found"):
        project_game_mutation(source, "delete", {"id": "missing"}, [])


def test_rating_plan_rejects_invalid_source_shapes_and_duplicate_profiles():
    with pytest.raises(ValueError, match="must be an object"):
        build_rating_plan([])
    with pytest.raises(ValueError, match="arrays are required"):
        build_rating_plan({})
    source = _source()
    source["profiles"].append({"user_id": USERS[0]})
    with pytest.raises(ValueError, match="must be unique"):
        build_rating_plan(source)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda source: source["games"].append(None),
        lambda source: source["players"].append("bad"),
    ],
)
def test_rating_plan_rejects_scalar_source_rows(mutate):
    source = _source()
    mutate(source)
    with pytest.raises(ValueError, match="rows must be objects"):
        build_rating_plan(source)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda source: source["profiles"][0].update(user_id=[]),
        lambda source: source["games"][0].update(id=None),
        lambda source: source["players"][0].update(game_id=""),
    ],
)
def test_rating_plan_rejects_non_string_identities(mutate):
    source = _source()
    mutate(source)
    with pytest.raises(ValueError, match="identities must be non-empty strings"):
        build_rating_plan(source)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda source: source["games"].append(deepcopy(source["games"][0])), "games must be unique"),
        (lambda source: source["players"].append(deepcopy(source["players"][0])), "players must be unique"),
        (lambda source: source["players"][0].update(user_id="missing"), "unknown identities"),
        (lambda source: source["players"][0].update(game_id="missing"), "unknown identities"),
        (lambda source: source["players"][1].update(user_id=USERS[0]), "participants must be unique"),
    ],
)
def test_rating_plan_rejects_ambiguous_or_unknown_source_identities(mutate, message):
    source = _source()
    mutate(source)
    with pytest.raises(ValueError, match=message):
        build_rating_plan(source)
