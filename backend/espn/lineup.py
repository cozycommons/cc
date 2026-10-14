"""Automatic daily lineup setting for ESPN Fantasy (v2).

The rule (Warner's spec, standing instructions — no per-day approval):
every rostered player who is *scheduled* that day starts. "Scheduled"
means the player's pro team has a game in that scoring period AND the
player is not ruled OUT (questionable / game-time-decision players
count as scheduled). Players with no game and OUT players belong on the
bench; benching them is correct and never a conflict.

A *conflict* is any day where a scheduled player has to sit: more
scheduled players than starting slots (``slot_overflow``), or a
position-eligibility jam (``eligibility_jam``). The best legal lineup
is still submitted — the lowest-value scheduled players sit, where
value is projected fantasy points under the ACCOUNT LEAGUE's own
scoring settings (ESPN's projected stat splits where available,
last-7-days form as fallback) — and every conflict is recorded in the
run log (see :func:`list_runs`) for the user to pull on demand.

Moves are lineup slot moves only (plus IR activation / parking when
needed for a legal lineup). Adds, drops, trades and waiver claims are
out of scope and have no code path here.

Every run — live, dry-run, or failed — is persisted to
``espn_lineup_runs`` with its plan, submitted moves, conflicts and
error. An ESPN auth failure (expired cookies) is recorded as an
``auth_error`` run carrying an ``auth`` conflict, and stops the run:
no retries, no hammering ESPN with dead cookies.

Runs target one scoring period (one day). A run with no target gets
the league's current scoring period; adhoc runs may name a ``scoring_period_id`` directly or a calendar ``date``
(YYYY-MM-DD), resolved against the league's scoring periods via the
pro-game schedule — ESPN allows setting future days' lineups in
advance, and runs are idempotent per (account, scoring period).
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .espn_client import EspnAuthError, EspnError

_ET = ZoneInfo("America/New_York")

BENCH_SLOT = 12
IR_SLOT = 13

# Restrictive slots first: fill the scarcest positions before flex/UTIL.
SLOT_PRIORITY = [4, 0, 1, 2, 3, 5, 6, 11]
STARTING_SLOT_IDS = {0, 1, 2, 3, 4, 5, 6, 11}

# injuryStatus values that mean "ruled out". Anything else (ACTIVE,
# PROBABLE, QUESTIONABLE, DOUBTFUL, missing) counts as scheduled.
OUT_STATUSES = {"OUT", "INJURY_RESERVE"}

DEFAULT_LINEUP_SLOT_COUNTS = {
    0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 11: 3, 12: 3, 13: 1,
}


# --- payload extraction --------------------------------------------------------


def _normalize_member_id(value) -> str:
    return str(value or "").strip().strip("{}").upper()


def find_member_team(payload: dict, swid: str) -> dict:
    """The team owned by the account's SWID (payload member id)."""
    wanted = _normalize_member_id(swid)
    for team in payload.get("teams") or []:
        if not isinstance(team, dict):
            continue
        owners = team.get("owners") or []
        if any(_normalize_member_id(o) == wanted and wanted for o in owners):
            return team
    raise ValueError(
        "could not find the account's team in the league payload "
        "(SWID does not own any team in this league)"
    )


def pro_teams_playing(payload: dict, scoring_period_id: int):
    """Set of pro team ids with a game in the scoring period.

    Reads the league payload's ``proGamesByScoringPeriod`` block.
    Returns None when the block is absent entirely — the caller must
    fail the run rather than guess who is scheduled.
    """
    block = payload.get("proGamesByScoringPeriod")
    if not isinstance(block, dict):
        return None
    games = block.get(str(scoring_period_id))
    if games is None:
        games = block.get(scoring_period_id)
    playing = set()
    for game in games or []:
        if not isinstance(game, dict):
            continue
        for key in ("homeProTeamId", "awayProTeamId", "proTeamId"):
            value = game.get(key)
            if isinstance(value, int):
                playing.add(value)
    return playing


