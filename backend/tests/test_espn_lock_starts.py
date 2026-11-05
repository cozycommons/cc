"""Synthetic regression for cascading replacement locks; no ESPN writes."""
from espn import lineup


def test_excluded_replacement_preserves_incumbent_chain_and_unrelated_start():
    def player(pid, source, target):
        return {"player_id": pid, "name": f"Player {pid}", "from_slot": source,
                "to_slot": target, "value": 10, "scheduled": True}
    players = [player(1, 12, 0), player(2, 2, 12), player(3, 0, 2), player(4, 12, 1)]
    moves = [{"playerId": p["player_id"], "fromLineupSlotId": p["from_slot"],
              "toLineupSlotId": p["to_slot"]} for p in players]
    plan = {"players": players, "moves": moves}
    pending, skips = lineup._reconcile_lock_exclusions(plan, {1}, {}, {0: 1, 1: 1, 2: 1, 12: 2})
    assert [m["playerId"] for m in pending] == [4]
    assert {s["player_id"] for s in skips} == {1, 2, 3}
    assert all("replacement" in s["reason"] for s in skips if s["player_id"] in {2, 3})


def test_harmless_starter_shuffle_survives_a_lock():
    players = [{"player_id": 1, "name": "Locked", "from_slot": 12, "to_slot": 0, "value": 10},
               {"player_id": 2, "name": "Mover", "from_slot": 0, "to_slot": 1, "value": 10}]
    plan = {"players": players, "moves": [{"playerId": p["player_id"]} for p in players]}
    pending, _ = lineup._reconcile_lock_exclusions(plan, {1}, {}, {0: 1, 1: 1, 12: 1})
    assert [m["playerId"] for m in pending] == [2]
