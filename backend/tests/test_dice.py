import uuid
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from dice.rating_replay import build_rating_plan
from dice.routes import ADMIN_EMAIL, router
from dice.schemas import DiceGame
from fastapi import FastAPI
from fastapi.testclient import TestClient
from runtime_policy import initialize_runtime_policy

ADMIN_TOKEN = "admin-token"
HOST_TOKEN = "host-token"
OTHER_TOKEN = "other-token"

AUTH_USERS = {
    ADMIN_TOKEN: {"id": "u3", "email": ADMIN_EMAIL},  # Jason Keung
    HOST_TOKEN: {"id": "u1", "email": "andrew@example.com"},  # Andrew S
    OTHER_TOKEN: {"id": "u4", "email": "jaycee@example.com"},  # Jaycee
}


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


class _Resp:
    def __init__(self, data):
        self.data = data


class _NotProxy:
    """Stands in for postgrest-py's `.not_` filter negation proxy."""

    def __init__(self, query):
        self._query = query

    def is_(self, field, value):
        self._query._not_is.append((field, value))
        return self._query


class _FakeQuery:
    """A minimal in-memory stand-in for the supabase-py query builder, just
    enough of it (select/eq/in_/order/limit/insert/update/upsert/delete) to
    exercise dice/repository.py end to end without a real database."""

    def __init__(self, rows_ref):
        self._rows_ref = rows_ref
        self._eq = []
        self._in = []
        self._gt = []
        self._gte = []
        self._lt = []
        self._ilike = []
        self._not_is = []
        self._or = []
        self._order = []
        self._limit = None
        self._range = None
        self._op = None
        self._payload = None
        self._upsert_keys = None

    @property
    def not_(self):
        return _NotProxy(self)

    def select(self, *_args, **_kwargs):
        self._op = self._op or "select"
        return self

    def eq(self, field, value):
        self._eq.append((field, value))
        return self

    def in_(self, field, values):
        self._in.append((field, set(values)))
        return self

    def gt(self, field, value):
        self._gt.append((field, value))
        return self

    def gte(self, field, value):
        self._gte.append((field, value))
        return self

    def lt(self, field, value):
        self._lt.append((field, value))
        return self

    def ilike(self, field, pattern):
        needle = pattern.strip("%").lower()
        self._ilike.append((field, needle))
        return self

    def or_(self, filters):
        self._or.append(filters)
        return self

    def order(self, field, desc=False):
        self._order.append((field, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._payload = payload
        self._upsert_keys = on_conflict.split(",") if on_conflict else ["tournament_id", "user_id"]
        return self

    def delete(self):
        self._op = "delete"
        return self

    def _filtered(self):
        rows = self._rows_ref
        for field, value in self._eq:
            rows = [r for r in rows if r.get(field) == value]
        for field, values in self._in:
            rows = [r for r in rows if r.get(field) in values]
        for field, value in self._gt:
            rows = [r for r in rows if (r.get(field) or 0) > value]
        for field, value in self._gte:
            rows = [r for r in rows if (r.get(field) or 0) >= value]
        for field, value in self._lt:
            rows = [r for r in rows if (r.get(field) or 0) < value]
        for field, needle in self._ilike:
            rows = [r for r in rows if needle in str(r.get(field, "")).lower()]
        for field, value in self._not_is:
            if value == "null":
                rows = [r for r in rows if r.get(field) is not None]
            else:
                rows = [r for r in rows if r.get(field) != value]
        for filters in self._or:
            rows = [r for r in rows if any(self._matches_or_clause(r, c) for c in filters.split(","))]
        return rows

    @staticmethod
    def _matches_or_clause(row, clause):
        """Minimal stand-in for PostgREST's `or=(...)` clause parsing,
        just enough to cover `field.is.null` / `field.eq.value`."""
        field, op, value = clause.split(".", 2)
        if op == "is":
            return row.get(field) is None if value == "null" else row.get(field) == (value == "true")
        if op == "eq":
            return row.get(field) == value
        raise NotImplementedError(f"unsupported or_ clause operator: {op}")

    def execute(self):
        if self._op in (None, "select"):
            rows = self._filtered()
            # Stable sorts in reverse priority reproduce PostgREST's compound
            # order clauses (first call is the primary key).
            for field, desc in reversed(self._order):
                rows = sorted(rows, key=lambda r: r.get(field), reverse=desc)
            if self._limit is not None:
                rows = rows[: self._limit]
            if self._range is not None:
                start, end = self._range
                rows = rows[start : end + 1]
            return _Resp([dict(r) for r in rows])

        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            now = datetime.now(timezone.utc).isoformat()
            for p in payloads:
                row = dict(p)
                row.setdefault("id", str(uuid.uuid4()))
                row.setdefault("created_at", now)
                row.setdefault("updated_at", now)
                self._rows_ref.append(row)
                inserted.append(row)
            return _Resp(inserted)

        if self._op == "update":
            rows = self._filtered()
            for r in rows:
                r.update(self._payload)
            return _Resp([dict(r) for r in rows])

        if self._op == "upsert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            result = []
            for p in payloads:
                existing = next(
                    (
                        r
                        for r in self._rows_ref
                        if all(r.get(key) == p.get(key) for key in self._upsert_keys)
                    ),
                    None,
                )
                if existing:
                    existing.update(p)
                    result.append(existing)
                else:
                    row = dict(p)
                    if "tournament_id" in row:
                        row.setdefault("enrolled_at", datetime.now(timezone.utc).isoformat())
                    self._rows_ref.append(row)
                    result.append(row)
            return _Resp(result)

        if self._op == "delete":
            rows = self._filtered()
            for r in rows:
                self._rows_ref.remove(r)
            return _Resp([dict(r) for r in rows])


class _FakeAuth:
    def __init__(self, users_by_token):
        self._users_by_token = users_by_token

    def get_user(self, token):
        info = self._users_by_token.get(token)
        if info is None:
            raise ValueError("invalid token")
        user = type("User", (), {"id": info["id"], "email": info["email"], "user_metadata": {}})()
        return type("Resp", (), {"user": user})()


class _FakeSupabase:
    def __init__(self):
        self.tables = {}
        self.auth = _FakeAuth({})
        self.cache_clear_count = 0
        self.rating_mutation_failure = None
        self.rating_mutation_receipts = {}

    def clear_cache(self):
        self.cache_clear_count += 1

    def table(self, name):
        return _FakeQuery(self.tables.setdefault(name, []))

    def _rating_analytics_snapshot(self):
        games = [
            {key: row.get(key) for key in (
                "id", "ranked", "winner_team", "team1_score", "team2_score",
                "played_at", "created_at", "live_result_state",
            )}
            for row in self.tables.get("dice_games", [])
            if row.get("live_result_state") in (None, "official")
        ]
        game_ids = {row["id"] for row in games}
        return {
            "snapshot_version": "dice-rating-analytics/v1",
            "profiles": [
                {key: row.get(key) for key in (
                    "user_id", "display_name", "elo_rating", "rating_deviation",
                    "elo_model_version", "ranked_games_played", "games_played",
                    "wins", "losses", "ranked_wins", "ranked_losses",
                    "normal_wins", "normal_losses", "self_sinks", "sinks",
                    "hide_from_leaderboard",
                )}
                for row in self.tables.get("dice_profiles", [])
            ],
            "games": games,
            "players": [
                {key: row.get(key) for key in (
                    "id", "game_id", "user_id", "team", "self_sinks", "sinks",
                    "elo_before", "elo_after", "rating_deviation_before",
                    "rating_deviation_after",
                )}
                for row in self.tables.get("dice_game_players", []) if row["game_id"] in game_ids
            ],
        }

    def _rating_source_snapshot(self, tables=None):
        tables = self.tables if tables is None else tables
        return {
            "profiles": [
                {"user_id": row["user_id"]}
                for row in sorted(tables.get("dice_profiles", []), key=lambda row: row["user_id"])
            ],
            "games": [
                {key: row.get(key) for key in (
                    "id", "created_by", "ranked", "team1_score", "team2_score",
                    "winner_team", "played_at", "created_at", "tournament_id",
                    "source_live_match_id", "live_result_state", "termination_reason",
                    "detail_coverage", "stats_complete",
                )}
                for row in sorted(
                    tables.get("dice_games", []),
                    key=lambda row: (row["played_at"], row["created_at"], row["id"]),
                )
            ],
            "players": [
                {key: row.get(key) for key in (
                    "id", "game_id", "user_id", "team", "counts_for_group_stage",
                    "self_sinks", "sinks",
                )}
                for row in sorted(
                    tables.get("dice_game_players", []),
                    key=lambda row: (row["game_id"], row["user_id"], row["id"]),
                )
            ],
        }

    def _rating_state_snapshot(self, tables=None):
        tables = self.tables if tables is None else tables
        return {
            "profiles": [
                {key: row.get(key) for key in (
                    "user_id", "elo_rating", "rating_deviation", "elo_model_version",
                    "ranked_games_played", "games_played", "wins", "losses",
                    "ranked_wins", "ranked_losses", "normal_wins", "normal_losses",
                    "self_sinks", "sinks",
                )}
                for row in sorted(tables.get("dice_profiles", []), key=lambda row: row["user_id"])
            ],
            "players": [
                {key: row.get(key) for key in (
                    "id", "elo_before", "elo_after", "rating_deviation_before",
                    "rating_deviation_after",
                )}
                for row in sorted(tables.get("dice_game_players", []), key=lambda row: row["id"])
            ],
        }

    def rpc(self, name, params=None):
        supabase = self

        class _FakeRpc:
            def execute(self):
                if name == "dice_rating_analytics_snapshot":
                    return _Resp(supabase._rating_analytics_snapshot())
                if name == "dice_rating_source_snapshot":
                    return _Resp(supabase._rating_source_snapshot())
                if name == "dice_rating_state_snapshot":
                    return _Resp(supabase._rating_state_snapshot())
                if name == "dice_rating_mutation_receipt":
                    return _Resp(deepcopy(
                        supabase.rating_mutation_receipts.get(params["p_mutation_id"])
                    ))
                if name == "dice_rating_apply_game_mutation":
                    mutation_id = params["p_mutation_id"]
                    prior_receipt = supabase.rating_mutation_receipts.get(mutation_id)
                    if prior_receipt is not None:
                        if (
                            prior_receipt["operation"] != params["p_operation"]
                            or prior_receipt["game_id"] != params["p_game"]["id"]
                            or prior_receipt["actor_id"] != params["p_actor_id"]
                            or prior_receipt["request_fingerprint"]
                            != params["p_request_fingerprint"]
                        ):
                            raise RuntimeError("dice_rating.idempotency_conflict")
                        return _Resp({**deepcopy(prior_receipt), "replayed": True})
                    if supabase.rating_mutation_failure == "before":
                        raise RuntimeError("synthetic mutation failure")
                    if params["p_source"] != supabase._rating_source_snapshot():
                        raise RuntimeError("dice_rating.source_changed")
                    working = deepcopy(supabase.tables)
                    game_id = params["p_game"]["id"]
                    games = working.setdefault("dice_games", [])
                    players = working.setdefault("dice_game_players", [])
                    games[:] = [row for row in games if row["id"] != game_id]
                    players[:] = [row for row in players if row["game_id"] != game_id]
                    if params["p_operation"] != "delete":
                        games.append(dict(params["p_game"]))
                        players.extend(
                            {**dict(row), "game_id": game_id} for row in params["p_players"]
                        )
                    if params["p_expected_source"] != supabase._rating_source_snapshot(working):
                        raise RuntimeError("dice_rating.post_mutation_mismatch")
                    players_by_id = {row["id"]: row for row in players}
                    profiles_by_id = {
                        row["user_id"]: row for row in working.get("dice_profiles", [])
                    }
                    for snapshot in params["p_player_snapshots"]:
                        players_by_id[snapshot["id"]].update(snapshot)
                    for state in params["p_profile_states"]:
                        profiles_by_id[state["user_id"]].update(state)
                    if supabase.rating_mutation_failure == "after":
                        raise RuntimeError("synthetic mutation failure")
                    supabase.tables = working
                    supabase.rating_mutation_receipts[mutation_id] = {
                        "mutation_id": mutation_id,
                        "operation": params["p_operation"],
                        "game_id": game_id,
                        "actor_id": params["p_actor_id"],
                        "request_fingerprint": params["p_request_fingerprint"],
                        "source_digest": params["p_source_digest"],
                        "output_digest": params["p_output_digest"],
                        "players_updated": len(params["p_player_snapshots"]),
                        "profiles_updated": len(params["p_profile_states"]),
                    }
                    if supabase.rating_mutation_failure == "after_commit":
                        supabase.rating_mutation_failure = None
                        raise RuntimeError("synthetic dropped mutation response")
                    return _Resp({
                        "operation": params["p_operation"],
                        "game_id": game_id,
                        "mutation_id": mutation_id,
                        "actor_id": params["p_actor_id"],
                        "request_fingerprint": params["p_request_fingerprint"],
                        "source_digest": params["p_source_digest"],
                        "output_digest": params["p_output_digest"],
                        "players_updated": len(params["p_player_snapshots"]),
                        "profiles_updated": len(params["p_profile_states"]),
                        "state": supabase._rating_state_snapshot(),
                    })
                raise NotImplementedError(name)

        return _FakeRpc()


def _profile(user_id, display_name):
    return {
        "user_id": user_id,
        "display_name": display_name,
        "avatar_url": None,
        "elo_rating": 1500,
        "rating_deviation": 350.0,
        "elo_model_version": "1.1.0",
        "games_played": 0,
        "ranked_games_played": 0,
        "wins": 0,
        "losses": 0,
        "self_sinks": 0,
        "hide_from_leaderboard": False,
    }


# u1..u7, matching AUTH_USERS above (u1 = Andrew S, u3 = Jason Keung, u4 = Jaycee).
ROSTER_NAMES = ["Andrew S", "Aziz Rahman", "Jason Keung", "Jaycee", "Josh Lee", "Shrey Shah", "Warner Tsang", "Priya Nair"]
ROSTER = [_profile(f"u{i}", name) for i, name in enumerate(ROSTER_NAMES, start=1)]


def _build_client(
    profiles=None,
    auth_users=None,
    feature_access=None,
    raise_server_exceptions=True,
):
    app = FastAPI()
    app.include_router(router, prefix="/dice")
    app.state.runtime_policy = initialize_runtime_policy(
        {
            "DICE_LOCAL_HARNESS": "true",
        },
        lambda: None,
    )
    supabase = _FakeSupabase()
    supabase.tables["dice_profiles"] = profiles or []
    supabase.tables["dice_feature_access"] = feature_access or []
    supabase.auth = _FakeAuth(auth_users or {})
    app.state.supabase = supabase
    app.state.supabase_admin = supabase
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), supabase


# --- Private profile-level feature access ---


def _feature_state(opted_in=False, effective=False):
    return {"dice_live_referee": {"opted_in": opted_in, "effective": effective}}


def test_my_features_defaults_off_when_access_is_missing():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.get("/dice/me/features", headers=_headers(HOST_TOKEN))

    assert response.status_code == 200
    assert response.json() == _feature_state()


def test_profile_access_is_effective_without_a_global_gate():
    client, _ = _build_client(
        profiles=ROSTER,
        auth_users=AUTH_USERS,
        feature_access=[{"user_id": "u1", "feature": "dice_live_referee", "enabled": True}],
    )

    response = client.get("/dice/me/features", headers=_headers(HOST_TOKEN))

    assert response.json() == _feature_state(opted_in=True, effective=True)


def test_disabled_profile_access_stays_off():
    client, _ = _build_client(
        profiles=ROSTER,
        auth_users=AUTH_USERS,
        feature_access=[{"user_id": "u1", "feature": "dice_live_referee", "enabled": False}],
    )

    response = client.get("/dice/me/features", headers=_headers(HOST_TOKEN))

    assert response.json() == _feature_state()


def test_profile_access_enables_feature():
    client, _ = _build_client(
        profiles=ROSTER,
        auth_users=AUTH_USERS,
        feature_access=[{"user_id": "u1", "feature": "dice_live_referee", "enabled": True}],
    )

    response = client.get("/dice/me/features", headers=_headers(HOST_TOKEN))

    assert response.json() == _feature_state(opted_in=True, effective=True)


def test_user_can_enable_and_disable_their_own_feature():
    client, supabase = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    enabled = client.put(
        "/dice/me/features/dice_live_referee",
        headers=_headers(HOST_TOKEN),
        json={"enabled": True},
    )
    disabled = client.put(
        "/dice/me/features/dice_live_referee",
        headers=_headers(HOST_TOKEN),
        json={"enabled": False},
    )

    assert enabled.status_code == 200
    assert enabled.json() == _feature_state(opted_in=True, effective=True)
    assert disabled.status_code == 200
    assert disabled.json() == _feature_state()
    assert supabase.tables["dice_feature_access"] == [
        {"user_id": "u1", "feature": "dice_live_referee", "enabled": False}
    ]


def test_user_self_update_is_immediately_effective():
    client, _ = _build_client(
        profiles=ROSTER,
        auth_users=AUTH_USERS,
    )

    response = client.put(
        "/dice/me/features/dice_live_referee",
        headers=_headers(HOST_TOKEN),
        json={"enabled": True},
    )

    assert response.json() == _feature_state(opted_in=True, effective=True)


def test_user_cannot_target_another_profile_through_self_update():
    client, supabase = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.put(
        "/dice/me/features/dice_live_referee",
        headers=_headers(HOST_TOKEN),
        json={"enabled": True, "user_id": "u4"},
    )

    assert response.status_code == 422
    assert supabase.tables["dice_feature_access"] == []


def test_unknown_self_feature_is_rejected():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.put(
        "/dice/me/features/future_flag",
        headers=_headers(HOST_TOKEN),
        json={"enabled": True},
    )

    assert response.status_code == 422


def test_unknown_feature_mutation_is_rejected():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.put(
        "/dice/admin/features/u1",
        headers=_headers(ADMIN_TOKEN),
        json={"feature": "future_flag", "enabled": True},
    )

    assert response.status_code == 422


def test_non_admin_cannot_mutate_feature_access():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.put(
        "/dice/admin/features/u4",
        headers=_headers(HOST_TOKEN),
        json={"feature": "dice_live_referee", "enabled": True},
    )

    assert response.status_code == 403


def test_admin_can_enable_profile_access():
    client, supabase = _build_client(
        profiles=ROSTER,
        auth_users=AUTH_USERS,
    )

    response = client.put(
        "/dice/admin/features/u1",
        headers=_headers(ADMIN_TOKEN),
        json={"feature": "dice_live_referee", "enabled": True},
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "u1",
        "feature": "dice_live_referee",
        "state": {"opted_in": True, "effective": True},
    }
    assert supabase.tables["dice_feature_access"] == [
        {"user_id": "u1", "feature": "dice_live_referee", "enabled": True}
    ]


def test_user_only_receives_their_own_effective_features():
    client, _ = _build_client(
        profiles=ROSTER,
        auth_users=AUTH_USERS,
        feature_access=[{"user_id": "u4", "feature": "dice_live_referee", "enabled": True}],
    )

    host_response = client.get("/dice/me/features", headers=_headers(HOST_TOKEN))
    other_response = client.get("/dice/me/features", headers=_headers(OTHER_TOKEN))

    assert host_response.json() == _feature_state()
    assert other_response.json() == _feature_state(opted_in=True, effective=True)


def test_private_access_does_not_change_public_profile_payload():
    client, _ = _build_client(
        profiles=ROSTER,
        auth_users=AUTH_USERS,
        feature_access=[{"user_id": "u1", "feature": "dice_live_referee", "enabled": True}],
    )

    response = client.get("/dice/profiles/u1")

    assert response.status_code == 200
    assert "dice_live_referee" not in response.json()
    assert "features" not in response.json()


# --- Regression: GET /dice/profiles/search must accept the limit every ---
# --- picker in the app actually requests (LogMatch and the tournament   ---
# --- host picker both fetch the whole roster in one shot).              ---


def test_profile_search_accepts_the_full_roster_limit():
    client, _ = _build_client(profiles=ROSTER)

    response = client.get("/dice/profiles/search?q=&limit=100")

    assert response.status_code == 200
    names = {p["display_name"] for p in response.json()}
    assert names == set(ROSTER_NAMES)


def test_profile_search_still_rejects_unreasonable_limits():
    client, _ = _build_client(profiles=ROSTER)

    response = client.get("/dice/profiles/search?limit=100000")

    assert response.status_code == 422


def test_profile_search_filters_by_name_case_insensitively():
    client, _ = _build_client(profiles=ROSTER)

    response = client.get("/dice/profiles/search?q=warner")

    assert response.status_code == 200
    names = [p["display_name"] for p in response.json()]
    assert names == ["Warner Tsang"]


def test_new_profile_initializes_canonical_rating_state():
    client, supabase = _build_client(profiles=[], auth_users=AUTH_USERS)

    response = client.get("/dice/me", headers=_headers(HOST_TOKEN))

    assert response.status_code == 200
    assert response.json()["elo_model_version"] == "1.1.0"
    assert response.json()["rating_deviation"] == 350.0
    assert supabase.cache_clear_count == 0


# --- ELO leaderboard placement filter ---


def test_leaderboard_excludes_players_still_in_placements_by_default():
    established = _profile("u1", "Andrew S")
    established["elo_rating"] = 1600
    established["ranked_games_played"] = 3
    provisional = _profile("u2", "Aziz Rahman")
    provisional["elo_rating"] = 1700
    provisional["ranked_games_played"] = 2

    client, _ = _build_client(profiles=[established, provisional])

    response = client.get("/dice/leaderboard/elo?limit=500")

    assert response.status_code == 200
    names = [p["display_name"] for p in response.json()]
    assert names == ["Andrew S"]


def test_leaderboard_with_include_provisional_lists_everyone_flagged():
    established = _profile("u1", "Andrew S")
    established["elo_rating"] = 1600
    established["ranked_games_played"] = 3
    provisional = _profile("u2", "Aziz Rahman")
    provisional["elo_rating"] = 1700
    provisional["ranked_games_played"] = 2

    client, _ = _build_client(profiles=[established, provisional])

    response = client.get("/dice/leaderboard/elo?limit=500&include_provisional=true")

    assert response.status_code == 200
    body = response.json()
    by_name = {p["display_name"]: p for p in body}
    assert set(by_name) == {"Andrew S", "Aziz Rahman"}
    assert by_name["Andrew S"]["is_provisional"] is False
    assert by_name["Aziz Rahman"]["is_provisional"] is True
    # Established players are always listed ahead of provisional ones,
    # regardless of the provisional player's (unproven) ELO.
    assert [p["display_name"] for p in body] == ["Andrew S", "Aziz Rahman"]


def test_leaderboard_uses_deterministic_competition_ranks_for_ties():
    rows = []
    for user_id, name, rating in (
        ("u3", "Charlie", 1500),
        ("u2", "Bravo", 1600),
        ("u1", "Alpha", 1600),
        ("u4", "Delta", 1400),
    ):
        profile = _profile(user_id, name)
        profile.update({"elo_rating": rating, "ranked_games_played": 3})
        rows.append(profile)
    client, _ = _build_client(profiles=rows)

    first = client.get("/dice/leaderboard/elo?limit=500").json()
    second = client.get("/dice/leaderboard/elo?limit=500").json()

    assert first == second
    assert [(row["display_name"], row["rank"], row["is_tied"]) for row in first] == [
        ("Alpha", 1, True),
        ("Bravo", 1, True),
        ("Charlie", 3, False),
        ("Delta", 4, False),
    ]


def test_leaderboard_detects_a_tie_crossing_the_response_limit():
    rows = []
    for index, rating in enumerate((1700, 1600, 1500, 1400, 1300, 1300), start=1):
        profile = _profile(f"u{index}", f"Player {index}")
        profile.update({"elo_rating": rating, "ranked_games_played": 3})
        rows.append(profile)
    client, _ = _build_client(profiles=rows)

    body = client.get("/dice/leaderboard/elo?limit=5").json()

    assert len(body) == 5
    assert body[-1]["rank"] == 5
    assert body[-1]["is_tied"] is True


def test_profile_flags_provisional_elo_with_games_remaining():
    provisional = _profile("u1", "Andrew S")
    provisional["ranked_games_played"] = 1
    client, _ = _build_client(profiles=[provisional])

    response = client.get("/dice/profiles/u1")

    assert response.status_code == 200
    body = response.json()
    assert body["is_provisional"] is True
    assert body["placement_games_remaining"] == 2


def test_rating_progress_is_authoritative_and_tracks_personal_best():
    client, _ = _build_client(profiles=deepcopy(ROSTER), auth_users=AUTH_USERS)
    for team1_score, team2_score in ((11, 7), (7, 11), (11, 8), (11, 9)):
        response = client.post(
            "/dice/games",
            json={"ranked": True, "team1_score": team1_score, "team2_score": team2_score,
                  "players": _game_players(["u1", "u2"], ["u3", "u4"])},
            headers=_headers(HOST_TOKEN),
        )
        assert response.status_code == 200

    body = client.get("/dice/profiles/u1/rating-progress").json()

    assert body["rating_system_version"] == "1.1.0"
    assert body["current_rating"] == body["history"][-1]["rating_after"]
    assert body["last_delta"] == body["history"][-1]["delta"]
    assert body["personal_best"] == max(point["rating_after"] for point in body["history"])
    assert body["is_provisional"] is False
    assert body["current_rank"] is not None
    assert len(body["history"]) == 4


def test_rating_progress_returns_404_for_unknown_profile():
    client, _ = _build_client(profiles=ROSTER)
    assert client.get("/dice/profiles/missing/rating-progress").status_code == 404


def test_rating_progress_rejects_discontinuous_or_mixed_profile_snapshots():
    client, supabase = _build_client(profiles=deepcopy(ROSTER), auth_users=AUTH_USERS)
    response = client.post(
        "/dice/games",
        json={"ranked": True, "team1_score": 11, "team2_score": 7,
              "players": _game_players(["u1", "u2"], ["u3", "u4"])},
        headers=_headers(HOST_TOKEN),
    )
    assert response.status_code == 200
    original_elo_before = supabase.tables["dice_game_players"][0]["elo_before"]
    supabase.tables["dice_game_players"][0]["elo_before"] += 1
    assert client.get("/dice/profiles/u1/rating-progress").status_code == 503

    supabase.tables["dice_game_players"][0]["elo_before"] = original_elo_before
    other_profile = next(row for row in supabase.tables["dice_profiles"] if row["user_id"] == "u2")
    other_profile["elo_rating"] += 1
    assert client.get("/dice/profiles/u1/rating-progress").status_code == 503


def test_rating_progress_uses_canonical_tiebreak_order_for_equal_play_times():
    first = _profile("u1", "Alpha")
    second = _profile("u2", "Bravo")
    first.update({"elo_rating": 1520, "ranked_games_played": 2})
    second.update({"elo_rating": 1480, "ranked_games_played": 2})
    client, supabase = _build_client(profiles=[first, second])
    played_at = "2026-01-01T12:00:00+00:00"
    supabase.tables["dice_games"] = [
        {"id": "g2", "ranked": True, "winner_team": 1, "team1_score": 11, "team2_score": 9,
         "played_at": played_at, "created_at": "2026-01-01T12:02:00+00:00", "live_result_state": None},
        {"id": "g1", "ranked": True, "winner_team": 1, "team1_score": 11, "team2_score": 9,
         "played_at": played_at, "created_at": "2026-01-01T12:01:00+00:00", "live_result_state": None},
    ]
    supabase.tables["dice_game_players"] = [
        {"id": "p3", "game_id": "g2", "user_id": "u1", "team": 1, "elo_before": 1510, "elo_after": 1520},
        {"id": "p4", "game_id": "g2", "user_id": "u2", "team": 2, "elo_before": 1490, "elo_after": 1480},
        {"id": "p1", "game_id": "g1", "user_id": "u1", "team": 1, "elo_before": 1500, "elo_after": 1510},
        {"id": "p2", "game_id": "g1", "user_id": "u2", "team": 2, "elo_before": 1500, "elo_after": 1490},
    ]

    body = client.get("/dice/profiles/u1/rating-progress").json()

    assert [point["game_id"] for point in body["history"]] == ["g1", "g2"]


def test_profile_elo_is_no_longer_provisional_after_placement_games():
    established = _profile("u1", "Andrew S")
    established["ranked_games_played"] = 3
    client, _ = _build_client(profiles=[established])

    response = client.get("/dice/profiles/u1")

    assert response.status_code == 200
    body = response.json()
    assert body["is_provisional"] is False
    assert body["placement_games_remaining"] == 0


# --- Tournament host/enroll flows ---


def test_only_admin_can_create_tournament():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": []},
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 403


def test_create_tournament_defaults_host_to_creator_and_stores_description():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "description": "BYO cups"},
        headers=_headers(ADMIN_TOKEN),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Summer Bash"
    assert body["description"] == "BYO cups"
    assert [h["user_id"] for h in body["hosts"]] == ["u3"]
    assert body["enrolled_players"] == []


