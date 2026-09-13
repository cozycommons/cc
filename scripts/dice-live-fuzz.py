#!/usr/bin/env python3
"""Run deterministic live-referee mutations against the disposable local sandbox."""

from __future__ import annotations

import argparse
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


class HttpFailure(RuntimeError):
    def __init__(self, method: str, url: str, status: int, body: object):
        self.status = status
        self.body = body
        super().__init__(f"{method} {url} returned {status}: {body}")


def request(url: str, *, method: str = "GET", token: str | None = None,
            body: dict | None = None, headers: dict | None = None) -> object:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, method=method, headers=request_headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raw = error.read().decode(errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise HttpFailure(method, url, error.code, detail) from error


def publishable_key() -> str:
    result = subprocess.run(
        [str(REPOSITORY / "scripts/dice-supabase.sh"), "status", "--workdir", str(REPOSITORY), "-o", "env"],
        check=True, capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith('PUBLISHABLE_KEY="') and line.endswith('"'):
            return line.removeprefix('PUBLISHABLE_KEY="').removesuffix('"')
    raise RuntimeError("local Supabase did not report PUBLISHABLE_KEY")


def authenticate() -> str:
    session = request(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password", method="POST",
        headers={"apikey": publishable_key()},
        body={"email": "referee@dice.local", "password": "local-dice-password"},
    )
    return session["access_token"]


def rules(target: int = 99, win_by: int = 2) -> dict:
    return {
        "contract_version": 1, "ruleset_version": 1, "scoring_version": 1,
        "target_score": target, "win_by": win_by,
        "call_policy": {
            "low_call_deadline": "before_surface_contact", "low_call_exceptions": [],
            "short_boundary": "center_line_is_short", "midline_remedy": "consume_attempt",
            "dispute_authority": "teams_or_designated_referee", "uncertain_call_remedy": "retoss",
        },
    }


def create(api: str, token: str, *, target: int = 99, win_by: int = 2) -> tuple[str, int]:
    created = request(
        f"{api}/dice/live/games", method="POST", token=token,
        headers={"Idempotency-Key": str(uuid.uuid4())},
        body={
            "team_order": ["blue", "clay"],
            "teams": {"blue": list(PLAYERS[:2]), "clay": list(PLAYERS[2:])},
            "rules_snapshot": rules(target, win_by), "ranked": False,
        },
    )
    return created["id"], created["version"]


def command(api: str, token: str, match_id: str, version: int, kind: str, **fields: object) -> dict:
    payload = {
        "kind": kind, "client_command_id": str(uuid.uuid4()),
        "expected_version": version, "match_elapsed_ms": 0, **fields,
    }
    return request(f"{api}/dice/live/games/{match_id}/commands", method="POST", token=token, body=payload)


def expect_http(label: str, action, statuses: set[int]) -> dict:
    try:
        action()
    except HttpFailure as error:
        if error.status in statuses:
            return {"case": label, "status": error.status, "detail": error.body}
        raise RuntimeError(f"{label}: unexpected HTTP {error.status}: {error.body}") from error
    raise RuntimeError(f"{label}: expected HTTP {sorted(statuses)} but request succeeded")


def case_observation_matrix(api: str, token: str) -> dict:
    match_id, version = create(api, token)
    expected = [0, 0]
    observations = (
        (PLAYERS[0], "miss", None),
        (PLAYERS[0], "point", None),
        (PLAYERS[2], "self_sink", None),
        # FIFA is recorded by the thrower, but the kicker is the receiving
        # player who can finish the play for the receiving team.
        (PLAYERS[0], "fifa", {"finish": "goal", "kicker_id": PLAYERS[2]}),
        (PLAYERS[0], "invalid", None),
    )
    for thrower, outcome, fifa in observations:
        fields = {"thrower_id": thrower, "outcome": outcome}
        if outcome == "invalid":
            fields["characteristics"] = ["short"]
        if fifa:
            fields["fifa"] = fifa
        receipt = command(api, token, match_id, version, "record_throw", **fields)
        version = receipt["accepted_version"]
        if outcome == "point":
            expected[0] += 1
        elif outcome == "self_sink":
            expected[0] += 2
        elif outcome == "fifa":
            expected[1] += 1
    detail = request(f"{api}/dice/live/games/{match_id}", token=token)
    if detail["score"] != expected or len(detail["events"]) != len(observations):
        raise RuntimeError(
            f"observation_matrix: projection mismatch: {detail['score']=}, {expected=}, "
            f"{len(detail['events'])=}, expected_events={len(observations)}"
        )
    return {"case": "observation_matrix", "match_id": match_id, "score": expected, "events": len(detail["events"])}


def case_idempotency_and_stale_version(api: str, token: str) -> dict:
    match_id, version = create(api, token)
    command_id = str(uuid.uuid4())
    payload = {"kind": "record_throw", "client_command_id": command_id,
               "expected_version": version, "match_elapsed_ms": 0,
               "thrower_id": PLAYERS[0], "outcome": "point"}
    first = request(f"{api}/dice/live/games/{match_id}/commands", method="POST", token=token, body=payload)
    retry = request(f"{api}/dice/live/games/{match_id}/commands", method="POST", token=token, body=payload)
    if retry["accepted_version"] != first["accepted_version"]:
        raise RuntimeError("idempotent retry changed the accepted version")
    stale = expect_http(
        "stale_expected_version",
        lambda: command(api, token, match_id, version, "record_throw", thrower_id=PLAYERS[2], outcome="point"),
        {409},
    )
    return {"case": "idempotency_and_stale_version", "match_id": match_id, "retry_version": retry["accepted_version"], "stale": stale["status"]}


def case_correction(api: str, token: str) -> dict:
    match_id, version = create(api, token)
    receipt = command(api, token, match_id, version, "record_throw", thrower_id=PLAYERS[0], outcome="point")
    version = receipt["accepted_version"]
    detail = request(f"{api}/dice/live/games/{match_id}", token=token)
    target = next(event["id"] for event in detail["events"] if event["kind"] == "observation")
    command(api, token, match_id, version, "change_throw", target_event_id=target,
            thrower_id=PLAYERS[0], outcome="miss", reason="mistaken_entry", decision_basis="designated_referee")
    corrected = request(f"{api}/dice/live/games/{match_id}", token=token)
    if corrected["score"] != [0, 0]:
        raise RuntimeError(f"correction did not replace the active observation: {corrected['score']}")
    return {"case": "change_throw", "match_id": match_id, "score": corrected["score"]}


def case_reopen(api: str, token: str) -> dict:
    match_id, version = create(api, token, target=1, win_by=1)
    receipt = command(api, token, match_id, version, "record_throw", thrower_id=PLAYERS[0], outcome="point")
    version = receipt["accepted_version"]
    finished = command(api, token, match_id, version, "finish", coverage="complete", termination_reason="target_reached")
    version = finished["accepted_version"]
    detail = request(f"{api}/dice/live/games/{match_id}", token=token)
    completion = next(event["id"] for event in detail["events"] if event["kind"] == "completion")
    reopened = command(api, token, match_id, version, "reopen", target_event_id=completion, reason="mistaken_entry")
    detail = request(f"{api}/dice/live/games/{match_id}", token=token)
    if detail["status"] not in {"active", "ready_to_finish"}:
        raise RuntimeError(f"reopen did not return an active projection: {detail['status']}")
    return {"case": "reopen_completed_game", "match_id": match_id, "accepted_version": reopened["accepted_version"], "status": detail["status"]}


def case_termination_and_invalid_commands(api: str, token: str) -> dict:
    match_id, version = create(api, token)
    roof = command(api, token, match_id, version, "off_roof", responsible_player_id=PLAYERS[0])
    if roof["accepted_version"] <= version:
        raise RuntimeError("off-roof command did not advance the match version")
    invalid_thrower = expect_http(
        "invalid_roster_player", lambda: command(api, token, match_id, roof["accepted_version"], "record_throw", thrower_id="not-rostered", outcome="point"), {400, 422},
    )
    invalid_reopen = expect_http(
        "reopen_with_score", lambda: request(f"{api}/dice/live/games/{match_id}/commands", method="POST", token=token, body={
            "kind": "reopen", "client_command_id": str(uuid.uuid4()), "expected_version": roof["accepted_version"],
            "match_elapsed_ms": 0, "score": [0, 0],
        }), {422},
    )
    return {"case": "off_roof_and_invalid_commands", "match_id": match_id, "invalid": [invalid_thrower["status"], invalid_reopen["status"]]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend-url", default="http://localhost:8080")
    args = parser.parse_args()
    parsed = urlparse(args.api_url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or not parsed.port:
        parser.error("--api-url must be an explicit loopback HTTP URL with a port")
    api = args.api_url.rstrip("/")
    health = request(f"{api}/health")
    if health.get("status") != "ok":
        raise RuntimeError("local API health check did not return ok")
    token = authenticate()
    cases = [
        case_observation_matrix, case_idempotency_and_stale_version,
        case_correction, case_reopen, case_termination_and_invalid_commands,
    ]
    results = [case(api, token) for case in cases]
    print(json.dumps({"verified": [result["case"] for result in results], "cases": results,
                      "url": f"{args.frontend_url.rstrip('/')}/dice/live"}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HttpFailure, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Fuzz failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
