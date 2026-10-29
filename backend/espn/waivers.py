"""Waiver-wire analytics for one account: free-agent form, pocket picks,
and the account's own drop candidates.

Powers the daily waiver report. Everything is computed live from the
account's ESPN league (no snapshots, no writes):

  - The free-agent pool is the kona player pool (``EspnClient.get_players``)
    minus every player rostered in this league (league-payload rosters and
    the pool entries' ``onTeamId`` are both honoured).
  - Recent form comes from per-scoring-period kona fetches
    (``EspnClient.get_players_for_period``): one fetch per day for the
    trailing 15 scoring periods gives exact games played and per-game
    fantasy points for the last-15-days and last-7-days windows. A scoring
    period is one day, so the windows are period ranges
    ``[current-14, current]`` and ``[current-6, current]``.
  - Fantasy points are ALWAYS the shared conversion — the league's own
    scoring items (``lineup.scoring_items``) applied through
    ``lineup._applied_total`` (ESPN's appliedTotal when the payload
    carries one, otherwise the scoring items applied to the raw stat
    line). There is deliberately no second scoring implementation here.
  - Season rate prefers the season split's ``appliedAverage`` (ESPN's own
    per-game average under league scoring); when a split lacks it, the
    fallback is the season total over the current scoring period (a
    per-day rate) and the response's ``notes`` say so.
  - ``games_next_7d`` counts, per pro team, the next 7 scoring periods in
    which the team plays: the league payload's ``proGamesByScoringPeriod``
    block first, the public scoreboard (period dates anchored off the
    block, periods advancing one per calendar day — the lineup runner's
    own rule) when a period is missing from the block. Periods neither
    source covers are excluded and the shortfall is disclosed in
    ``notes``.

Pocket picks are a deterministic subset of the free-agent list
(low ownership when known, plus at least one of: a last-15 breakout vs
the player's season rate, a top-10 last-7 rate in the pool, or a heavy
upcoming schedule with above-median last-15 form). Drop candidates are
the account's own roster, worst recent form first, with OUT / IR
players excluded and named in ``notes``.

Read-only: this module never calls the lineup transaction path.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone

from . import lineup, logic
from .espn_client import EspnAuthError, EspnError

LAST15_PERIODS = 15
LAST7_PERIODS = 7
FREE_AGENT_LIMIT = 25
POCKET_PICK_LIMIT = 8
DROP_LIMIT = 5
POOL_LIMIT = 1000

# ESPN pro team ids -> abbreviations. Cosmetic only: ids drive every
# computation (schedule counts included); the abbreviation is display.
# NOTE: espn/scoreboard.py's docstring claims WSH is id 27; the widely
# used ESPN team-id map (and ESPN's own team pages) put Utah at 27 and
# Washington at 28, which is what this map follows. Flagged in the PR.
PRO_TEAM_ABBR = {
    1: "ATL", 2: "BOS", 3: "NOP", 4: "CHI", 5: "CLE", 6: "DAL",
    7: "DEN", 8: "DET", 9: "GSW", 10: "HOU", 11: "IND", 12: "LAC",
    13: "LAL", 14: "MIA", 15: "MIL", 16: "MIN", 17: "BKN", 18: "NYK",
    19: "ORL", 20: "PHI", 21: "PHX", 22: "POR", 23: "SAC", 24: "SAS",
    25: "OKC", 26: "TOR", 27: "UTA", 28: "WAS", 29: "MEM", 30: "CHA",
}

_NON_POSITION_SLOTS = {12, 13}  # BE / IR are lineup slots, not positions


# --- payload extraction ---------------------------------------------------------


def _entry_player(entry) -> dict:
    """The player object of a kona pool entry (either entry shape)."""
    if not isinstance(entry, dict):
        return {}
    player = entry.get("player")
    if isinstance(player, dict):
        return player
    pooled = entry.get("playerPoolEntry")
    if isinstance(pooled, dict) and isinstance(pooled.get("player"), dict):
        return pooled["player"]
    return {}


def _entry_player_id(entry, player: dict):
    pid = entry.get("id") if isinstance(entry, dict) else None
    if pid is None:
        pid = player.get("id")
    return pid


def _positions(player: dict) -> list:
    names = []
    for slot in player.get("eligibleSlots") or []:
        if not isinstance(slot, int) or slot in _NON_POSITION_SLOTS:
            continue
        name = logic._position_name(slot)
        if name and name not in names:
            names.append(name)
    default = logic._position_name(player.get("defaultPositionId"))
    if default and default not in names:
        names.insert(0, default)
    return names


def _season_split(player: dict, items: list) -> dict:
    """Season totals from the player's unscoped splits.

    Returns {"total": float|None, "per_game": float|None,
    "per_game_is_per_day": bool}. The season split is statSplitTypeId 1
    with statSourceId 0 (actual) — the same mapping lineup.player_value
    and logic's trend reader use.
    """
    total = None
    per_game = None
    for stat in player.get("stats") or []:
        if not isinstance(stat, dict):
            continue
        if stat.get("statSplitTypeId") != 1:
            continue
        if stat.get("statSourceId") not in (0, None):
            continue
        value = lineup._applied_total(stat, items)
        if value is None:
            continue
        total = value
        average = stat.get("appliedAverage")
        if isinstance(average, (int, float)):
            per_game = float(average)
        break
    return {"total": total, "per_game": per_game}


def _day_fantasy_points(player: dict, period: int, items: list):
    """One scoring period's actual fantasy points for a player, or None.

    Picks the actual (statSourceId 0) split scoped to ``period`` out of a
    period-scoped kona entry; a missing/None result means the player did
    not record a game that day.
    """
    candidates = []
    for stat in player.get("stats") or []:
        if not isinstance(stat, dict):
            continue
        if stat.get("statSourceId") not in (0, None):
            continue
        entry_period = stat.get("scoringPeriodId")
        if entry_period is not None and entry_period != period:
            continue
        candidates.append(stat)
    for stat in candidates:
        if stat.get("statSplitTypeId") in (0, None):
            value = lineup._applied_total(stat, items)
            if value is not None:
                return value
    for stat in candidates:
        value = lineup._applied_total(stat, items)
        if value is not None:
            return value
    return None


def _fetch_day_points(client, periods: list, items: list):
    """{player_id: {period: fantasy points}} over the given periods.

    A failed period fetch is recorded and skipped (the windows just get
    thinner); an auth failure is fatal and propagates — expired cookies
    must surface as a 401, not as an empty report.
    """
    by_player: dict = {}
    failed = []
    for period in periods:
        try:
            entries = client.get_players_for_period(period, limit=POOL_LIMIT)
        except EspnAuthError:
            raise
        except EspnError:
            failed.append(period)
            continue
        for entry in entries or []:
            player = _entry_player(entry)
            pid = _entry_player_id(entry, player)
            if pid is None:
                continue
            value = _day_fantasy_points(player, period, items)
            if value is not None:
                by_player.setdefault(pid, {})[period] = value
    return by_player, failed


# --- schedule (next 7 days) -------------------------------------------------------


def _team_games_next_7d(payload: dict, current: int, scoreboard) -> tuple:
    """({pro_team_id: games in next 7 periods}, covered_period_count).

    The league payload's proGamesByScoringPeriod block is authoritative
    for the periods it publishes. For unpublished periods the public
    scoreboard is consulted when one is injected, with the period's
    date anchored off the block (periods advance one per calendar day).
    """
    block = payload.get("proGamesByScoringPeriod")
    date_map = lineup._period_date_map(payload)
    anchor = None
    if date_map:
        anchor_period = min(date_map, key=lambda q: abs(q - (current + 1)))
        anchor = (anchor_period, date_map[anchor_period])

    counts: dict = {}
    covered = 0
    for period in range(current + 1, current + 8):
        playing = None
        if isinstance(block, dict) and (
            str(period) in block or period in block
        ):
            playing = lineup.pro_teams_playing(payload, period)
        if playing is None and scoreboard is not None and anchor is not None:
            day = anchor[1] + timedelta(days=period - anchor[0])
            try:
                playing = scoreboard.teams_on(day)
            except EspnError:
                playing = None
        if playing is None:
            continue
        covered += 1
        for team_id in playing:
            counts[team_id] = counts.get(team_id, 0) + 1
    return counts, covered


# --- reasons ---------------------------------------------------------------------


def _base_reasons(rec: dict) -> list:
    reasons = []
    pg15, pg_season = rec["fp_pg_last15"], rec["fp_pg_season"]
    if pg15 is not None and pg_season is not None:
        reasons.append(
            f"{pg15:.1f} FP/g last 15 vs {pg_season:.1f} season"
        )
    elif pg15 is not None:
        reasons.append(
            f"{pg15:.1f} FP/g over {rec['games_played_last15']} games "
            "in the last 15 days"
        )
    if rec["fp_last3_games"]:
        last3 = ", ".join(f"{v:.0f}" for v in rec["fp_last3_games"])
        reasons.append(f"last 3 games: {last3} FP")
    change = rec["ownership_change"]
    if change is not None and abs(change) >= 1.0:
        direction = "climbing" if change > 0 else "falling"
        reasons.append(
            f"ownership {direction} ({change:+.1f} pts, ESPN percentChange)"
        )
    if rec["games_next_7d"]:
        reasons.append(f"{rec['games_next_7d']} games in the next 7 days")
    return reasons


# --- the report -------------------------------------------------------------------


def _period_int(value) -> int | None:
    """Lenient scoring-period coercion (the lineup runner int()s the
    same status fields): ints pass, integral floats and digit strings
    convert, everything else is None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def get_waivers(client, swid, scoreboard=None) -> dict:
    """The waiver-wire report for the account behind ``client``.

    ``swid`` is the account's own SWID (used only to resolve the
    account's team for drop candidates, exactly like the lineup
    runner). ``scoreboard`` is an optional ScoreboardClient for the
    schedule fallback. Raises EspnAuthError / EspnError from the wire,
    ValueError when the current scoring period can be neither read
    from the payload nor derived — from its pro-games schedule, or
    from the public scoreboard when the payload carries no schedule
    at all.
    """
    payload = client.get_league(["mSettings", "mTeam", "mRoster"]) or {}
    items = lineup.scoring_items(payload)
    notes: list[str] = []
    status = payload.get("status") or {}
    first = _period_int(status.get("firstScoringPeriod"))
    if first is None:
        first = 1
    current = _period_int(status.get("currentScoringPeriod"))
    if current is None:
        # ESPN omits currentScoringPeriod in-season (first seen on
        # opening day 2026-10-20; the lineup runner documents the same
        # reality and falls back identically): derive today's period
        # from the pro-games block's period->date map.
        today = datetime.now(lineup._ET).date()
        if isinstance(payload.get("proGamesByScoringPeriod"), dict):
            current = lineup.resolve_scoring_period(
                payload, date=today.isoformat()
            )
            notes.append(
                "the league payload omitted status.currentScoringPeriod; "
                f"the current period ({current}) was derived from the "
                "pro-games schedule for today's date (America/New_York), "
                "the lineup runner's fallback"
            )
        elif scoreboard is not None:
            # The payload carries no pro-games block either (the live
            # reality after #169): anchor on the public scoreboard the
            # way the runner's no-date path does — period ``first``
            # falls on the season's first regular-season date and
            # periods advance one per calendar day.
            start, end = lineup._scoreboard_window(client.season)
            season_start = scoreboard.first_regular_season_date(start, end)
            if season_start is not None:
                derived = first + (today - season_start).days
                if derived >= first:
                    current = derived
                    notes.append(
                        "the league payload omitted "
                        "status.currentScoringPeriod and carried no "
                        f"pro-games schedule; the current period "
                        f"({current}) was derived from the public "
                        f"scoreboard: period {first} began on the "
                        "season's first regular-season date "
                        f"({season_start.isoformat()}), and periods "
                        "advance one per calendar day "
                        "(America/New_York) — the lineup runner's anchor"
                    )
        if current is None:
            raise ValueError("league payload has no current scoring period")
    last15_start = max(first, current - (LAST15_PERIODS - 1))
    last7_start = max(first, current - (LAST7_PERIODS - 1))
    notes.append(
        f"windows are scoring periods (1 period = 1 day): last 15 = "
        f"periods {last15_start}-{current}, last 7 = periods "
        f"{last7_start}-{current}; the current period may still be in "
        f"progress, so its stats are partial"
    )
    if not items:
        notes.append(
            "league payload carried no scoring items; fantasy points use "
            "ESPN's applied totals only"
        )

    # Rosters: who is taken, and the account's own team.
    teams = logic._teams(payload)
    rostered_ids: set = set()
    own_team = None
    own_roster: dict = {}  # player_id -> {player, lineup_slot_id}
    try:
        own_team = lineup.find_member_team(payload, swid)
    except ValueError:
        notes.append(
            "could not resolve the account's team in this league; "
            "drop candidates skipped"
        )
    own_team_id = own_team.get("id") if own_team else None
    for team in teams:
        entries = ((team.get("roster") or {}).get("entries")) or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            player = ((entry.get("playerPoolEntry") or {}).get("player")) or {}
            pid = entry.get("playerId")
            if pid is None and isinstance(player, dict):
                pid = player.get("id")
            if pid is None:
                continue
            rostered_ids.add(pid)
            if own_team is not None and team.get("id") == own_team_id:
                own_roster[pid] = {
                    "player": player if isinstance(player, dict) else {},
                    "lineup_slot_id": entry.get("lineupSlotId"),
                }

    # The pool.
    pool: dict = {}  # player_id -> {player, on_team_id}
    raw_pool = client.get_players(POOL_LIMIT) or []
    for entry in raw_pool:
        player = _entry_player(entry)
        pid = _entry_player_id(entry, player)
        if pid is None:
            continue
        pool[pid] = {"player": player, "on_team_id": entry.get("onTeamId")}
    # TEMP PROBE (shape diagnostic; remove once the live kona shape is known)
    def _shape(entries):
        if not entries:
            return "no entries"
        e = entries[0]
        if not isinstance(e, dict):
            return f"first entry is {type(e).__name__}"
        parts = [f"count={len(entries)}", f"entry_keys={sorted(e.keys())}"]
        p = e.get("player")
        if isinstance(p, dict):
            parts.append(f"player_keys={sorted(p.keys())}")
            parts.append(f"player_stats={len(p.get('stats') or [])}")
            parts.append(f"player_ownership={type(p.get('ownership')).__name__}")
        else:
            parts.append(f"player_field={type(p).__name__}")
        parts.append(f"top_stats={len(e.get('stats') or [])}")
        parts.append(f"top_ownership={type(e.get('ownership')).__name__}")
        return "; ".join(parts)

    notes.append("PROBE pool: " + _shape(raw_pool))
    try:
        probe_entries = client.get_players_for_period(current, limit=5) or []
        notes.append("PROBE period: " + _shape(probe_entries))
    except Exception as exc:  # probe only; never fail the report on it
        notes.append(f"PROBE period fetch failed: {type(exc).__name__}")

    for pid, rostered in own_roster.items():
        if pid not in pool:
            pool[pid] = {"player": rostered["player"], "on_team_id": own_team_id}

    # Per-day form over the last-15 window.
    day_points, failed_periods = _fetch_day_points(
        client, list(range(last15_start, current + 1)), items
    )
    if failed_periods and len(failed_periods) < LAST15_PERIODS:
        notes.append(
            f"per-day stats unavailable for scoring periods "
            f"{failed_periods} (ESPN fetch failed); recent-form windows "
            f"are computed from the remaining days"
        )
    elif failed_periods:
        notes.append(
            "per-day stat fetches failed for the whole window; "
            "recent-form windows are unavailable"
        )

    # Schedule for the next 7 days.
    team_games_next7, covered = _team_games_next_7d(payload, current, scoreboard)
    if covered < 7:
        notes.append(
            f"games_next_7d covers {covered} of the next 7 days "
            f"(the rest is not published yet); counts may understate"
        )

    # Ownership presence (for the honesty note + the pocket-pick gate).
    any_ownership = any(
        isinstance((p["player"].get("ownership") or {}).get("percentOwned"), (int, float))
        for p in pool.values()
    )
    if not any_ownership:
        notes.append(
            "ownership data absent from the player payload; "
            "ownership_pct / ownership_change are null and the "
            "low-ownership pocket-pick rule was skipped"
        )

    season_per_day_used = False

    def build_record(pid: int, player: dict) -> dict:
        days = day_points.get(pid) or {}
        games15 = {p: v for p, v in days.items() if p >= last15_start}
        games7 = {p: v for p, v in days.items() if p >= last7_start}
        pg15 = (
            sum(games15.values()) / len(games15) if games15 else None
        )
        pg7 = sum(games7.values()) / len(games7) if games7 else None
        last3 = [games15[p] for p in sorted(games15)][-3:]
        season = _season_split(player, items)
        pg_season = season["per_game"]
        nonlocal season_per_day_used
        if pg_season is None and season["total"] is not None:
            pg_season = season["total"] / max(1, current)
            season_per_day_used = True
        ownership = player.get("ownership") or {}
        pro_team_id = player.get("proTeamId")
        return {
            "player_id": pid,
            "name": player.get("fullName"),
            "pro_team": PRO_TEAM_ABBR.get(pro_team_id),
            "positions": _positions(player),
            "injury_status": player.get("injuryStatus") or None,
            "ownership_pct": ownership.get("percentOwned"),
            "ownership_change": ownership.get("percentChange"),
            "games_played_last15": len(games15),
            "fp_pg_season": round(pg_season, 1) if pg_season is not None else None,
            "fp_pg_last15": round(pg15, 1) if pg15 is not None else None,
            "fp_pg_last7": round(pg7, 1) if pg7 is not None else None,
            "fp_last3_games": [round(v, 1) for v in last3],
            "games_next_7d": team_games_next7.get(pro_team_id, 0),
        }

    records = {
        pid: build_record(pid, entry["player"]) for pid, entry in pool.items()
    }
    if season_per_day_used:
        notes.append(
            "fp_pg_season is a per-day rate (season total / current "
            "scoring period) for players whose season split carries no "
            "per-game average"
        )

    def is_free_agent(pid: int) -> bool:
        if pid in rostered_ids:
            return False
        on_team = pool[pid]["on_team_id"]
        return on_team in (None, 0)

    free_agent_ids = [pid for pid in pool if is_free_agent(pid)]
    with_form = [
        records[pid]
        for pid in free_agent_ids
        if records[pid]["games_played_last15"] >= 1
        and records[pid]["fp_pg_last15"] is not None
    ]
    with_form.sort(
        key=lambda r: (-r["fp_pg_last15"], -(r["fp_pg_last7"] or 0), r["name"] or "")
    )
    free_agents = []
    for rec in with_form[:FREE_AGENT_LIMIT]:
        out = dict(rec)
        out["reasons"] = _base_reasons(rec)
        free_agents.append(out)

    # Pocket picks: a deterministic subset of the free-agent list.
    median15 = None
    if with_form:
        median15 = statistics.median(r["fp_pg_last15"] for r in with_form)
    hot7_ids = {
        r["player_id"]
        for r in sorted(
            (r for r in (records[pid] for pid in free_agent_ids)
             if r["fp_pg_last7"] is not None),
            key=lambda r: -r["fp_pg_last7"],
        )[:10]
    }
    pocket_picks = []
    for rec in free_agents:
        if len(pocket_picks) >= POCKET_PICK_LIMIT:
            break
        owned = rec["ownership_pct"]
        if owned is not None and owned > 20:
            continue
        pg15, pg_season, pg7 = (
            rec["fp_pg_last15"], rec["fp_pg_season"], rec["fp_pg_last7"],
        )
        reasons = []
        if (
            pg_season is not None and pg_season > 0
            and rec["games_played_last15"] >= 3
            and pg15 >= 1.4 * pg_season
        ):
            reasons.append(
                f"breakout: {pg15:.1f} FP/g last 15 is "
                f"{pg15 / pg_season:.1f}x his {pg_season:.1f} FP/g season rate "
                f"({rec['games_played_last15']} games)"
            )
        if rec["player_id"] in hot7_ids and pg7 is not None:
            reasons.append(
                f"scorching week: {pg7:.1f} FP/g last 7, top 10 among "
                f"free agents"
            )
        if (
            rec["games_next_7d"] >= 4
            and median15 is not None
            and pg15 > median15
        ):
            reasons.append(
                f"schedule edge: {rec['games_next_7d']} games in the next "
                f"7 days and {pg15:.1f} FP/g last 15 beats the free-agent "
                f"median {median15:.1f}"
            )
        if not reasons:
            continue
        if owned is not None:
            reasons.append(f"only {owned:.1f}% owned")
        out = dict(rec)
        out["reasons"] = reasons + [
            r for r in _base_reasons(rec) if r not in reasons
        ]
        pocket_picks.append(out)

    # Drop candidates: the account's own roster, worst recent form first.
    drop_candidates = []
    if own_team is not None:
        excluded_names = []
        eligible = []
        for pid, rostered in own_roster.items():
            rec = records.get(pid)
            if rec is None:
                continue
            on_ir = rostered["lineup_slot_id"] == lineup.IR_SLOT
            status = str(rec["injury_status"] or "").strip().upper()
            if on_ir or status in lineup.OUT_STATUSES:
                excluded_names.append(rec["name"] or str(pid))
                continue
            eligible.append(rec)
        if excluded_names:
            notes.append(
                "excluded from drop candidates (OUT or on IR): "
                + ", ".join(sorted(excluded_names))
            )

        def drop_key(rec):
            value = (
                rec["fp_pg_last15"]
                if rec["fp_pg_last15"] is not None
                else rec["fp_pg_last7"]
                if rec["fp_pg_last7"] is not None
                else rec["fp_pg_season"]
            )
            return (value is not None, value if value is not None else 0.0)

        eligible.sort(key=drop_key)
        for rec in eligible[:DROP_LIMIT]:
            out = dict(rec)
            reasons = _base_reasons(rec)
            if rec["fp_pg_last15"] is not None:
                reasons.insert(
                    0,
                    f"coldest on your roster: {rec['fp_pg_last15']:.1f} "
                    f"FP/g last 15",
                )
            out["reasons"] = reasons
            drop_candidates.append(out)

    return {
        "league_id": payload.get("id") or getattr(client, "league_id", None),
        "season": payload.get("seasonId") or getattr(client, "season", None),
        "scoring_period": current,
        "generated_at": datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "free_agents": free_agents,
        "pocket_picks": pocket_picks,
        "drop_candidates": drop_candidates,
        "notes": notes,
    }