def test_adding_a_host_makes_them_appear_on_the_tournament():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u3"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    response = client.put(
        f"/dice/tournaments/{created['id']}",
        json={"host_user_ids": ["u3", "u7"]},  # add Warner Tsang
        headers=_headers(ADMIN_TOKEN),
    )

    assert response.status_code == 200
    hosts = {h["display_name"] for h in response.json()["hosts"]}
    assert hosts == {"Jason Keung", "Warner Tsang"}


def test_cannot_add_a_host_without_an_existing_profile():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.post(
        "/dice/tournaments",
        json={
            "name": "Summer Bash",
            "starts_at": "2026-08-15T22:00:00Z",
            "host_user_ids": ["no-such-user"],
        },
        headers=_headers(ADMIN_TOKEN),
    )

    assert response.status_code == 400


def test_only_host_or_admin_can_edit_tournament():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    forbidden = client.put(
        f"/dice/tournaments/{created['id']}",
        json={"name": "Hacked"},
        headers=_headers(OTHER_TOKEN),
    )
    assert forbidden.status_code == 403

    allowed = client.put(
        f"/dice/tournaments/{created['id']}",
        json={"name": "Renamed by host"},
        headers=_headers(HOST_TOKEN),
    )
    assert allowed.status_code == 200
    assert allowed.json()["name"] == "Renamed by host"


