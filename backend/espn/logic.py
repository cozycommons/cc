"""ESPN Fantasy read logic: pure functions over an EspnClient (no framework code).

Every function takes the per-account client, pulls one league payload with the
views it needs, and returns slim, JSON-friendly dicts. ESPN's unofficial v3
payloads vary by season/era (e.g. a team's display name may be a single
``name`` or a ``location`` + ``nickname`` pair), so all extraction goes through
defensive ``.get`` chains and tolerates missing blocks.

Snapshots (see snapshots.py) are plain payload dicts built by
:func:`build_snapshot`; the trend functions below are pure functions over two
such payloads (the previous one may be ``None`` on first capture).

There is deliberately no matchup-summary function: matchup data is used only
inside :func:`build_snapshot` and :func:`get_team_trends` in v1.
"""

from __future__ import annotations

from datetime import datetime, timezone

# ESPN defaultPositionId / eligibleSlots ids -> display names.
POSITION_NAMES = {
    0: "PG",
    1: "SG",
    2: "SF",
    3: "PF",
    4: "C",
    5: "G",
    6: "F",
    7: "SG/SF",
    8: "G/F",
    9: "PF/C",
    10: "F/C",
    11: "UTIL",
    12: "BE",
    13: "IR",
}

_STREAK_PREFIX = {"WIN": "W", "LOSS": "L", "TIE": "T"}


def _position_name(position_id) -> str | None:
    if position_id is None:
        return None
    return POSITION_NAMES.get(position_id, f"POS{position_id}")


def _team_name(team: dict) -> str | None:
    name = team.get("name")
    if name:
        return name
    parts = [team.get("location"), team.get("nickname")]
    joined = " ".join(str(p) for p in parts if p)
    return joined or team.get("abbrev") or None


def _members_by_id(payload: dict) -> dict:
    members = {}
    for member in payload.get("members") or []:
        if isinstance(member, dict) and member.get("id") is not None:
            members[member["id"]] = member.get("displayName")
    return members


def _slim_team(team: dict, members: dict) -> dict:
    record = ((team.get("record") or {}).get("overall")) or {}
    streak_raw = record.get("streak") or {}
    streak = None
    if isinstance(streak_raw, dict):
        prefix = _STREAK_PREFIX.get(streak_raw.get("type"))
        length = streak_raw.get("length")
        if prefix and length is not None:
            streak = f"{prefix}{length}"
    owners = team.get("owners") or []
    owner_id = owners[0] if owners else None
    return {
        "team_id": team.get("id"),
        "name": _team_name(team),
        "abbrev": team.get("abbrev"),
        "owner": members.get(owner_id) if owner_id is not None else None,
        "wins": record.get("wins"),
        "losses": record.get("losses"),
        "ties": record.get("ties"),
        "points_for": record.get("pointsFor"),
        "points_against": record.get("pointsAgainst"),
        "streak": streak,
    }


def _weekly_points_by_team(schedule) -> dict:
    """{team_id: {week_int: points}} from mMatchup schedule entries.

    Sides with a ``None`` total (unplayed weeks) are skipped.
    """
    weekly: dict[int, dict[int, float]] = {}
    for entry in schedule or []:
        if not isinstance(entry, dict):
            continue
        week = entry.get("matchupPeriodId")
        if week is None:
            continue
        for side_name in ("home", "away"):
            side = entry.get(side_name) or {}
            if not isinstance(side, dict):
                continue
            team_id = side.get("teamId")
            points = side.get("totalPoints")
            if team_id is None or points is None:
                continue
            weekly.setdefault(team_id, {})[int(week)] = points
    return weekly


def _stat_total(player: dict, split_type_id: int):
    if not isinstance(player, dict):
        return None
    for stat in player.get("stats") or []:
        if isinstance(stat, dict) and stat.get("statSplitTypeId") == split_type_id:
            return stat.get("appliedTotal")
    return None


def _season_fantasy_points(player: dict):
    """Season-total fantasy points (statSplitTypeId 1), or None when absent."""
    return _stat_total(player, 1)


