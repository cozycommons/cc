#!/usr/bin/env python3
"""Build a replayable completed Dice game in the synthetic local sandbox."""

from __future__ import annotations

import argparse
import atexit
import json
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse


REPOSITORY = Path(__file__).resolve().parents[1]
SUPABASE_URL = "http://127.0.0.1:54321"
PLAYERS = (
    "10000000-0000-0000-0000-000000000006",
    "10000000-0000-0000-0000-000000000007",
    "10000000-0000-0000-0000-000000000008",
    "10000000-0000-0000-0000-000000000009",
)


def request_json(url: str, *, method: str = "GET", token: str | None = None,
                 body: dict | None = None, headers: dict | None = None) -> dict | list:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        method=method,
        headers=request_headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url} returned {error.code}: {detail}") from error


def publishable_key() -> str:
    result = subprocess.run(
        [str(REPOSITORY / "scripts/dice-supabase.sh"), "status", "--workdir", str(REPOSITORY), "-o", "env"],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith('PUBLISHABLE_KEY="') and line.endswith('"'):
            return line.removeprefix('PUBLISHABLE_KEY="').removesuffix('"')
    raise RuntimeError("local Supabase did not report PUBLISHABLE_KEY")


def authenticate(key: str | None = None) -> str:
    session = request_json(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        method="POST",
        headers={"apikey": key or publishable_key()},
        body={"email": "referee@dice.local", "password": "local-dice-password"},
    )
    return session["access_token"]


def parse_score(value: str) -> tuple[int, int]:
    try:
        left, right = (int(item) for item in value.replace("–", "-").split("-", 1))
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("score must look like 4-5 or 25-23") from error
    if left < 0 or right < 0 or left == right:
        raise argparse.ArgumentTypeError("completed score must be nonnegative and have one winner")
    return left, right


def ready_to_finish(score: tuple[int, int], target: int, win_by: int) -> bool:
    return max(score) >= target and abs(score[0] - score[1]) >= win_by


def validate_local_api(api_url: str) -> str:
    parsed = urlparse(api_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or not parsed.port:
        raise RuntimeError("--api-url must be an explicit loopback HTTP URL with a port")
    base = api_url.rstrip("/")
    health = request_json(f"{base}/health")
    if health.get("status") != "ok":
        raise RuntimeError("local API health check did not return ok")
    openapi = request_json(f"{base}/openapi.json")
    if "/dice/live/games/{match_id}/settings" not in openapi.get("paths", {}):
        raise RuntimeError("local API is missing the completed-game settings endpoint")
    return base


def rules(target: int, win_by: int) -> dict:
    return {
        "contract_version": 1,
        "ruleset_version": 1,
        "scoring_version": 1,
        "target_score": target,
        "win_by": win_by,
        "call_policy": {
            "low_call_deadline": "before_surface_contact",
            "low_call_exceptions": [],
            "short_boundary": "center_line_is_short",
            "midline_remedy": "consume_attempt",
            "dispute_authority": "teams_or_designated_referee",
            "uncertain_call_remedy": "retoss",
        },
    }


def duo_entry(ladder: dict, members: tuple[str, str]) -> dict:
    expected = set(members)
    for entry in [*ladder["ranked"], *ladder["to_watch"]]:
        if {member["user_id"] for member in entry["members"]} == expected:
            return entry
    raise RuntimeError(f"duo not found in replay output: {sorted(expected)}")


def profile_snapshot(api: str, token: str) -> dict[str, dict]:
    fields = (
        "elo_rating", "rating_deviation", "elo_model_version", "ranked_games_played",
        "games_played", "wins", "losses",
        "ranked_wins", "ranked_losses", "normal_wins", "normal_losses",
    )
    snapshots = {}
    for player_id in PLAYERS:
        profile = request_json(f"{api}/dice/profiles/{player_id}", token=token)
        snapshots[player_id] = {field: profile[field] for field in fields}
    return snapshots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend-url", default="http://localhost:8080")
    parser.add_argument("--supabase-key", help=argparse.SUPPRESS)
    parser.add_argument("--score", type=parse_score, default=parse_score("4-5"))
    parser.add_argument("--target", type=int, default=5)
    parser.add_argument("--win-by", type=int, default=1)
    args = parser.parse_args()
    if args.target < 1 or args.win_by < 1:
        parser.error("--target and --win-by must be positive")
    remaining = list(args.score)
    point_teams = []
    while remaining[0] or remaining[1]:
        for team_index in (0, 1):
            if remaining[team_index]:
                point_teams.append(team_index)
                remaining[team_index] -= 1
    if not ready_to_finish(args.score, args.target, args.win_by):
        parser.error("--score is not complete under the requested target and win-by rules")

    api = validate_local_api(args.api_url)
    token = authenticate(args.supabase_key)
    created = request_json(
        f"{api}/dice/live/games",
        method="POST",
        token=token,
        headers={"Idempotency-Key": str(uuid.uuid4())},
        body={
            "team_order": ["blue", "clay"],
            "teams": {"blue": [PLAYERS[1], PLAYERS[0]], "clay": list(PLAYERS[2:])},
            "rules_snapshot": rules(args.target, args.win_by),
            "ranked": False,
        },
    )
    match_id = created["id"]
    version = created["version"]
    scorer_index = [0, 0]
    for team_index in point_teams:
        roster = PLAYERS[:2] if team_index == 0 else PLAYERS[2:]
        scorer = roster[scorer_index[team_index] % 2]
        scorer_index[team_index] += 1
        receipt = request_json(
            f"{api}/dice/live/games/{match_id}/commands",
            method="POST",
            token=token,
            body={
                "kind": "record_throw",
                "client_command_id": str(uuid.uuid4()),
                "expected_version": version,
                "match_elapsed_ms": 0,
                "thrower_id": scorer,
                "outcome": "point",
            },
        )
        version = receipt["accepted_version"]

    finished = request_json(
        f"{api}/dice/live/games/{match_id}/commands",
        method="POST",
        token=token,
        body={
            "kind": "finish",
            "client_command_id": str(uuid.uuid4()),
            "expected_version": version,
            "match_elapsed_ms": 0,
            "coverage": "complete",
            "termination_reason": "target_reached",
        },
    )
    game_id = finished.get("official_result", {}).get("id")
    if not game_id:
        raise RuntimeError("finishing the scenario did not materialize an official game")

    official_before = request_json(f"{api}/dice/games/{game_id}", token=token)
    if official_before["ranked"] is not False or any(
        player.get("elo_before") is not None or player.get("elo_after") is not None
        for player in official_before["players"]
    ):
        raise RuntimeError("completed unranked result started with rating snapshots")
    profiles_before = profile_snapshot(api, token)
    ladder_before = request_json(f"{api}/dice/stats/duos?limit=100&homepage_eligible=false", token=token)
    pairs = (PLAYERS[:2], PLAYERS[2:])
    before_games = [duo_entry(ladder_before, pair)["games"] for pair in pairs]
    rollback = {"ranked": False}

    def restore_unranked_on_failure() -> None:
        if not rollback["ranked"]:
            return
        try:
            request_json(
                f"{api}/dice/live/games/{match_id}/settings",
                method="PUT",
                token=token,
                body={"ranked": False},
            )
        except Exception as error:  # Best-effort cleanup must not hide the original failure.
            print(f"Scenario cleanup failed: {error}", file=sys.stderr)

    atexit.register(restore_unranked_on_failure)
    rollback["ranked"] = True
    ranked = request_json(
        f"{api}/dice/live/games/{match_id}/settings",
        method="PUT",
        token=token,
        body={"ranked": True},
    )
    official = request_json(f"{api}/dice/games/{game_id}", token=token)
    profiles_ranked = profile_snapshot(api, token)
    ladder_ranked = request_json(f"{api}/dice/stats/duos?limit=100&homepage_eligible=false", token=token)
    ranked_duos = [duo_entry(ladder_ranked, pair) for pair in pairs]
    after_games = [entry["games"] for entry in ranked_duos]
    if ranked["ranked"] is not True or official["ranked"] is not True:
        raise RuntimeError("ranked toggle did not reach both live and official records")
    if any(player.get("elo_before") is None or player.get("elo_after") is None for player in official["players"]):
        raise RuntimeError("ranked toggle did not backfill individual ELO snapshots")
    for player in official["players"]:
        delta = player["elo_after"] - player["elo_before"]
        if (player["team"] == official["winner_team"] and delta <= 0) or (
            player["team"] != official["winner_team"] and delta >= 0
        ):
            raise RuntimeError("ranked toggle backfilled an incorrect individual ELO direction")
    if after_games != [count + 1 for count in before_games]:
        raise RuntimeError("ranked toggle did not add the game to both exact duo replays")
    if any(game_id not in entry["game_ids"] for entry in ranked_duos):
        raise RuntimeError("ranked toggle did not attribute both exact duo replays to this game")
    credited_pairs = {
        frozenset(member["user_id"] for member in entry["members"])
        for entry in [*ladder_ranked["ranked"], *ladder_ranked["to_watch"]]
        if game_id in entry["game_ids"]
    }
    if credited_pairs != {frozenset(pair) for pair in pairs}:
        raise RuntimeError("ranked toggle credited a non-exact or order-sensitive duo")
    for player in official["players"]:
        before = profiles_before[player["user_id"]]
        after = profiles_ranked[player["user_id"]]
        won = player["team"] == official["winner_team"]
        if (after["elo_rating"] - before["elo_rating"] != player["elo_after"] - player["elo_before"]
                or after["rating_deviation"] != player["rating_deviation_after"]):
            raise RuntimeError("ranked toggle did not apply the individual ELO snapshot to the profile")
        expected_counter = "ranked_wins" if won else "ranked_losses"
        normal_counter = "normal_wins" if won else "normal_losses"
        if (after["ranked_games_played"] != before["ranked_games_played"] + 1
                or after[expected_counter] != before[expected_counter] + 1
                or after[normal_counter] != before[normal_counter] - 1
                or after["games_played"] != before["games_played"]
                or after["wins"] != before["wins"]
                or after["losses"] != before["losses"]):
            raise RuntimeError("ranked toggle did not move the profile aggregate from normal to ranked")

    unranked = request_json(
        f"{api}/dice/live/games/{match_id}/settings",
        method="PUT",
        token=token,
        body={"ranked": False},
    )
    restored = request_json(f"{api}/dice/games/{game_id}", token=token)
    profiles_restored = profile_snapshot(api, token)
    ladder_restored = request_json(f"{api}/dice/stats/duos?limit=100&homepage_eligible=false", token=token)
    if unranked["ranked"] is not False or restored["ranked"] is not False:
        raise RuntimeError("unranked toggle did not restore both live and official records")
    if any(player.get("elo_before") is not None or player.get("elo_after") is not None for player in restored["players"]):
        raise RuntimeError("unranked toggle did not remove individual ELO snapshots")
    restored_duos = [duo_entry(ladder_restored, pair) for pair in pairs]
    if [entry["games"] for entry in restored_duos] != before_games:
        raise RuntimeError("unranked toggle did not restore both exact duo replays")
    if any(game_id in entry["game_ids"] for entry in restored_duos):
        raise RuntimeError("unranked toggle left this game in an exact duo replay")
    if profiles_restored != profiles_before:
        raise RuntimeError("unranked toggle did not restore individual profile aggregates")
    rollback["ranked"] = False
    atexit.unregister(restore_unranked_on_failure)

    browser_url = f"{args.frontend_url.rstrip('/')}/dice/live/{match_id}"
    print(json.dumps({
        "match_id": match_id,
        "game_id": game_id,
        "score": list(args.score),
        "ranked": False,
        "verified": ["individual_elo_backfill", "duo_replay", "unranked_restore"],
        "url": browser_url,
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Scenario failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