def test_updating_name_preserves_existing_description():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "description": "BYO cups"},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    response = client.put(
        f"/dice/tournaments/{created['id']}",
        json={"name": "Summer Bash II"},
        headers=_headers(ADMIN_TOKEN),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Summer Bash II"
    assert body["description"] == "BYO cups"


def test_enroll_and_unenroll():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z"},
        headers=_headers(ADMIN_TOKEN),
    ).json()
    tournament_id = created["id"]

    enrolled = client.post(f"/dice/tournaments/{tournament_id}/enroll", headers=_headers(OTHER_TOKEN))
    assert enrolled.status_code == 200
    assert [p["user_id"] for p in enrolled.json()["enrolled_players"]] == ["u4"]

    unenrolled = client.delete(f"/dice/tournaments/{tournament_id}/enroll", headers=_headers(OTHER_TOKEN))
    assert unenrolled.status_code == 200
    assert unenrolled.json()["enrolled_players"] == []


# --- Hosts adding people / scheduled matches ---


def test_host_can_add_someone_else_to_the_tournament():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()
    tournament_id = created["id"]

    response = client.post(
        f"/dice/tournaments/{tournament_id}/enroll",
        json={"user_id": "u7"},
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 200
    assert [p["user_id"] for p in response.json()["enrolled_players"]] == ["u7"]


def test_non_host_cannot_add_someone_else_to_the_tournament():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    response = client.post(
        f"/dice/tournaments/{created['id']}/enroll",
        json={"user_id": "u6"},
        headers=_headers(OTHER_TOKEN),
    )

    assert response.status_code == 403


def test_add_scheduled_match_with_a_tbd_slot():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    response = client.post(
        f"/dice/tournaments/{created['id']}/matches",
        json={"label": "Round 1", "team1_player_ids": ["u1", "u7"], "team2_player_ids": ["u4", None]},
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 200
    match = response.json()["scheduled_matches"][0]
    assert match["label"] == "Round 1"
    assert [p["display_name"] for p in match["team1"]] == ["Andrew S", "Warner Tsang"]
    assert [p["user_id"] for p in match["team2"]] == ["u4", None]
    assert match["team2"][1]["display_name"] == "TBD"


def test_add_scheduled_match_supports_1v1():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    response = client.post(
        f"/dice/tournaments/{created['id']}/matches",
        json={"label": "Singles Round 1", "team1_player_ids": ["u1"], "team2_player_ids": ["u4"]},
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 200
    match = response.json()["scheduled_matches"][0]
    assert [p["user_id"] for p in match["team1"]] == ["u1"]
    assert [p["user_id"] for p in match["team2"]] == ["u4"]


def test_scheduled_match_rejects_mismatched_team_sizes():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    response = client.post(
        f"/dice/tournaments/{created['id']}/matches",
        json={"team1_player_ids": ["u1"], "team2_player_ids": ["u4", None]},
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 422


def test_scheduled_match_rejects_more_than_two_slots():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    response = client.post(
        f"/dice/tournaments/{created['id']}/matches",
        json={"team1_player_ids": ["u1", "u2", "u3"], "team2_player_ids": ["u4", "u5", "u6"]},
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 422


def test_only_host_or_admin_can_add_a_scheduled_match():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    response = client.post(
        f"/dice/tournaments/{created['id']}/matches",
        json={"team1_player_ids": [None, None], "team2_player_ids": [None, None]},
        headers=_headers(OTHER_TOKEN),
    )

    assert response.status_code == 403


def test_update_scheduled_match_fills_in_a_tbd_slot():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()
    tournament_id = created["id"]

    added = client.post(
        f"/dice/tournaments/{tournament_id}/matches",
        json={"team1_player_ids": ["u1", "u7"], "team2_player_ids": ["u4", None]},
        headers=_headers(HOST_TOKEN),
    ).json()
    match_id = added["scheduled_matches"][0]["id"]

    response = client.put(
        f"/dice/tournaments/{tournament_id}/matches/{match_id}",
        json={"team1_player_ids": ["u1", "u7"], "team2_player_ids": ["u4", "u6"]},
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 200
    match = response.json()["scheduled_matches"][0]
    assert match["id"] == match_id
    assert [p["user_id"] for p in match["team2"]] == ["u4", "u6"]


def test_delete_scheduled_match():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()
    tournament_id = created["id"]

    added = client.post(
        f"/dice/tournaments/{tournament_id}/matches",
        json={"team1_player_ids": [None, None], "team2_player_ids": [None, None]},
        headers=_headers(HOST_TOKEN),
    ).json()
    match_id = added["scheduled_matches"][0]["id"]

    response = client.delete(
        f"/dice/tournaments/{tournament_id}/matches/{match_id}",
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 200
    assert response.json()["scheduled_matches"] == []


def test_cannot_schedule_a_match_with_an_unknown_player():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    created = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()

    response = client.post(
        f"/dice/tournaments/{created['id']}/matches",
        json={"team1_player_ids": ["no-such-user", None], "team2_player_ids": [None, None]},
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 400


# --- Finalists and the bracket ---


def test_add_and_remove_finalists():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]

    response = client.post(
        f"/dice/tournaments/{tournament_id}/finalists",
        json={"user_id": "u1"},
        headers=_headers(HOST_TOKEN),
    )
    assert response.status_code == 200
    finalists = response.json()["finalists"]
    assert [f["user_id"] for f in finalists] == ["u1"]
    assert finalists[0]["display_name"] == "Andrew S"

    response = client.delete(
        f"/dice/tournaments/{tournament_id}/finalists/u1",
        headers=_headers(HOST_TOKEN),
    )
    assert response.status_code == 200
    assert response.json()["finalists"] == []


def test_only_host_or_admin_can_add_a_finalist():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]

    response = client.post(
        f"/dice/tournaments/{tournament_id}/finalists",
        json={"user_id": "u1"},
        headers=_headers(OTHER_TOKEN),
    )
    assert response.status_code == 403


def test_cannot_add_the_same_finalist_twice_or_more_than_eight():
    client, _ = _build_client(profiles=ROSTER + [_profile("u9", "Extra Player")], auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]

    dup = client.post(
        f"/dice/tournaments/{tournament_id}/finalists",
        json={"user_id": "u1"},
        headers=_headers(HOST_TOKEN),
    )
    assert dup.status_code == 200
    dup_again = client.post(
        f"/dice/tournaments/{tournament_id}/finalists",
        json={"user_id": "u1"},
        headers=_headers(HOST_TOKEN),
    )
    assert dup_again.status_code == 400

    for uid in ["u2", "u3", "u4", "u5", "u6", "u7", "u8"]:
        client.post(
            f"/dice/tournaments/{tournament_id}/finalists",
            json={"user_id": uid},
            headers=_headers(HOST_TOKEN),
        )
    ninth = client.post(
        f"/dice/tournaments/{tournament_id}/finalists",
        json={"user_id": "u9"},
        headers=_headers(HOST_TOKEN),
    )
    assert ninth.status_code == 400


def _add_finalists(client, tournament_id, user_ids):
    for uid in user_ids:
        response = client.post(
            f"/dice/tournaments/{tournament_id}/finalists",
            json={"user_id": uid},
            headers=_headers(HOST_TOKEN),
        )
        assert response.status_code == 200
    return response.json()


def _set_bracket_teams(client, tournament_id, team1, team2, team3, team4):
    response = client.put(
        f"/dice/tournaments/{tournament_id}/bracket/teams",
        json={
            "team1_player_ids": team1,
            "team2_player_ids": team2,
            "team3_player_ids": team3,
            "team4_player_ids": team4,
        },
        headers=_headers(HOST_TOKEN),
    )
    assert response.status_code == 200
    return response.json()


def test_finalists_start_with_no_bracket_teams_assigned():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]

    tournament = _add_finalists(client, tournament_id, ["u1", "u2", "u3", "u4", "u5", "u6", "u7", "u8"])
    bracket = tournament["bracket"]

    # Adding finalists only builds the pool — it doesn't guess team
    # pairings, so every bracket slot starts open until teams are formed.
    assert all(
        p["display_name"] == "TBD"
        for match in (bracket["semi1"], bracket["semi2"], bracket["final"])
        for p in match["team1"] + match["team2"]
    )
    assert bracket["champion"] == []


def test_forming_bracket_teams_from_the_finalist_pool():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2", "u3", "u4", "u5", "u6", "u7", "u8"])

    # Deliberately out of finalist-entry-order, to prove teams are explicit
    # rather than inferred from the order finalists were added in. Team 1 &
    # Team 3 are the bracket's left side (semi1); Team 2 & Team 4 the right
    # side (semi2).
    tournament = _set_bracket_teams(
        client, tournament_id, ["u4", "u1"], ["u2", "u3"], ["u8", "u5"], ["u6", "u7"]
    )
    bracket = tournament["bracket"]

    assert [p["user_id"] for p in bracket["semi1"]["team1"]] == ["u4", "u1"]
    assert [p["user_id"] for p in bracket["semi1"]["team2"]] == ["u8", "u5"]
    assert [p["user_id"] for p in bracket["semi2"]["team1"]] == ["u2", "u3"]
    assert [p["user_id"] for p in bracket["semi2"]["team2"]] == ["u6", "u7"]


def test_cannot_assign_a_non_finalist_to_a_bracket_team():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2", "u3"])

    response = client.put(
        f"/dice/tournaments/{tournament_id}/bracket/teams",
        json={
            "team1_player_ids": ["u1", "u2"],
            # u9 was never added as a finalist.
            "team2_player_ids": ["u3", "u9"],
            "team3_player_ids": [None, None],
            "team4_player_ids": [None, None],
        },
        headers=_headers(HOST_TOKEN),
    )
    assert response.status_code == 400


def test_cannot_assign_the_same_finalist_to_two_bracket_teams():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2", "u3"])

    response = client.put(
        f"/dice/tournaments/{tournament_id}/bracket/teams",
        json={
            "team1_player_ids": ["u1", "u2"],
            "team2_player_ids": ["u2", "u3"],
            "team3_player_ids": [None, None],
            "team4_player_ids": [None, None],
        },
        headers=_headers(HOST_TOKEN),
    )
    # Caught by the request schema's own validator, before it reaches the
    # repository — same as the analogous check on CreateGameRequest.
    assert response.status_code == 422


def test_forming_1v1_bracket_teams_and_resolving_to_a_champion():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2", "u3", "u4"])

    tournament = _set_bracket_teams(client, tournament_id, ["u1"], ["u2"], ["u3"], ["u4"])
    bracket = tournament["bracket"]
    assert [p["user_id"] for p in bracket["semi1"]["team1"]] == ["u1"]
    assert [p["user_id"] for p in bracket["semi1"]["team2"]] == ["u3"]
    assert [p["user_id"] for p in bracket["semi2"]["team1"]] == ["u2"]
    assert [p["user_id"] for p in bracket["semi2"]["team2"]] == ["u4"]

    semi1_game_id = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "tournament_id": tournament_id,
            "players": _game_players_1v1("u1", "u3"),
        },
        headers=_headers(HOST_TOKEN),
    ).json()["id"]
    client.post(
        f"/dice/tournaments/{tournament_id}/bracket/semi1/resolve",
        json={"game_id": semi1_game_id},
        headers=_headers(HOST_TOKEN),
    )

    semi2_game_id = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 5,
            "team2_score": 11,
            "tournament_id": tournament_id,
            "players": _game_players_1v1("u2", "u4"),
        },
        headers=_headers(HOST_TOKEN),
    ).json()["id"]
    resolve2 = client.post(
        f"/dice/tournaments/{tournament_id}/bracket/semi2/resolve",
        json={"game_id": semi2_game_id},
        headers=_headers(HOST_TOKEN),
    )
    final_before = resolve2.json()["bracket"]["final"]
    assert [p["user_id"] for p in final_before["team1"]] == ["u1"]
    assert [p["user_id"] for p in final_before["team2"]] == ["u4"]

    final_game_id = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 9,
            "tournament_id": tournament_id,
            "players": _game_players_1v1("u1", "u4"),
        },
        headers=_headers(HOST_TOKEN),
    ).json()["id"]
    final_resolve = client.post(
        f"/dice/tournaments/{tournament_id}/bracket/final/resolve",
        json={"game_id": final_game_id},
        headers=_headers(HOST_TOKEN),
    )

    champion_ids = {p["user_id"] for p in final_resolve.json()["bracket"]["champion"]}
    assert champion_ids == {"u1"}


