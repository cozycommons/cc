from copy import deepcopy

import pytest

from dice.rating_replay import apply_game_rating_mutation


def _source():
    timestamp = "2026-01-01T00:00:00+00:00"
    return {
        "profiles": [{"user_id": "u1"}, {"user_id": "u2"}],
        "games": [{
            "id": "g1", "ranked": True, "winner_team": 1,
            "team1_score": 11, "team2_score": 5,
            "played_at": timestamp, "created_at": timestamp,
            "live_result_state": None,
        }],
        "players": [
            {"id": "p1", "game_id": "g1", "user_id": "u1", "team": 1,
             "self_sinks": 0, "sinks": 2},
            {"id": "p2", "game_id": "g1", "user_id": "u2", "team": 2,
             "self_sinks": 0, "sinks": 1},
        ],
    }


class _Response:
    def __init__(self, data):
        self.data = data


class _MutationClient:
    def __init__(self, source, *, source_changes=0, mutate_then_raise=False):
        self.source = source
        self.state = {"players": [], "profiles": []}
        self.source_changes = source_changes
        self.mutate_then_raise = mutate_then_raise
        self.mutation_attempts = 0
        self.mutation_receipts = {}
        self.cache_clear_count = 0

    def clear_cache(self):
        self.cache_clear_count += 1

    def rpc(self, name, params=None):
        client = self

        class _RPC:
            def execute(self):
                if name == "dice_rating_source_snapshot":
                    return _Response(deepcopy(client.source))
                if name == "dice_rating_state_snapshot":
                    return _Response(deepcopy(client.state))
                if name == "dice_rating_mutation_receipt":
                    return _Response(deepcopy(client.mutation_receipts.get(params["p_mutation_id"])))
                if name != "dice_rating_apply_game_mutation":
                    raise AssertionError(name)
                client.mutation_attempts += 1
                if client.source_changes:
                    client.source_changes -= 1
                    client.source["games"][0]["created_at"] = "2026-01-01T00:00:01+00:00"
                    raise RuntimeError("dice_rating.source_changed")
                client.source = deepcopy(params["p_expected_source"])
                client.state = {
                    "players": deepcopy(params["p_player_snapshots"]),
                    "profiles": deepcopy(params["p_profile_states"]),
                }
                mutation_id = params["p_mutation_id"]
                client.mutation_receipts[mutation_id] = {
                    "mutation_id": mutation_id,
                    "operation": params["p_operation"],
                    "game_id": params["p_game"]["id"],
                    "actor_id": params["p_actor_id"],
                    "request_fingerprint": params["p_request_fingerprint"],
                    "source_digest": params["p_source_digest"],
                    "output_digest": params["p_output_digest"],
                    "players_updated": len(client.state["players"]),
                    "profiles_updated": len(client.state["profiles"]),
                }
                if client.mutate_then_raise:
                    client.mutate_then_raise = False
                    raise RuntimeError("synthetic dropped response after mutation")
                return _Response({**client.mutation_receipts[mutation_id], "state": deepcopy(client.state)})

        return _RPC()


@pytest.mark.parametrize("source_changes,mutate_then_raise", [(1, False), (0, True)])
def test_game_mutation_retries_stale_source_and_reconciles_dropped_response(
    source_changes, mutate_then_raise
):
    source = _source()
    game = {"id": "g1", "team1_score": 5, "team2_score": 11, "winner_team": 2}
    players = [{key: value for key, value in row.items() if key != "game_id"}
               for row in source["players"]]
    client = _MutationClient(
        deepcopy(source), source_changes=source_changes, mutate_then_raise=mutate_then_raise
    )

    result = apply_game_rating_mutation(client, "update", game, players)

    assert client.source["games"][0]["winner_team"] == 2
    assert result["operation"] == "update"
    assert client.mutation_attempts == 1 + source_changes
    assert result.get("reconciled_after_transport_error") is (True if mutate_then_raise else None)
    assert client.cache_clear_count == 1


def test_custom_rpc_parameters_cannot_override_canonical_inputs():
    with pytest.raises(ValueError, match="cannot override canonical fields: p_game"):
        apply_game_rating_mutation(
            object(),
            "delete",
            {"id": "g1"},
            [],
            mutation_id="77000000-0000-0000-0000-000000000001",
            rpc_parameters={"p_game": {"id": "other"}},
        )