def _recent7_fantasy_points(player: dict):
    """Last-7-days fantasy points (statSplitTypeId 2), or None when absent."""
    return _stat_total(player, 2)


def _teams(payload: dict) -> list:
    return [t for t in payload.get("teams") or [] if isinstance(t, dict)]


# --- league / standings / teams -----------------------------------------------


def get_league(client) -> dict:
    """League settings plus a slim team list."""
    payload = client.get_league(["mSettings", "mTeam"]) or {}
    settings = payload.get("settings") or {}
    status = payload.get("status") or {}
    members = _members_by_id(payload)
    teams = [_slim_team(t, members) for t in _teams(payload)]
    teams.sort(key=lambda t: (t["team_id"] is None, t["team_id"]))
    return {
        "league_id": payload.get("id"),
        "name": settings.get("name"),
        "season": payload.get("seasonId"),
        "size": settings.get("size"),
        "current_week": status.get("currentMatchupPeriod"),
        "current_scoring_period": status.get("currentScoringPeriod"),
        "teams": teams,
        "scoring_items": (settings.get("scoringSettings") or {}).get(
            "scoringItems"
        )
        or [],
    }


def get_standings(client) -> dict:
    """Slim teams ranked by wins (desc), then points_for (desc)."""
    payload = client.get_league(["mTeam", "mStandings"]) or {}
    members = _members_by_id(payload)
    teams = [_slim_team(t, members) for t in _teams(payload)]
    teams.sort(
        key=lambda t: (-(t["wins"] or 0), -(t["points_for"] or 0))
    )
    standings = []
    for rank, team in enumerate(teams, start=1):
        entry = dict(team)
        entry["rank"] = rank
        standings.append(entry)
    return {"standings": standings, "count": len(standings)}


def get_team(client, team_id: int) -> dict:
    """One slim team plus its slimmed roster."""
    payload = client.get_league(["mTeam", "mRoster"]) or {}
    members = _members_by_id(payload)
    team = None
    for candidate in _teams(payload):
        if candidate.get("id") == team_id:
            team = candidate
            break
    if team is None:
        raise ValueError("team not found")

    roster = []
    entries = ((team.get("roster") or {}).get("entries")) or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        player = ((entry.get("playerPoolEntry") or {}).get("player")) or {}
        if not isinstance(player, dict):
            player = {}
        ownership = player.get("ownership") or {}
        player_id = entry.get("playerId")
        if player_id is None:
            player_id = player.get("id")
        roster.append(
            {
                "player_id": player_id,
                "name": player.get("fullName"),
                "position": _position_name(player.get("defaultPositionId")),
                "eligible_slots": [
                    _position_name(slot)
                    for slot in player.get("eligibleSlots") or []
                ],
                "pro_team_id": player.get("proTeamId"),
                "injury_status": player.get("injuryStatus"),
                "percent_owned": ownership.get("percentOwned"),
                "percent_change": ownership.get("percentChange"),
            }
        )
    return {
        "team": _slim_team(team, members),
        "roster": roster,
        "roster_count": len(roster),
    }


# --- transactions / draft -------------------------------------------------------


def _iso_from_epoch_ms(value) -> str | None:
    if value is None:
        return None
    try:
        moment = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None
    return moment.isoformat().replace("+00:00", "Z")