def test_bracket_teams_reject_mixed_1v1_and_2v2_format():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2", "u3", "u4"])

    response = client.put(
        f"/dice/tournaments/{tournament_id}/bracket/teams",
        json={
            "team1_player_ids": ["u1"],
            "team2_player_ids": ["u2", "u4"],
            "team3_player_ids": ["u3"],
            "team4_player_ids": [None],
        },
        headers=_headers(HOST_TOKEN),
    )
    assert response.status_code == 422


def test_only_host_or_admin_can_form_bracket_teams():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2"])

    response = client.put(
        f"/dice/tournaments/{tournament_id}/bracket/teams",
        json={
            "team1_player_ids": ["u1", "u2"],
            "team2_player_ids": [None, None],
            "team3_player_ids": [None, None],
            "team4_player_ids": [None, None],
        },
        headers=_headers(OTHER_TOKEN),
    )
    assert response.status_code == 403


def test_resolving_semis_advances_the_winning_team_into_the_final_and_crowns_a_champion():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2", "u3", "u4", "u5", "u6", "u7", "u8"])
    # Team 1 & Team 3 form the left side (semi1: u1/u2 vs u3/u4); Team 2 &
    # Team 4 form the right side (semi2: u5/u6 vs u7/u8).
    _set_bracket_teams(client, tournament_id, ["u1", "u2"], ["u5", "u6"], ["u3", "u4"], ["u7", "u8"])

    semi1_game_id = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "tournament_id": tournament_id,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    ).json()["id"]
    resolve1 = client.post(
        f"/dice/tournaments/{tournament_id}/bracket/semi1/resolve",
        json={"game_id": semi1_game_id},
        headers=_headers(HOST_TOKEN),
    )
    assert resolve1.status_code == 200
    bracket = resolve1.json()["bracket"]
    assert bracket["semi1"]["winner_team"] == 1
    assert [p["user_id"] for p in bracket["final"]["team1"]] == ["u1", "u2"]
    assert all(p["display_name"] == "TBD" for p in bracket["final"]["team2"])

    semi2_game_id = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 5,
            "team2_score": 11,
            "tournament_id": tournament_id,
            "players": _game_players(["u5", "u6"], ["u7", "u8"]),
        },
        headers=_headers(HOST_TOKEN),
    ).json()["id"]
    client.post(
        f"/dice/tournaments/{tournament_id}/bracket/semi2/resolve",
        json={"game_id": semi2_game_id},
        headers=_headers(HOST_TOKEN),
    )

    final_game_id = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 9,
            "tournament_id": tournament_id,
            "players": _game_players(["u1", "u2"], ["u7", "u8"]),
        },
        headers=_headers(HOST_TOKEN),
    ).json()["id"]
    final_resolve = client.post(
        f"/dice/tournaments/{tournament_id}/bracket/final/resolve",
        json={"game_id": final_game_id},
        headers=_headers(HOST_TOKEN),
    )

    tournament = final_resolve.json()
    champion_ids = {p["user_id"] for p in tournament["bracket"]["champion"]}
    assert champion_ids == {"u1", "u2"}
    # Bracket games are kept out of the generic group-stage results list.
    assert tournament["completed_games"] == []


