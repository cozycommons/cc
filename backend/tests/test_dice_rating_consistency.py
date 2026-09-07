from copy import deepcopy

import pytest

from dice.rating_consistency import validate_canonical_rating_snapshot


def _source():
    profiles = [
        {"user_id": "a", "elo_rating": 1531, "rating_deviation": 297.5,
         "elo_model_version": "1.1.0", "ranked_games_played": 1,
         "games_played": 1, "wins": 1, "losses": 0, "ranked_wins": 1,
         "ranked_losses": 0, "normal_wins": 0, "normal_losses": 0,
         "self_sinks": 0, "sinks": 0},
        {"user_id": "b", "elo_rating": 1469, "rating_deviation": 297.5,
         "elo_model_version": "1.1.0", "ranked_games_played": 1,
         "games_played": 1, "wins": 0, "losses": 1, "ranked_wins": 0,
         "ranked_losses": 1, "normal_wins": 0, "normal_losses": 0,
         "self_sinks": 0, "sinks": 0},
    ]
    games = [{
        "id": "g1", "ranked": True, "winner_team": 1,
        "team1_score": 11, "team2_score": 5,
        "played_at": "2026-01-01T00:00:00+00:00",
        "created_at": "2026-01-01T00:00:00+00:00",
        "live_result_state": None,
    }]
    players = [
        {"id": "p1", "game_id": "g1", "user_id": "a", "team": 1,
         "self_sinks": 0, "sinks": 0, "elo_before": 1500, "elo_after": 1531,
         "rating_deviation_before": 350.0, "rating_deviation_after": 297.5},
        {"id": "p2", "game_id": "g1", "user_id": "b", "team": 2,
         "self_sinks": 0, "sinks": 0, "elo_before": 1500, "elo_after": 1469,
         "rating_deviation_before": 350.0, "rating_deviation_after": 297.5},
    ]
    return profiles, games, players


def test_canonical_snapshot_replays_profiles_and_player_transitions():
    source = _source()
    original = deepcopy(source)

    validate_canonical_rating_snapshot(*source)

    assert source == original


@pytest.mark.parametrize(
    ("collection", "field"),
    [(0, "elo_rating"), (0, "rating_deviation"), (0, "wins"),
     (2, "elo_after"), (2, "rating_deviation_after")],
)
def test_canonical_snapshot_rejects_persisted_rating_mismatch(collection, field):
    source = list(_source())
    source[collection][0][field] += 1

    with pytest.raises(ValueError, match="canonical replay does not match"):
        validate_canonical_rating_snapshot(*source)


def test_canonical_snapshot_rejects_invalid_references_and_ranked_rosters():
    profiles, games, players = _source()
    players[0]["user_id"] = "unknown"
    with pytest.raises(ValueError, match="unknown identities"):
        validate_canonical_rating_snapshot(profiles, games, players)

    profiles, games, players = _source()
    with pytest.raises(ValueError, match="incomplete roster"):
        validate_canonical_rating_snapshot(profiles, games, players[:1])
