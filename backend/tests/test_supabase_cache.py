from supabase_cache import (
    CachedSupabaseClient,
    SupabaseTTLCacheStore,
    forget_snapshot_rpc,
    read_snapshot_rpc,
)
from dice.repository import _player_profiles


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.filters = {}
        self.mutating = False

    def select(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def in_(self, field, values):
        self.filters[field] = set(values)
        return self

    def update(self, _payload):
        self.mutating = True
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        self.client.table_reads.append((self.table, dict(self.filters)))
        rows = self.client.rows
        if "user_id" in self.filters:
            return _Resp([row for row in self.client.all_rows if row["user_id"] in self.filters["user_id"]])
        return _Resp(list(rows))


class _Rpc:
    def __init__(self, client, name, params):
        self.client = client
        self.name = name
        self.params = params

    def execute(self):
        self.client.rpc_calls.append((self.name, self.params))
        return _Resp({"call": len(self.client.rpc_calls)})


class _Client:
    def __init__(self, rows=None, all_rows=None):
        self.rows = rows or []
        self.all_rows = all_rows or self.rows
        self.table_reads = []
        self.rpc_calls = []

    def table(self, name):
        return _Query(self, name)

    def rpc(self, name, params=None):
        return _Rpc(self, name, params)


def _cached(client):
    return CachedSupabaseClient(client, SupabaseTTLCacheStore(ttl_seconds=60))


def test_snapshot_rpc_is_served_from_cache_until_a_write_clears_it():
    raw = _Client()
    client = _cached(raw)

    first = read_snapshot_rpc(client, "dice_rating_analytics_snapshot")
    second = read_snapshot_rpc(client, "dice_rating_analytics_snapshot")
    assert first.data == second.data == {"call": 1}

    client.table("dice_profiles").update({"display_name": "x"}).eq("user_id", "u1").execute()
    assert read_snapshot_rpc(client, "dice_rating_analytics_snapshot").data == {"call": 2}


def test_snapshot_rpc_cache_is_keyed_by_params_and_can_be_forgotten():
    raw = _Client()
    client = _cached(raw)

    read_snapshot_rpc(client, "dice_duo_replay_snapshot", {"p_max_games": 10})
    read_snapshot_rpc(client, "dice_duo_replay_snapshot", {"p_max_games": 20})
    read_snapshot_rpc(client, "dice_duo_replay_snapshot", {"p_max_games": 10})
    assert len(raw.rpc_calls) == 2

    forget_snapshot_rpc(client, "dice_duo_replay_snapshot", {"p_max_games": 10})
    read_snapshot_rpc(client, "dice_duo_replay_snapshot", {"p_max_games": 10})
    assert len(raw.rpc_calls) == 3


def test_snapshot_rpc_reads_directly_without_a_cache():
    raw = _Client()
    read_snapshot_rpc(raw, "dice_rating_analytics_snapshot")
    read_snapshot_rpc(raw, "dice_rating_analytics_snapshot")
    assert len(raw.rpc_calls) == 2


def test_player_profiles_share_one_directory_read_across_pages():
    rows = [
        {"user_id": "u1", "display_name": "One", "avatar_url": None},
        {"user_id": "u2", "display_name": "Two", "avatar_url": None},
    ]
    raw = _Client(rows=rows)
    client = _cached(raw)

    assert _player_profiles(client, ["u1"]) == {"u1": rows[0]}
    assert _player_profiles(client, ["u2", "u1"]) == {"u2": rows[1], "u1": rows[0]}
    assert len(raw.table_reads) == 1


def test_player_profiles_fetch_anyone_the_directory_read_missed():
    listed = {"user_id": "u1", "display_name": "One", "avatar_url": None}
    capped = {"user_id": "u9", "display_name": "Nine", "avatar_url": None}
    raw = _Client(rows=[listed], all_rows=[listed, capped])

    assert _player_profiles(raw, ["u1", "u9", "gone"]) == {"u1": listed, "u9": capped}
    assert raw.table_reads[-1] == ("dice_profiles", {"user_id": {"u9", "gone"}})


def test_player_profiles_skip_the_read_for_no_players():
    raw = _Client()
    assert _player_profiles(raw, []) == {}
    assert raw.table_reads == []