def test_cannot_resolve_a_bracket_slot_with_a_game_from_another_tournament():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    other_tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Fall Classic", "starts_at": "2026-10-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2", "u3", "u4"])

    stray_game_id = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "tournament_id": other_tournament_id,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    ).json()["id"]

    response = client.post(
        f"/dice/tournaments/{tournament_id}/bracket/semi1/resolve",
        json={"game_id": stray_game_id},
        headers=_headers(HOST_TOKEN),
    )
    assert response.status_code == 400


def test_removing_a_finalist_opens_their_bracket_slot_and_clears_that_results():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2", "u3", "u4"])
    _set_bracket_teams(client, tournament_id, ["u1", "u2"], [None, None], ["u3", "u4"], [None, None])

    semi1_game_id = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "tournament_id": tournament_id,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    ).json()["id"]
    client.post(
        f"/dice/tournaments/{tournament_id}/bracket/semi1/resolve",
        json={"game_id": semi1_game_id},
        headers=_headers(HOST_TOKEN),
    )

    response = client.delete(
        f"/dice/tournaments/{tournament_id}/finalists/u2",
        headers=_headers(HOST_TOKEN),
    )
    tournament = response.json()
    assert [f["user_id"] for f in tournament["finalists"]] == ["u1", "u3", "u4"]
    bracket = tournament["bracket"]
    # u2's specific slot opens up — their teammate u1 stays put — and the
    # semi1 result is dropped since it no longer reflects who's on team1.
    assert [p["user_id"] for p in bracket["semi1"]["team1"]] == ["u1", None]
    assert [p["user_id"] for p in bracket["semi1"]["team2"]] == ["u3", "u4"]
    assert bracket["semi1"]["winner_team"] is None