def get_transactions(client, limit: int = 25) -> dict:
    """Recent league transactions, newest first.

    Player names are not in the mTransactions2 payload — moves carry player
    ids only, and that is expected.
    """
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    payload = client.get_league(["mTransactions2"]) or {}
    raw = [t for t in payload.get("transactions") or [] if isinstance(t, dict)]
    raw = sorted(raw, key=lambda t: t.get("date") or 0, reverse=True)

    transactions = []
    for txn in raw[:limit]:
        moves = []
        for item in txn.get("items") or []:
            if not isinstance(item, dict):
                continue
            moves.append(
                {
                    "action": item.get("type"),
                    "player_id": item.get("playerId"),
                    "from_team_id": item.get("fromTeamId"),
                    "to_team_id": item.get("toTeamId"),
                }
            )
        transactions.append(
            {
                "id": txn.get("id"),
                "type": txn.get("type"),
                "status": txn.get("status"),
                "date": _iso_from_epoch_ms(txn.get("date")),
                "team_id": txn.get("teamId"),
                "member_id": txn.get("memberId"),
                "bid_amount": txn.get("bidAmount"),
                "scoring_period_id": txn.get("scoringPeriodId"),
                "moves": moves,
            }
        )
    return {"transactions": transactions, "count": len(transactions)}


def get_draft(client) -> dict:
    """Draft picks in overall-pick order, with team names resolved."""
    payload = client.get_league(["mDraftDetail", "mTeam"]) or {}
    team_names = {t.get("id"): _team_name(t) for t in _teams(payload)}
    detail = payload.get("draftDetail") or {}
    raw = [p for p in detail.get("picks") or [] if isinstance(p, dict)]
    raw = sorted(
        raw,
        key=lambda p: (
            p.get("overallPickNumber") is None,
            p.get("overallPickNumber") or 0,
        ),
    )
    picks = [
        {
            "overall_pick": pick.get("overallPickNumber"),
            "round": pick.get("roundId"),
            "pick_in_round": pick.get("roundPickNumber"),
            "team_id": pick.get("teamId"),
            "team_name": team_names.get(pick.get("teamId")),
            "player_id": pick.get("playerId"),
            "keeper": pick.get("keeper"),
            "bid_amount": pick.get("bidAmount"),
        }
        for pick in raw
    ]
    return {
        "drafted": bool(detail.get("drafted")),
        "picks": picks,
        "count": len(picks),
    }


# --- team trends ----------------------------------------------------------------


def get_team_trends(client) -> dict:
    """Per-team form: weekly points, recent average, all-play wins, and luck.

    All-play expected wins replay every played week as if each team faced
    every other team that week: for each week, a team earns
    ``(opponents with fewer points + 0.5 * opponents tied) / (num_teams - 1)``.
    ``luck`` is actual wins minus that expectation (positive = lucky).
    """
    payload = client.get_league(["mTeam", "mMatchup"]) or {}
    members = _members_by_id(payload)
    teams = _teams(payload)
    weekly = _weekly_points_by_team(payload.get("schedule") or [])
    num_teams = len(teams)

    out = []
    for team in teams:
        slim = _slim_team(team, members)
        team_id = team.get("id")
        by_week = weekly.get(team_id) or {}
        weeks = sorted(by_week)
        played = [by_week[w] for w in weeks]
        last3 = played[-3:]
        last3_avg = round(sum(last3) / len(last3), 1) if last3 else None

        expected = 0.0
        if num_teams > 1:
            for week in weeks:
                points = by_week[week]
                fewer = 0
                tied = 0
                for other_id, other_by_week in weekly.items():
                    if other_id == team_id or week not in other_by_week:
                        continue
                    if other_by_week[week] < points:
                        fewer += 1
                    elif other_by_week[week] == points:
                        tied += 1
                expected += (fewer + 0.5 * tied) / (num_teams - 1)
        expected = round(expected, 2)

        out.append(
            {
                "team_id": team_id,
                "name": slim["name"],
                "points_by_week": {str(w): by_week[w] for w in weeks},
                "total_points_for": slim["points_for"],
                "total_points_against": slim["points_against"],
                "last3_avg": last3_avg,
                "streak": slim["streak"],
                "allplay_expected_wins": expected,
                "luck": round((slim["wins"] or 0) - expected, 2),
            }
        )
    out.sort(key=lambda t: -(t["total_points_for"] or 0))
    return {"teams": out}


# --- snapshots ------------------------------------------------------------------