def _period_date_map(payload: dict) -> dict:
    """{scoring_period_id: calendar date} from the pro-game schedule.

    A scoring period is one day; its date is the earliest tip-off in
    the period, converted to America/New_York (a 7pm ET game is already
    the next day in UTC, so the conversion matters). Periods with no
    games are absent — scoring periods advance one per calendar day, so
    game-less days resolve by offset from a dated anchor period.
    """
    block = payload.get("proGamesByScoringPeriod")
    mapping: dict[int, _date] = {}
    if not isinstance(block, dict):
        return mapping
    for key, games in block.items():
        try:
            period = int(key)
        except (TypeError, ValueError):
            continue
        dates = []
        for game in games or []:
            if not isinstance(game, dict):
                continue
            raw = game.get("date")
            if isinstance(raw, (int, float)):
                moment = datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
                dates.append(moment.astimezone(_ET).date())
        if dates:
            mapping[period] = min(dates)
    return mapping


def resolve_scoring_period(
    payload: dict, date: str | None = None, scoring_period_id: int | None = None
) -> int:
    """Resolve a run target to a scoring period id.

    An explicit ``scoring_period_id`` wins. A ``date`` (YYYY-MM-DD) is
    resolved by day-offset from the earliest dated scoring period in
    the pro-game schedule. With neither, the league's current scoring
    period is the target (the no-argument trigger path).
    """
    if scoring_period_id is not None:
        return int(scoring_period_id)
    status = payload.get("status") or {}
    if date is None:
        current = status.get("currentScoringPeriod")
        if current is None:
            raise ValueError(
                "ESPN payload has no currentScoringPeriod; cannot tell "
                "which day to set the lineup for"
            )
        return int(current)
    try:
        target = _date.fromisoformat(date)
    except (TypeError, ValueError):
        raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
    mapping = _period_date_map(payload)
    if not mapping:
        raise ValueError(
            "ESPN payload has no dated pro games; cannot resolve a date "
            "to a scoring period"
        )
    anchor_period = min(mapping)
    resolved = anchor_period + (target - mapping[anchor_period]).days
    first = status.get("firstScoringPeriod")
    if resolved < 1 or (first is not None and resolved < int(first)):
        raise ValueError(
            f"date {date} falls before the season's first scoring period"
        )
    return resolved