def test_removing_a_finalist_not_on_a_bracket_team_leaves_the_bracket_untouched():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    _add_finalists(client, tournament_id, ["u1", "u2", "u3", "u4", "u5"])
    _set_bracket_teams(client, tournament_id, ["u1", "u2"], [None, None], ["u3", "u4"], [None, None])

    semi1_game_id = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "tournament_id": tournament_id,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    ).json()["id"]
    client.post(
        f"/dice/tournaments/{tournament_id}/bracket/semi1/resolve",
        json={"game_id": semi1_game_id},
        headers=_headers(HOST_TOKEN),
    )

    # u5 is a finalist but was never assigned to a bracket team.
    response = client.delete(
        f"/dice/tournaments/{tournament_id}/finalists/u5",
        headers=_headers(HOST_TOKEN),
    )
    bracket = response.json()["bracket"]
    assert [p["user_id"] for p in bracket["semi1"]["team1"]] == ["u1", "u2"]
    assert bracket["semi1"]["winner_team"] == 1


# --- Completed tournament games (logged matches tagged with tournament_id) ---


def _game_players(team1, team2):
    return [
        {"user_id": team1[0], "team": 1, "self_sinks": 0},
        {"user_id": team1[1], "team": 1, "self_sinks": 0},
        {"user_id": team2[0], "team": 2, "self_sinks": 0},
        {"user_id": team2[1], "team": 2, "self_sinks": 0},
    ]


def _game_players_1v1(p1, p2):
    return [
        {"user_id": p1, "team": 1, "self_sinks": 0},
        {"user_id": p2, "team": 2, "self_sinks": 0},
    ]


def test_logging_a_match_with_a_tournament_id_shows_up_as_a_completed_tournament_game():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]

    game = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "tournament_id": tournament_id,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    assert game.status_code == 200
    assert game.json()["tournament_id"] == tournament_id

    tournament = client.get(f"/dice/tournaments/{tournament_id}").json()
    assert len(tournament["completed_games"]) == 1
    completed = tournament["completed_games"][0]
    assert completed["id"] == game.json()["id"]
    assert completed["winner_team"] == 1
    team1_names = {p["display_name"] for p in completed["players"] if p["team"] == 1}
    assert team1_names == {"Andrew S", "Aziz Rahman"}


def test_completed_game_reconciles_matching_scheduled_match_without_client_delete():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    scheduled = client.post(
        f"/dice/tournaments/{tournament_id}/matches",
        json={"team1_player_ids": ["u1", "u2"], "team2_player_ids": ["u3", "u4"]},
        headers=_headers(HOST_TOKEN),
    )
    assert scheduled.status_code == 200

    game = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "tournament_id": tournament_id,
            "players": _game_players(["u2", "u1"], ["u4", "u3"]),
        },
        headers=_headers(OTHER_TOKEN),
    )
    assert game.status_code == 200

    # Simulates a lost/failed client-side DELETE. Repeated reads remain
    # stable and do not mutate the stored schedule.
    first = client.get(f"/dice/tournaments/{tournament_id}").json()
    second = client.get(f"/dice/tournaments/{tournament_id}").json()
    assert first["scheduled_matches"] == []
    assert second["scheduled_matches"] == []
    assert len(first["completed_games"]) == 1