def build_snapshot(client) -> dict:
    """One point-in-time snapshot payload for trend comparisons.

    Teams carry their weekly points (string week keys, JSON-friendly);
    players carry ownership plus season / last-7-days fantasy-point totals
    extracted from the kona player stats splits.
    """
    payload = (
        client.get_league(["mSettings", "mTeam", "mMatchup"]) or {}
    )
    settings = payload.get("settings") or {}
    status = payload.get("status") or {}
    weekly = _weekly_points_by_team(payload.get("schedule") or [])

    teams = []
    for team in _teams(payload):
        record = ((team.get("record") or {}).get("overall")) or {}
        team_id = team.get("id")
        by_week = weekly.get(team_id) or {}
        teams.append(
            {
                "team_id": team_id,
                "name": _team_name(team),
                "wins": record.get("wins"),
                "losses": record.get("losses"),
                "ties": record.get("ties"),
                "points_for": record.get("pointsFor"),
                "points_against": record.get("pointsAgainst"),
                "weekly_points": {
                    str(w): by_week[w] for w in sorted(by_week)
                },
            }
        )

    players = []
    for entry in client.get_players(300) or []:
        if not isinstance(entry, dict):
            continue
        player = entry.get("player")
        if not isinstance(player, dict):
            continue
        ownership = player.get("ownership") or {}
        player_id = player.get("id")
        if player_id is None:
            player_id = entry.get("id")
        players.append(
            {
                "player_id": player_id,
                "name": player.get("fullName"),
                "position": _position_name(player.get("defaultPositionId")),
                "team_id": entry.get("onTeamId") or None,
                "percent_owned": ownership.get("percentOwned"),
                "percent_started": ownership.get("percentStarted"),
                "percent_change": ownership.get("percentChange"),
                "season_fantasy_points": _season_fantasy_points(player),
                "recent7_fantasy_points": _recent7_fantasy_points(player),
            }
        )

    return {
        "league_id": payload.get("id"),
        "season": payload.get("seasonId"),
        "name": settings.get("name"),
        "current_scoring_period": status.get("currentScoringPeriod"),
        "current_matchup_period": status.get("currentMatchupPeriod"),
        "teams": teams,
        "players": players,
    }


# --- player trends (pure functions over snapshot payloads) -----------------------


def _players_by_id(snapshot) -> dict:
    players = {}
    for player in (snapshot or {}).get("players") or []:
        if isinstance(player, dict) and player.get("player_id") is not None:
            players[player["player_id"]] = player
    return players


def player_ownership_trends(current_snap, previous_snap=None, limit: int = 10) -> dict:
    """Most added / most dropped players by ownership movement.

    With a previous snapshot, movement is the change in ``percent_owned``
    between the two snapshots; players missing from either snapshot are not
    comparable and are skipped. Without one, ESPN's own ``percent_change``
    on the current snapshot is used instead.
    """
    current = _players_by_id(current_snap)
    candidates = []  # (movement, entry)

    if previous_snap is not None:
        source = "snapshots"
        previous = _players_by_id(previous_snap)
        for player_id, cur in current.items():
            prev = previous.get(player_id)
            if prev is None:
                continue
            cur_owned = cur.get("percent_owned")
            prev_owned = prev.get("percent_owned")
            if cur_owned is None or prev_owned is None:
                continue
            movement = cur_owned - prev_owned
            if movement == 0:
                continue
            candidates.append(
                (
                    movement,
                    {
                        "player_id": player_id,
                        "name": cur.get("name"),
                        "team_id": cur.get("team_id"),
                        "percent_owned": cur_owned,
                        "ownership_change": round(movement, 2),
                    },
                )
            )
    else:
        source = "espn_percent_change"
        for player_id, cur in current.items():
            movement = cur.get("percent_change")
            if movement is None or movement == 0:
                continue
            candidates.append(
                (
                    movement,
                    {
                        "player_id": player_id,
                        "name": cur.get("name"),
                        "team_id": cur.get("team_id"),
                        "percent_owned": cur.get("percent_owned"),
                        "ownership_change": round(movement, 2),
                    },
                )
            )

    most_added = [
        entry
        for movement, entry in sorted(
            (c for c in candidates if c[0] > 0),
            key=lambda c: -c[0],
        )[:limit]
    ]
    most_dropped = [
        entry
        for movement, entry in sorted(
            (c for c in candidates if c[0] < 0),
            key=lambda c: c[0],
        )[:limit]
    ]
    return {
        "most_added": most_added,
        "most_dropped": most_dropped,
        "source": source,
    }


