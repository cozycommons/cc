from types import SimpleNamespace

from jobs import dice_rating_rebuild as job


class Query:
    def __init__(self, data=None, error=None):
        self.data, self.error = data, error

    def execute(self):
        if self.error:
            raise self.error
        return SimpleNamespace(data=self.data)


class Client:
    def __init__(self):
        self.calls = []

    def rpc(self, name, parameters=None):
        self.calls.append((name, parameters))
        if name == "dice_rating_source_snapshot":
            return Query({"profiles": [{"user_id": "p1"}], "games": [], "players": []})
        return Query({"state": {
            "profiles": parameters["p_profile_states"],
            "players": parameters["p_player_snapshots"],
        }})


def test_rebuild_commits_the_complete_deterministic_plan():
    client = Client()

    assert job.rebuild_canonical_ratings(client) == 0
    assert client.calls[0] == ("dice_rating_source_snapshot", None)
    name, payload = client.calls[1]
    assert name == "dice_rating_commit_rebuild"
    assert payload["p_source"] == {
        "profiles": [{"user_id": "p1"}], "games": [], "players": []
    }
    assert payload["p_profile_states"][0]["elo_rating"] == 1500


def test_rebuild_replays_a_fresh_plan_after_a_source_race():
    class ConflictClient(Client):
        def __init__(self):
            super().__init__()
            self.commit_attempts = 0

        def rpc(self, name, parameters=None):
            if name == "dice_rating_commit_rebuild":
                self.commit_attempts += 1
                if self.commit_attempts == 1:
                    self.calls.append((name, parameters))
                    return Query(error=RuntimeError("dice_rating.source_changed"))
            return super().rpc(name, parameters)

    client = ConflictClient()

    assert job.rebuild_canonical_ratings(client) == 0
    assert [name for name, _ in client.calls].count("dice_rating_source_snapshot") == 2
    assert client.commit_attempts == 2