def test_completed_1v1_game_reconciles_matching_1v1_scheduled_match():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]
    scheduled = client.post(
        f"/dice/tournaments/{tournament_id}/matches",
        json={"team1_player_ids": ["u1"], "team2_player_ids": ["u2"]},
        headers=_headers(HOST_TOKEN),
    )
    assert scheduled.status_code == 200

    game = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "tournament_id": tournament_id,
            "players": _game_players_1v1("u1", "u2"),
        },
        headers=_headers(OTHER_TOKEN),
    )
    assert game.status_code == 200

    tournament = client.get(f"/dice/tournaments/{tournament_id}").json()
    assert tournament["scheduled_matches"] == []
    assert len(tournament["completed_games"]) == 1


def test_a_game_not_tied_to_a_tournament_does_not_appear_in_its_completed_games():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    tournament_id = client.post(
        "/dice/tournaments",
        json={"name": "Summer Bash", "starts_at": "2026-08-15T22:00:00Z", "host_user_ids": ["u1"]},
        headers=_headers(ADMIN_TOKEN),
    ).json()["id"]

    client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    tournament = client.get(f"/dice/tournaments/{tournament_id}").json()
    assert tournament["completed_games"] == []


def test_cannot_log_a_match_against_an_unknown_tournament():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "tournament_id": "no-such-tournament",
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 400


# --- 1v1 matches ---


def test_can_log_a_1v1_match_with_two_players():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players_1v1("u1", "u2"),
        },
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 200
    game = response.json()
    assert len(game["players"]) == 2
    assert game["winner_team"] == 1


def test_legacy_post_game_remains_readable_without_live_result_state():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players_1v1("u1", "u2"),
        },
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 200
    assert response.json()["winner_team"] == 1


def test_a_ranked_1v1_match_updates_elo_for_both_players():
    client, supabase = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    game = client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players_1v1("u1", "u2"),
        },
        headers=_headers(HOST_TOKEN),
    ).json()

    by_user = {p["user_id"]: p for p in game["players"]}
    assert by_user["u1"]["elo_before"] == 1500
    assert by_user["u1"]["elo_after"] > 1500
    assert by_user["u2"]["elo_before"] == 1500
    assert by_user["u2"]["elo_after"] < 1500

    assert by_user["u1"]["rating_deviation_before"] == 350.0
    assert by_user["u1"]["rating_deviation_after"] == 297.5

    winner_profile = client.get("/dice/profiles/u1").json()
    assert winner_profile["elo_rating"] == by_user["u1"]["elo_after"]
    assert winner_profile["elo_model_version"] == "1.1.0"
    assert winner_profile["rating_deviation"] == 297.5
    assert winner_profile["wins"] == 1

@pytest.mark.parametrize("failure", ["before", "after"])
def test_canonical_mutation_failure_rolls_back_the_entire_create(failure):
    client, supabase = _build_client(
        profiles=deepcopy(ROSTER),
        auth_users=AUTH_USERS,
        raise_server_exceptions=False,
    )
    before = deepcopy(supabase.tables)
    supabase.rating_mutation_failure = failure
    response = client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players_1v1("u1", "u2"),
        },
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 500
    assert supabase.tables == before


def test_dropped_create_response_reconciles_without_a_second_game():
    client, supabase = _build_client(profiles=deepcopy(ROSTER), auth_users=AUTH_USERS)
    supabase.rating_mutation_failure = "after_commit"

    response = client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players_1v1("u1", "u2"),
        },
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 200
    assert len(supabase.tables["dice_games"]) == 1
    assert response.json()["id"] == supabase.tables["dice_games"][0]["id"]


def test_create_reuses_caller_idempotency_key_after_request_process_loss(monkeypatch):
    client, supabase = _build_client(profiles=deepcopy(ROSTER), auth_users=AUTH_USERS)
    notifications = []
    monkeypatch.setattr(
        "dice.routes.notify_ranked_game",
        lambda *_args: notifications.append("sent"),
    )
    payload = {
        "ranked": True,
        "team1_score": 11,
        "team2_score": 7,
        "players": _game_players_1v1("u1", "u2"),
    }
    headers = {
        **_headers(HOST_TOKEN),
        "Idempotency-Key": "65000000-0000-0000-0000-000000000001",
    }

    first = client.post("/dice/games", json=payload, headers=headers)
    second = client.post("/dice/games", json=payload, headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"] == headers["Idempotency-Key"]
    assert len(supabase.tables["dice_games"]) == 1
    assert len(supabase.tables["dice_game_players"]) == 2
    assert notifications == ["sent"]


@pytest.mark.parametrize(
    ("token", "payload_change"),
    [
        (HOST_TOKEN, {"team1_score": 12}),
        (OTHER_TOKEN, {}),
    ],
)
def test_create_rejects_idempotency_key_reuse_by_another_request(token, payload_change):
    client, _ = _build_client(profiles=deepcopy(ROSTER), auth_users=AUTH_USERS)
    payload = {
        "ranked": True,
        "team1_score": 11,
        "team2_score": 7,
        "players": _game_players_1v1("u1", "u2"),
    }
    headers = {
        **_headers(HOST_TOKEN),
        "Idempotency-Key": "65000000-0000-0000-0000-000000000002",
    }
    assert client.post("/dice/games", json=payload, headers=headers).status_code == 200

    replay = client.post(
        "/dice/games",
        json={**payload, **payload_change},
        headers={**_headers(token), "Idempotency-Key": headers["Idempotency-Key"]},
    )

    assert replay.status_code == 400
    assert "conflicts with an earlier request" in replay.json()["detail"]


def test_create_rejects_an_invalid_idempotency_key():
    client, _ = _build_client(profiles=deepcopy(ROSTER), auth_users=AUTH_USERS)
    response = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players_1v1("u1", "u2"),
        },
        headers={**_headers(HOST_TOKEN), "Idempotency-Key": "not-a-uuid"},
    )
    assert response.status_code == 400


def test_canonical_update_and_delete_replace_the_complete_generation():
    client, supabase = _build_client(profiles=deepcopy(ROSTER), auth_users=AUTH_USERS)
    payload = {
        "ranked": True,
        "team1_score": 11,
        "team2_score": 7,
        "players": _game_players_1v1("u1", "u2"),
    }
    game = client.post("/dice/games", json=payload, headers=_headers(HOST_TOKEN)).json()

    updated = client.put(
        f"/dice/games/{game['id']}",
        json={**payload, "team1_score": 7, "team2_score": 11},
        headers=_headers(HOST_TOKEN),
    )
    assert updated.status_code == 200
    assert updated.json()["winner_team"] == 2
    assert len(supabase.tables["dice_games"]) == 1
    assert client.get("/dice/profiles/u2").json()["elo_rating"] > 1500

    before_failed_delete = deepcopy(supabase.tables)
    supabase.rating_mutation_failure = "after"
    with pytest.raises(RuntimeError, match="synthetic mutation failure"):
        client.delete(f"/dice/games/{game['id']}", headers=_headers(HOST_TOKEN))
    assert supabase.tables == before_failed_delete

    supabase.rating_mutation_failure = None
    deleted = client.delete(f"/dice/games/{game['id']}", headers=_headers(HOST_TOKEN))
    assert deleted.status_code == 200
    assert supabase.tables["dice_games"] == []
    assert client.get("/dice/profiles/u1").json()["elo_rating"] == 1500
    assert client.get("/dice/profiles/u2").json()["rating_deviation"] == 350.0


def test_live_materialized_game_rejects_manual_update_and_delete():
    client, supabase = _build_client(profiles=deepcopy(ROSTER), auth_users=AUTH_USERS)
    payload = {
        "ranked": False,
        "team1_score": 11,
        "team2_score": 7,
        "players": _game_players_1v1("u1", "u2"),
    }
    game = client.post("/dice/games", json=payload, headers=_headers(HOST_TOKEN)).json()
    supabase.tables["dice_games"][0]["source_live_match_id"] = "live-match-1"
    before = deepcopy(supabase.tables)

    updated = client.put(
        f"/dice/games/{game['id']}", json={**payload, "ranked": True},
        headers=_headers(HOST_TOKEN),
    )
    deleted = client.delete(f"/dice/games/{game['id']}", headers=_headers(HOST_TOKEN))

    assert updated.status_code == 400
    assert deleted.status_code == 400
    assert "through the live match" in updated.json()["detail"]
    assert supabase.tables == before


def test_logging_a_match_with_three_players_is_rejected():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    response = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "players": [
                {"user_id": "u1", "team": 1, "self_sinks": 0},
                {"user_id": "u2", "team": 1, "self_sinks": 0},
                {"user_id": "u3", "team": 2, "self_sinks": 0},
            ],
        },
        headers=_headers(HOST_TOKEN),
    )

    assert response.status_code == 422


# --- Ranked vs normal win/loss breakdown on the profile ---