def _season_rate_denominator(current_snap) -> float:
    period = (current_snap or {}).get("current_scoring_period")
    if isinstance(period, (int, float)) and not isinstance(period, bool):
        return max(1, period)
    return 1


def _performance_entries(candidates, limit: int) -> tuple[list, list]:
    risers = [
        entry
        for delta, entry in sorted(
            (c for c in candidates if c[0] > 0), key=lambda c: -c[0]
        )[:limit]
    ]
    fallers = [
        entry
        for delta, entry in sorted(
            (c for c in candidates if c[0] < 0), key=lambda c: c[0]
        )[:limit]
    ]
    return risers, fallers


def _performance_from_splits(current_snap, limit: int) -> dict:
    """Fallback: compare each player's last-7-days rate to their season rate."""
    denominator = _season_rate_denominator(current_snap)
    candidates = []
    qualified = 0
    for player in _players_by_id(current_snap).values():
        recent7 = player.get("recent7_fantasy_points")
        season_total = player.get("season_fantasy_points")
        if recent7 is None or season_total is None:
            continue
        qualified += 1
        recent_rate = recent7 / 7
        season_rate = season_total / denominator
        delta = recent_rate - season_rate
        if delta == 0:
            continue
        candidates.append(
            (
                delta,
                {
                    "player_id": player.get("player_id"),
                    "name": player.get("name"),
                    "team_id": player.get("team_id"),
                    "season_fantasy_points": season_total,
                    "recent_points_per_day": round(recent_rate, 2),
                    "season_points_per_day": round(season_rate, 2),
                    "delta_per_day": round(delta, 2),
                },
            )
        )
    if not qualified:
        return {"risers": [], "fallers": [], "source": "insufficient_history"}
    risers, fallers = _performance_entries(candidates, limit)
    return {"risers": risers, "fallers": fallers, "source": "espn_splits"}


def player_performance_trends(
    current_snap, previous_snap=None, span_days: float | None = None, limit: int = 10
) -> dict:
    """Risers / fallers by recent scoring rate vs season scoring rate.

    With a previous snapshot at least a day old, the recent rate is the
    season-total growth over the span between snapshots. Otherwise (first
    snapshot, or a previous snapshot too fresh to span a day) this falls
    back to ESPN's own last-7-days split on the current snapshot.
    """
    if previous_snap is not None and span_days and span_days >= 1:
        denominator = _season_rate_denominator(current_snap)
        current = _players_by_id(current_snap)
        previous = _players_by_id(previous_snap)
        candidates = []
        for player_id, cur in current.items():
            prev = previous.get(player_id)
            if prev is None:
                continue
            cur_total = cur.get("season_fantasy_points")
            prev_total = prev.get("season_fantasy_points")
            if cur_total is None or prev_total is None:
                continue
            recent_rate = (cur_total - prev_total) / span_days
            season_rate = cur_total / denominator
            delta = recent_rate - season_rate
            if delta == 0:
                continue
            candidates.append(
                (
                    delta,
                    {
                        "player_id": player_id,
                        "name": cur.get("name"),
                        "team_id": cur.get("team_id"),
                        "season_fantasy_points": cur_total,
                        "recent_points_per_day": round(recent_rate, 2),
                        "season_points_per_day": round(season_rate, 2),
                        "delta_per_day": round(delta, 2),
                    },
                )
            )
        risers, fallers = _performance_entries(candidates, limit)
        return {"risers": risers, "fallers": fallers, "source": "snapshots"}

    return _performance_from_splits(current_snap, limit)