def lineup_slot_counts(payload: dict) -> dict:
    """{slot_id: count} from mSettings rosterSettings (defensive)."""
    settings = payload.get("settings") or {}
    raw = (settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    counts = {}
    for key, value in raw.items():
        try:
            counts[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return counts or dict(DEFAULT_LINEUP_SLOT_COUNTS)


def scoring_items(payload: dict) -> list:
    """[{stat_id, points}] from the league's own scoring settings."""
    settings = payload.get("settings") or {}
    raw = (settings.get("scoringSettings") or {}).get("scoringItems") or []
    items = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stat_id = item.get("statId")
        points = item.get("points")
        if stat_id is None or points is None:
            continue
        items.append({"stat_id": stat_id, "points": points})
    return items


def _applied_total(stat_entry: dict, items: list):
    """Fantasy points for one stat split, under the league's scoring.

    Prefers ESPN's own ``appliedTotal`` (already league-scored); falls
    back to applying the league's scoring items to the raw stat line.
    """
    applied = stat_entry.get("appliedTotal")
    if isinstance(applied, (int, float)):
        return float(applied)
    raw_stats = stat_entry.get("stats")
    if isinstance(raw_stats, dict) and items:
        total = 0.0
        for item in items:
            value = raw_stats.get(str(item["stat_id"]))
            if isinstance(value, (int, float)):
                total += float(value) * float(item["points"])
        return total
    return None


def player_value(player: dict, items: list, scoring_period_id: int):
    """(projected points per day, source) for ranking who sits.

    Order: ESPN's projected split for the target day, then last-7-days
    form (per-day rate), then the season split (per-day rate, actual or
    projected). 0.0 / "none" when the payload carries no usable split.
    """
    day_projection = None
    last7 = None
    season_actual = None
    season_projection = None
    for stat in player.get("stats") or []:
        if not isinstance(stat, dict):
            continue
        total = _applied_total(stat, items)
        if total is None:
            continue
        split = stat.get("statSplitTypeId")
        source = stat.get("statSourceId")
        period = stat.get("scoringPeriodId")
        if source == 1 and period == scoring_period_id:
            day_projection = total
        elif split == 2 and source != 1:
            last7 = total
        elif split == 1 and source == 1:
            season_projection = total
        elif split == 1:
            season_actual = total
    if day_projection is not None:
        return day_projection, "day_projection"
    if last7 is not None:
        return last7 / 7.0, "recent7"
    denominator = max(1, scoring_period_id or 1)
    if season_actual is not None:
        return season_actual / denominator, "season"
    if season_projection is not None:
        return season_projection / denominator, "projection"
    return 0.0, "none"


def _is_out(player: dict) -> bool:
    status = str(player.get("injuryStatus") or "").strip().upper()
    return status in OUT_STATUSES


def _parse_roster(team: dict) -> list:
    players = []
    entries = ((team.get("roster") or {}).get("entries")) or []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        player = ((entry.get("playerPoolEntry") or {}).get("player")) or {}
        if not isinstance(player, dict):
            player = {}
        player_id = entry.get("playerId")
        if player_id is None:
            player_id = player.get("id")
        if player_id is None:
            continue
        eligible = player.get("eligibleSlots")
        if not isinstance(eligible, list) or not eligible:
            default_pos = player.get("defaultPositionId")
            eligible = [default_pos] if default_pos is not None else []
        players.append(
            {
                "player_id": player_id,
                "name": player.get("fullName"),
                "pro_team_id": player.get("proTeamId"),
                "injury_status": player.get("injuryStatus"),
                "out": _is_out(player),
                "current_slot": entry.get("lineupSlotId"),
                "eligible_slots": [s for s in eligible if isinstance(s, int)],
                "player": player,
            }
        )
    return players


# --- the planner (pure) ----------------------------------------------------------


def _starting_instances(counts: dict) -> list:
    """Expanded starting slot ids, scarcest first (UTIL appears per count)."""
    instances = []
    for slot_id in SLOT_PRIORITY:
        instances.extend([slot_id] * max(0, counts.get(slot_id, 0)))
    return instances


def _match_scheduled(scheduled: list, instances: list) -> dict:
    """Maximum bipartite matching scheduled players -> slot instances.

    Players are processed highest-value first (Kuhn's augmenting paths),
    so when not everyone fits, the players left unmatched are the
    lowest-value ones that could not be placed. Returns
    {player_id: slot_id}.
    """
    slot_owner: list = [None] * len(instances)
    assignment: dict = {}

    def try_assign(player, visited) -> bool:
        eligible = set(player["eligible_slots"]) & STARTING_SLOT_IDS
        for idx, slot_id in enumerate(instances):
            if slot_id not in eligible or idx in visited:
                continue
            visited.add(idx)
            owner = slot_owner[idx]
            if owner is None or try_assign(owner, visited):
                slot_owner[idx] = player
                assignment[player["player_id"]] = slot_id
                return True
        return False

    for player in scheduled:
        try_assign(player, set())
    return assignment


def plan_lineup(team: dict, payload: dict, scoring_period_id: int, playing) -> dict:
    """Compute the target lineup for one team / scoring period (pure).

    Returns the plan dict persisted on the run row: per-player target
    slots, the LINEUP moves to submit, and any conflicts.
    """
    counts = lineup_slot_counts(payload)
    items = scoring_items(payload)
    players = _parse_roster(team)
    for p in players:
        value, source = player_value(p["player"], items, scoring_period_id)
        p["value"] = round(value, 2)
        p["value_source"] = source
        p["scheduled"] = (
            p["pro_team_id"] in playing if playing is not None else False
        ) and not p["out"]

    instances = _starting_instances(counts)
    scheduled = sorted(
        (p for p in players if p["scheduled"]),
        key=lambda p: (-p["value"], p["player_id"]),
    )
    assignment = _match_scheduled(scheduled, instances)
    sitters = [p for p in scheduled if p["player_id"] not in assignment]

    conflicts = []
    if sitters:
        kind = (
            "slot_overflow"
            if len(scheduled) > len(instances)
            else "eligibility_jam"
        )
        for p in sitters:
            conflicts.append(
                {
                    "kind": kind,
                    "scoring_period_id": scoring_period_id,
                    "player_id": p["player_id"],
                    "player_name": p["name"],
                    "reason": (
                        f"scheduled player must sit: {len(scheduled)} scheduled "
                        f"for {len(instances)} starting slots"
                        if kind == "slot_overflow"
                        else "scheduled player must sit: no starting slot he "
                        "is eligible for is available (eligibility jam)"
                    ),
                    "detail": {
                        "value": p["value"],
                        "value_source": p["value_source"],
                        "eligible_slots": sorted(
                            set(p["eligible_slots"]) & STARTING_SLOT_IDS
                        ),
                        "scheduled_count": len(scheduled),
                        "starting_slots": len(instances),
                        "on_ir": p["current_slot"] == IR_SLOT,
                    },
                }
            )

    # Target slot for every player. Starters come from the matching;
    # everyone else keeps a bench/IR placement that respects capacities.
    # Placement order matters when bench+IR cannot hold everyone (an
    # eligibility jam leaves a starting slot empty): current IR
    # occupants stay parked, OUT players take IR, current bench players
    # keep their seats, sitters take what's left, and unscheduled
    # starters are last — they can legally stay in a leftover slot.
    def _placement_group(p):
        if p["current_slot"] == IR_SLOT:
            return 0
        if p["out"]:
            return 1
        if p["current_slot"] == BENCH_SLOT:
            return 2
        if p["scheduled"]:
            return 3
        return 4

    target: dict = dict(assignment)
    bench_left = max(0, counts.get(BENCH_SLOT, 0))
    ir_left = max(0, counts.get(IR_SLOT, 0))
    others = [p for p in players if p["player_id"] not in target]
    others.sort(key=lambda p: (_placement_group(p), p["player_id"]))
    for p in others:
        pid = p["player_id"]
        eligible = set(p["eligible_slots"])
        if p["current_slot"] == IR_SLOT and ir_left > 0:
            target[pid] = IR_SLOT
            ir_left -= 1
        elif p["out"] and IR_SLOT in eligible and ir_left > 0:
            target[pid] = IR_SLOT
            ir_left -= 1
        elif bench_left > 0:
            target[pid] = BENCH_SLOT
            bench_left -= 1
        elif IR_SLOT in eligible and ir_left > 0:
            target[pid] = IR_SLOT
            ir_left -= 1
        elif (
            p["current_slot"] in STARTING_SLOT_IDS
            and list(target.values()).count(p["current_slot"])
            < counts.get(p["current_slot"], 0)
        ):
            # Nowhere legal to move him: he keeps the (otherwise empty)
            # starting slot and scores nothing today. Not a conflict —
            # he is not scheduled.
            target[pid] = p["current_slot"]
        else:
            target[pid] = BENCH_SLOT
            conflicts.append(
                {
                    "kind": "eligibility_jam",
                    "scoring_period_id": scoring_period_id,
                    "player_id": pid,
                    "player_name": p["name"],
                    "reason": "no legal bench/IR slot available in the plan; "
                    "player left in place",
                    "detail": {"placement": "no_legal_slot"},
                }
            )

    moves = []
    plan_players = []
    for p in sorted(players, key=lambda p: p["player_id"]):
        to_slot = target.get(p["player_id"], p["current_slot"])
        plan_players.append(
            {
                "player_id": p["player_id"],
                "name": p["name"],
                "scheduled": p["scheduled"],
                "out": p["out"],
                "value": p["value"],
                "value_source": p["value_source"],
                "from_slot": p["current_slot"],
                "to_slot": to_slot,
            }
        )
        if to_slot is not None and to_slot != p["current_slot"]:
            moves.append(
                {
                    "playerId": p["player_id"],
                    "fromLineupSlotId": p["current_slot"],
                    "toLineupSlotId": to_slot,
                }
            )

    return {
        "team_id": team.get("id"),
        "scoring_period_id": scoring_period_id,
        "players": plan_players,
        "moves": moves,
        "scheduled_player_ids": [p["player_id"] for p in scheduled],
        "sitting_player_ids": [p["player_id"] for p in sitters],
        "conflicts": conflicts,
    }


# --- run log storage -------------------------------------------------------------


def record_run(supabase, run: dict) -> dict:
    """Append one run row to espn_lineup_runs; returns the stored shape."""
    row = {
        "account_id": run["account_id"],
        "league_id": run["league_id"],
        "season": run["season"],
        "scoring_period_id": run.get("scoring_period_id"),
        "mode": run.get("mode") or "live",
        "status": run["status"],
        "plan": run.get("plan"),
        "moves": run.get("moves") or [],
        "conflicts": run.get("conflicts") or [],
        "error": run.get("error"),
    }
    res = supabase.table("espn_lineup_runs").insert(row).execute()
    stored = (res.data or [{}])[0] if res.data else {}
    return {**row, "id": stored.get("id"), "created_at": stored.get("created_at")}


def list_runs(supabase, account_id, limit: int = 25,
              scoring_period_id: int | None = None) -> dict:
    """Newest lineup runs for one account (and only that account).

    ``scoring_period_id`` narrows the list to one day — that is how a
    specific adhoc run (say, the first live write for a future date) is
    pulled up for inspection.
    """
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    query = (
        supabase.table("espn_lineup_runs")
        .select(
            "id,league_id,season,scoring_period_id,mode,status,plan,moves,"
            "conflicts,error,created_at"
        )
        .eq("account_id", account_id)
    )
    if scoring_period_id is not None:
        query = query.eq("scoring_period_id", scoring_period_id)
    res = query.order("created_at", desc=True).limit(limit).execute()
    runs = list(res.data or [])
    return {"runs": runs, "count": len(runs)}


# --- the runner ------------------------------------------------------------------


def _verify(client, account: dict, plan: dict) -> list:
    """Re-read the roster FOR THE PLAN'S PERIOD and diff actual slots.

    Returns a list of verify_mismatch conflict records (empty = the
    lineup on ESPN matches the plan exactly).
    """
    payload = (
        client.get_league(
            ["mTeam", "mRoster"],
            scoring_period_id=plan.get("scoring_period_id"),
        )
        or {}
    )
    team = find_member_team(payload, account["swid"])
    actual = {
        p["player_id"]: p["current_slot"] for p in _parse_roster(team)
    }
    mismatches = []
    for entry in plan.get("players") or []:
        pid = entry["player_id"]
        if actual.get(pid) != entry["to_slot"]:
            mismatches.append(
                {
                    "kind": "verify_mismatch",
                    "scoring_period_id": plan.get("scoring_period_id"),
                    "player_id": pid,
                    "player_name": entry.get("name"),
                    "reason": "lineup on ESPN does not match the submitted plan",
                    "detail": {
                        "expected_slot": entry["to_slot"],
                        "actual_slot": actual.get(pid),
                    },
                }
            )
    return mismatches


def run_lineup(supabase, account: dict, client, dry_run: bool = False,
               scoring_period_id: int | None = None,
               date: str | None = None) -> dict:
    """Plan (and, unless dry_run, submit + verify) one day's lineup.

    The target day comes from ``scoring_period_id``, or ``date``
    (YYYY-MM-DD) resolved against the league's scoring periods, or —
    with neither — the league's current scoring period (one code path
    serves every trigger: endpoint, MCP tool, batch entrypoint).

    Always persists and returns the run record — including auth and
    other failures — so conflicts are pullable afterwards.
    """
    run = {
        "account_id": account["id"],
        "league_id": account["league_id"],
        "season": account["season"],
        "scoring_period_id": scoring_period_id,
        "mode": "dry_run" if dry_run else "live",
        "status": "error",
        "plan": None,
        "moves": [],
        "conflicts": [],
        "error": None,
    }
    try:
        base = client.get_league(["mSettings", "mTeam", "mRoster"]) or {}
        period = resolve_scoring_period(
            base, date=date, scoring_period_id=scoring_period_id
        )
        run["scoring_period_id"] = period
        current = (base.get("status") or {}).get("currentScoringPeriod")
        payload = base
        if current is None or int(current) != period:
            # Future (or past) day: plan against that period's own
            # roster state, not today's.
            scoped = (
                client.get_league(
                    ["mSettings", "mTeam", "mRoster"],
                    scoring_period_id=period,
                )
                or {}
            )
            if scoped:
                payload = scoped
        team = find_member_team(payload, account["swid"])
        playing = pro_teams_playing(payload, period)
        if playing is None:
            playing = pro_teams_playing(base, period)
        if playing is None:
            raise ValueError(
                "ESPN payload has no proGamesByScoringPeriod schedule "
                "block; refusing to guess who is scheduled"
            )
        plan = plan_lineup(team, payload, period, playing)
        plan["requested"] = {"date": date, "scoring_period_id": scoring_period_id}
        run["plan"] = plan
        run["moves"] = plan["moves"]
        run["conflicts"] = list(plan["conflicts"])

        if dry_run:
            run["status"] = "dry_run"
            return record_run(supabase, run)

        if plan["moves"]:
            response = client.post_lineup_transaction(
                member_id=account["swid"],
                team_id=team.get("id"),
                scoring_period_id=period,
                items=plan["moves"],
            )
            txn_status = response.get("status") if isinstance(response, dict) else None
            if txn_status not in (None, "EXECUTED"):
                run["conflicts"].append(
                    {
                        "kind": "verify_mismatch",
                        "scoring_period_id": period,
                        "player_id": None,
                        "player_name": None,
                        "reason": f"ESPN transaction status is {txn_status}",
                        "detail": {"transaction_status": txn_status},
                    }
                )
            mismatches = _verify(client, account, plan)
            run["conflicts"].extend(mismatches)

        kinds = {c["kind"] for c in run["conflicts"]}
        if "verify_mismatch" in kinds:
            run["status"] = "verify_mismatch"
        elif run["conflicts"]:
            run["status"] = "conflict"
        elif plan["moves"]:
            run["status"] = "ok"
        else:
            run["status"] = "noop"
        return record_run(supabase, run)
    except EspnAuthError as e:
        # Conflict-level event: record it and stop — no retries.
        run["status"] = "auth_error"
        run["error"] = str(e)
        run["conflicts"] = [
            {
                "kind": "auth",
                "scoring_period_id": run.get("scoring_period_id"),
                "player_id": None,
                "player_name": None,
                "reason": "ESPN cookies expired or were rejected; "
                "re-onboard with fresh espn_s2/SWID cookies",
                "detail": {"error": str(e)},
            }
        ]
        return record_run(supabase, run)
    except (EspnError, ValueError) as e:
        run["status"] = "error"
        run["error"] = str(e)
        return record_run(supabase, run)