def test_profile_tracks_ranked_and_normal_wins_losses_separately():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    )
    client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 5,
            "team2_score": 11,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    profile = client.get("/dice/profiles/u1").json()
    assert profile["wins"] == 1
    assert profile["losses"] == 1
    assert profile["ranked_wins"] == 1
    assert profile["ranked_losses"] == 0
    assert profile["normal_wins"] == 0
    assert profile["normal_losses"] == 1


def test_official_draw_is_readable_and_canonical_replay_counts_no_outcome():
    draw = {
        "id": "draw", "created_by": "u1", "ranked": False,
        "team1_score": 3, "team2_score": 3, "winner_team": None,
        "played_at": datetime.now(timezone.utc), "created_at": datetime.now(timezone.utc),
        "players": [],
    }
    assert DiceGame.model_validate(draw).winner_team is None

    _, supabase = _build_client(profiles=[_profile("u1", "Andrew S"), _profile("u2", "Aziz Rahman")])
    supabase.tables["dice_games"] = [{**draw, "live_result_state": "official"}]
    supabase.tables["dice_game_players"] = [
        {"id": "p1", "game_id": "draw", "user_id": "u1", "team": 1, "self_sinks": 0, "sinks": 0},
        {"id": "p2", "game_id": "draw", "user_id": "u2", "team": 2, "self_sinks": 0, "sinks": 0},
    ]

    plan = build_rating_plan(supabase._rating_source_snapshot())
    profiles = {row["user_id"]: row for row in plan.profile_states}

    for profile in profiles.values():
        assert profile["games_played"] == 1
        assert profile["wins"] == profile["losses"] == 0
        assert profile["normal_wins"] == profile["normal_losses"] == 0
        assert profile["elo_rating"] == 1500


def test_game_list_includes_null_and_official_state_but_excludes_reopened():
    base = {
        "created_by": "u1", "ranked": False,
        "team1_score": 3, "team2_score": 1, "winner_team": 1,
        "played_at": datetime.now(timezone.utc), "created_at": datetime.now(timezone.utc),
    }
    client, supabase = _build_client(profiles=[_profile("u1", "Andrew S"), _profile("u2", "Aziz Rahman")])
    supabase.tables["dice_games"] = [
        {**base, "id": "legacy"},  # no live_result_state key at all
        {**base, "id": "official", "live_result_state": "official"},
        {**base, "id": "reopened", "live_result_state": "reopened"},
    ]

    response = client.get("/dice/games")

    assert response.status_code == 200
    ids = {game["id"] for game in response.json()}
    assert ids == {"legacy", "official"}


# --- Head-to-head vs another player ---


def test_head_to_head_tallies_opponent_wins_and_losses():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    # u1 (viewer) and u4 (profile owner) are opponents in both games: u1 wins one, u4 wins one.
    client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players(["u1", "u2"], ["u4", "u3"]),
        },
        headers=_headers(HOST_TOKEN),
    )
    client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 5,
            "team2_score": 11,
            "players": _game_players(["u1", "u2"], ["u4", "u3"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    profile = client.get("/dice/profiles/u4", headers=_headers(HOST_TOKEN)).json()
    h2h = profile["head_to_head"]
    assert h2h["opponent_wins"] == 1
    assert h2h["opponent_losses"] == 1
    assert h2h["teammate_wins"] == 0
    assert h2h["teammate_losses"] == 0
    assert h2h["total_games"] == 2


def test_head_to_head_tallies_teammate_wins_and_losses():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    # u1 (viewer) and u4 (profile owner) are teammates in both games: one win, one loss together.
    client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players(["u1", "u4"], ["u2", "u3"]),
        },
        headers=_headers(HOST_TOKEN),
    )
    client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 5,
            "team2_score": 11,
            "players": _game_players(["u1", "u4"], ["u2", "u3"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    profile = client.get("/dice/profiles/u4", headers=_headers(HOST_TOKEN)).json()
    h2h = profile["head_to_head"]
    assert h2h["teammate_wins"] == 1
    assert h2h["teammate_losses"] == 1
    assert h2h["opponent_wins"] == 0
    assert h2h["opponent_losses"] == 0
    assert h2h["total_games"] == 2


def test_head_to_head_mixed_teammate_and_opponent_games():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    # Game 1: u1 and u4 are teammates and win.
    client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players(["u1", "u4"], ["u2", "u3"]),
        },
        headers=_headers(HOST_TOKEN),
    )
    # Game 2: u1 and u4 are opponents; u4's team wins, so u1 loses.
    client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 5,
            "team2_score": 11,
            "players": _game_players(["u1", "u2"], ["u4", "u3"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    profile = client.get("/dice/profiles/u4", headers=_headers(HOST_TOKEN)).json()
    h2h = profile["head_to_head"]
    assert h2h["teammate_wins"] == 1
    assert h2h["teammate_losses"] == 0
    assert h2h["opponent_wins"] == 0
    assert h2h["opponent_losses"] == 1
    assert h2h["total_games"] == 2


def test_head_to_head_is_all_zero_with_no_shared_games():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    # A game between u1 and someone else entirely, never involving u4.
    client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players(["u1", "u2"], ["u3", "u5"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    profile = client.get("/dice/profiles/u4", headers=_headers(HOST_TOKEN)).json()
    h2h = profile["head_to_head"]
    assert h2h is not None
    assert h2h["total_games"] == 0
    assert h2h["opponent_wins"] == 0
    assert h2h["opponent_losses"] == 0
    assert h2h["teammate_wins"] == 0
    assert h2h["teammate_losses"] == 0


def test_head_to_head_is_absent_when_viewing_own_profile():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players(["u1", "u4"], ["u2", "u3"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    profile = client.get("/dice/profiles/u1", headers=_headers(HOST_TOKEN)).json()
    assert profile["head_to_head"] is None


def test_head_to_head_is_absent_when_unauthenticated():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players(["u1", "u4"], ["u2", "u3"]),
        },
        headers=_headers(HOST_TOKEN),
    )

    response = client.get("/dice/profiles/u4")
    assert response.status_code == 200
    assert response.json()["head_to_head"] is None


# --- Sinks (distinct from self sinks) ---


def test_profile_aggregates_sinks_across_games():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    game = client.post(
        "/dice/games",
        json={
            "ranked": True,
            "team1_score": 11,
            "team2_score": 7,
            "players": [
                {"user_id": "u1", "team": 1, "sinks": 3, "self_sinks": 1},
                {"user_id": "u2", "team": 1, "sinks": 2},
                {"user_id": "u3", "team": 2, "sinks": 1},
                {"user_id": "u4", "team": 2, "sinks": 0},
            ],
        },
        headers=_headers(HOST_TOKEN),
    ).json()

    u1_out = next(p for p in game["players"] if p["user_id"] == "u1")
    assert u1_out["sinks"] == 3
    assert u1_out["self_sinks"] == 1

    client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 5,
            "team2_score": 11,
            "players": [
                {"user_id": "u1", "team": 1, "sinks": 4},
                {"user_id": "u2", "team": 1, "sinks": 0},
                {"user_id": "u3", "team": 2, "sinks": 0},
                {"user_id": "u4", "team": 2, "sinks": 0},
            ],
        },
        headers=_headers(HOST_TOKEN),
    )

    profile = client.get("/dice/profiles/u1").json()
    assert profile["sinks"] == 7
    assert profile["self_sinks"] == 1


# --- Photo gallery (comment images, aggregated across all games) ---


def test_photos_lists_only_comments_with_images_newest_first():
    client, _ = _build_client(profiles=ROSTER, auth_users=AUTH_USERS)

    game_a = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 7,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    ).json()
    game_b = client.post(
        "/dice/games",
        json={
            "ranked": False,
            "team1_score": 11,
            "team2_score": 9,
            "players": _game_players(["u1", "u2"], ["u3", "u4"]),
        },
        headers=_headers(HOST_TOKEN),
    ).json()

    client.post(
        f"/dice/games/{game_a['id']}/comments",
        json={"body": "gg"},
        headers=_headers(HOST_TOKEN),
    )
    client.post(
        f"/dice/games/{game_a['id']}/comments",
        json={"image_url": "https://example.com/a.jpg"},
        headers=_headers(HOST_TOKEN),
    )
    client.post(
        f"/dice/games/{game_b['id']}/comments",
        json={"body": "nice shot", "image_url": "https://example.com/b.jpg"},
        headers=_headers(ADMIN_TOKEN),
    )

    photos = client.get("/dice/photos").json()

    assert [p["image_url"] for p in photos] == ["https://example.com/b.jpg", "https://example.com/a.jpg"]
    assert photos[0]["game_id"] == game_b["id"]
    assert photos[0]["display_name"] == "Jason Keung"
    assert photos[1]["game_id"] == game_a["id"]
