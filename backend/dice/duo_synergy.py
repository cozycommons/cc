"""Pure pair comparisons using stored individual pregame ratings."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import isfinite
from typing import Iterable, Mapping, Sequence

from dice.duo_rating import DuoMatch, canonical_duo_id, eligible_duo_matches
from dice.elo import expected_score

DUO_SYNERGY_MIN_GAMES = 5
BIG_MOMENTS_MIN_LIVE_GAMES = 10


@dataclass(frozen=True, slots=True)
class SynergyMatch(DuoMatch):
    elo_before: Mapping[str, float | None] = field(default_factory=dict)


def calculate_duo_synergies(matches: Iterable[DuoMatch]) -> dict[str, dict]:
    """Compare every exact pair; never substitute today's Elo for missing history.

    A pair with incomplete rating snapshots has no comparison. Its games still
    count in apart records, which do not depend on ratings.
    """
    pairs: dict[str, dict] = {}
    individual = defaultdict(lambda: {"wins": 0, "losses": 0})
    for match, team1, team2 in eligible_duo_matches(matches):
        if match.live_result_state not in (None, "official"):
            continue
        ratings = getattr(match, "elo_before", {})
        values = [ratings.get(member) for member in (*team1, *team2)]
        complete = all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)
            for value in values
        )
        probability = expected_score(sum(values[:2]) / 2, sum(values[2:]) / 2) if complete else None
        for team, members in enumerate((team1, team2), 1):
            duo_id = canonical_duo_id(*members)
            record = pairs.setdefault(duo_id, {
                "members": members, "wins": 0, "losses": 0, "games": 0,
                "expected_wins": 0.0, "complete": True,
            })
            result = "wins" if match.winner_team == team else "losses"
            record[result] += 1
            record["games"] += 1
            record["complete"] &= complete
            if probability is not None:
                record["expected_wins"] += probability if team == 1 else 1 - probability
            for member in members:
                individual[member][result] += 1

    result = {}
    for duo_id, record in pairs.items():
        if record["games"] < DUO_SYNERGY_MIN_GAMES or not record["complete"]:
            continue
        apart = []
        for member in record["members"]:
            wins = individual[member]["wins"] - record["wins"]
            losses = individual[member]["losses"] - record["losses"]
            if wins + losses:
                apart.append({"user_id": member, "wins": wins, "losses": losses, "games": wins + losses})
        result[duo_id] = {
            key: record[key] for key in ("wins", "losses", "games", "expected_wins")
        } | {"wins_above_expected": record["wins"] - record["expected_wins"], "apart": apart}
    return result


def calculate_big_moments(
    members: tuple[str, str],
    matches: Iterable[DuoMatch],
    points_by_game: Mapping[str, Sequence[Mapping]],
) -> dict | None:
    """Positive team-relative swing attributed to each member's throws.

    Only games with a live timeline count toward the gate. Callers supply a
    timeline projected from the effective ledger so corrections cannot award
    swing to throws that no longer exist. Unattributed moments award no share.
    """
    wanted = canonical_duo_id(*members)
    totals = dict.fromkeys(sorted(members), 0.0)
    games = 0
    for match, team1, team2 in eligible_duo_matches(matches):
        if match.live_result_state not in (None, "official") or match.game_id not in points_by_game:
            continue
        if wanted not in (canonical_duo_id(*team1), canonical_duo_id(*team2)):
            continue
        games += 1
        direction = 1 if canonical_duo_id(*team1) == wanted else -1
        for point in points_by_game[match.game_id]:
            thrower = point.get("thrower_id")
            swing = point.get("swing")
            if thrower in totals and isinstance(swing, (float, int)) and isfinite(swing):
                totals[thrower] += max(0.0, direction * swing)
    total = sum(totals.values())
    if games < BIG_MOMENTS_MIN_LIVE_GAMES or total <= 0:
        return None
    return {"games": games, "members": [
        {"user_id": member, "positive_swing": swing, "share": swing / total}
        for member, swing in totals.items()
    ]}


def project_big_moment_points(match: Mapping, rules: Mapping, events: Sequence[Mapping], prior: float):
    """Project surviving throws in ledger order, without correction double counts."""
    from dice.live_probability import project_live_history
    from dice.live_projector import effective_event_roots

    active = [event for _, event in effective_event_roots(events)]
    retossed = {event.get("target_event_id") for event in active if event["kind"] == "retoss_decision"}
    effective = []
    for event in active:
        if event["kind"] == "retoss_decision" or event["id"] in retossed:
            continue
        current = dict(event)
        for key in ("replacement_for", "replay_of", "replay_resolution_for", "replay_disposition"):
            current.pop(key, None)
        version = len(effective) + 1
        current.update(sequence=version, match_version=version, command_index=0,
                       client_command_id=f"duo-moment-{version}")
        effective.append(current)
    return project_live_history(match, rules, effective, pregame_team1_probability=prior)
