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
value is fantasy points per game under the ACCOUNT LEAGUE's own
scoring settings, ranked by preference: the day's projected fantasy
points when ESPN publishes a real projection for that day, otherwise
the player's recent-7-days fantasy PPG, otherwise his season fantasy
PPG (Warner's sharpened policy, 2026-10-23) — and every conflict is
recorded in the run log (see :func:`list_runs`) for the user to pull
on demand. Conflicts are recorded ONLY for scheduled players who
actually sit: an unscheduled player shuffling between bench, IR and
a leftover starting slot is correct placement, never a conflict,
even when the planner's bench/IR capacity accounting cannot
formally place him (he is moved to the bench, which ESPN accepts).

Moves are lineup slot moves only (plus IR activation / parking when
needed for a legal lineup). Adds, drops, trades and waiver claims are
out of scope and have no code path here.

Player locks are PER-PLAYER on ESPN: a player locks at his own game's
tip-off and cannot be moved afterwards, while every teammate whose
game has not started stays movable. ESPN validates a multi-item
transaction atomically, so one locked player in a batch rejects the
WHOLE transaction (live, 2026-10-24: the evening pass lost all 5
moves to a 409 "Naz Reid is locked", including an unrelated bench
player's start). The runner therefore pre-filters moves for players
whose game has already tipped — tip-offs come from the pro-games
block, or the scoreboard in the fallback path — and records each
exclusion in the plan's ``locked_skips`` (kind ``player_locked``):
never a conflict, never a run failure. As a safety net for a game
tipping between plan and submit, a 409 that names a locked player is
answered by dropping that player's moves and retrying the rest
(bounded: each retry removes at least one player's moves).

The roster cap is a second legality the planner itself must respect:
ESPN counts only ACTIVE players (starters + bench) against the
roster maximum — the IR slot is extra. Activating an IR player while
the active roster is already at the cap, with no OUT / IR-eligible
player able to take his IR spot, yields a final state ESPN rejects
outright (live, 2026-10-24 morning: 409 "Too many players on roster
(maximum 13)", 0 of 8 moves applied). No item ordering fixes an
illegal final state, so the planner pins such a player to IR: he
sits, recorded as a ``roster_cap`` conflict, and the rest of the
lineup is still set.

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

Schedule sources: the league payload's ``proGamesByScoringPeriod``
block is preferred when present, but it is not always there (in
preseason the payload carries no block at all). When it is absent the
runner falls back to ESPN's public scoreboard (see
``espn/scoreboard.py`` — no auth, canonical pro-team ids): scoring
period 1 anchors on the first regular-season date and periods
advance one per calendar day. Any period or playing set derived from
the fallback must pass the schedule gate (see :func:`_schedule_gate`)
against the candidate period's projected teams before anything
is planned, let alone submitted — on a poor match the run records a
clean error and submits nothing.

The gate's projected teams (P) come from the period-scoped roster
payload when it carries per-period projected splits, and from the
kona player feed filtered to the period when it does not (in
preseason ESPN publishes per-day projections in kona only — inside
roster payloads there are none). One exception, deliberately narrow:
when NO projection data exists anywhere for any candidate — roster
payloads and kona both checked, both empty — the gate has nothing to
check, so the period resolves by the deterministic formula alone
(firstScoringPeriod + days since the first regular-season date) and
the run records ``schedule.gate = "unverifiable_no_projection_data"``.
The gate exists to catch anchor misalignment; with zero published
projections it cannot, and a mislabeled future day self-heals
because every day is re-planned by its own run. The instant any
projection data exists for any candidate, the full gate applies and
this fallback is unreachable.
"""

from __future__ import annotations

import json
from datetime import date as _date
from datetime import datetime, timedelta, timezone
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


def pro_team_tipoffs(payload: dict, scoring_period_id: int):
    """{pro team id: earliest tip-off datetime} for the period.

    Reads the same ``proGamesByScoringPeriod`` block as
    :func:`pro_teams_playing`; each game carries its tip-off as an
    epoch-ms ``date``. Returns None when the block is absent entirely
    (callers fall back to the scoreboard), and an empty dict when the
    block exists but publishes no dates — no lock information, which
    the caller treats as "nothing known to be locked" and leaves to
    the 409 retry safety net.
    """
    block = payload.get("proGamesByScoringPeriod")
    if not isinstance(block, dict):
        return None
    games = block.get(str(scoring_period_id))
    if games is None:
        games = block.get(scoring_period_id)
    tipoffs: dict[int, datetime] = {}
    for game in games or []:
        if not isinstance(game, dict):
            continue
        raw = game.get("date")
        if not isinstance(raw, (int, float)):
            continue
        moment = datetime.fromtimestamp(raw / 1000, tz=timezone.utc)
        for key in ("homeProTeamId", "awayProTeamId", "proTeamId"):
            value = game.get(key)
            if isinstance(value, int) and (
                value not in tipoffs or moment < tipoffs[value]
            ):
                tipoffs[value] = moment
    return tipoffs


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


# --- schedule fallback: the public scoreboard ----------------------------------
#
# Used only when the league payload has no proGamesByScoringPeriod
# block. ``scoreboard`` is duck-typed (espn.scoreboard.ScoreboardClient):
# teams_on(date) -> set[int] and first_regular_season_date(start, end)
# -> date | None. Nothing in this section runs when the block is
# present or when no scoreboard was injected. The gate's projected
# teams come from the roster payload, or from the kona player feed
# when the payload publishes no per-period projections (see
# _gate_projected_teams).

# A derived period/slate is trusted only when the intersection covers
# at least this share of BOTH the scoreboard set and the projected set.
GATE_MIN_OVERLAP = 0.8


def _first_scoring_period(payload: dict) -> int:
    first = (payload.get("status") or {}).get("firstScoringPeriod")
    if isinstance(first, int) and first >= 1:
        return first
    return 1


def _scoreboard_window(season) -> tuple[_date, _date]:
    """Fetch window for finding the season's first regular-season date.

    A fantasy ``season`` is the ending year (2027 = the 2026-27
    season), so its games start in the fall of season - 1. Oct 1 to
    Nov 30 covers any plausible NBA opening date, plus room for the
    calibration neighbours around it.
    """
    year = int(season) - 1
    return _date(year, 10, 1), _date(year, 11, 30)


def _entry_player(entry: dict) -> dict:
    """The player dict of a roster or kona entry ({} when absent).

    Roster entries nest it under ``playerPoolEntry.player``; kona
    player-feed entries carry it at top level as ``player``.
    """
    pool = entry.get("playerPoolEntry")
    if isinstance(pool, dict) and isinstance(pool.get("player"), dict):
        return pool["player"]
    player = entry.get("player")
    return player if isinstance(player, dict) else {}


def _projected_teams_from_entries(entries, scoring_period_id: int) -> set:
    """Pro teams with at least one player projected for the period.

    A player counts when his stat splits carry a projected entry
    (statSourceId 1) whose scoringPeriodId is the target period — the
    same test :func:`player_value` uses for its day projection.
    """
    teams = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        player = _entry_player(entry)
        pro_team = player.get("proTeamId")
        if not isinstance(pro_team, int):
            continue
        for stat in player.get("stats") or []:
            if (
                isinstance(stat, dict)
                and stat.get("statSourceId") == 1
                and stat.get("scoringPeriodId") == scoring_period_id
            ):
                teams.add(pro_team)
                break
    return teams


def _projected_teams(payload: dict, scoring_period_id: int) -> set:
    """Projected teams from a league payload: every roster counts,
    not just the member's team — the wider the pool, the sharper the
    gate's signal."""
    entries = []
    for team in payload.get("teams") or []:
        if not isinstance(team, dict):
            continue
        entries.extend(((team.get("roster") or {}).get("entries")) or [])
    return _projected_teams_from_entries(entries, scoring_period_id)


def _kona_projected_teams(client, scoring_period_id: int):
    """(teams, note): projected teams from the kona player feed.

    ``note`` is None when the feed answered (the team set may still
    be empty — that is a completed check); a string when the check
    could not be completed (the client has no period fetch, or ESPN
    errored), which callers must NOT treat as "checked, empty".
    Auth failures propagate: dead cookies stop the run.
    """
    getter = getattr(client, "get_players_for_period", None)
    if getter is None:
        return set(), "kona_unavailable"
    try:
        entries = getter(scoring_period_id)
    except EspnAuthError:
        raise
    except EspnError as e:
        return set(), f"kona_error: {e}"
    return _projected_teams_from_entries(entries, scoring_period_id), None


def _gate_projected_teams(client, scoped_payload, scoring_period_id, kona_cache):
    """(teams, p_source, kona_note): the gate's P for one period.

    The period-scoped roster payload is the first source. When it
    yields no per-period projected splits for the period — the
    preseason reality, where ESPN publishes per-day projections only
    in the kona feed — P is computed from kona filtered to the
    period instead. ``p_source`` is "roster", "kona", or "none"
    (checked everywhere, nothing published); ``kona_note`` carries
    why a kona check could not be completed, else None. Kona answers
    are memoised in ``kona_cache`` ({period: (teams, note)}) so a
    multi-candidate calibration fetches each period at most once.
    """
    roster_teams = _projected_teams(scoped_payload, scoring_period_id)
    if roster_teams:
        return roster_teams, "roster", None
    if scoring_period_id in kona_cache:
        teams, note = kona_cache[scoring_period_id]
    else:
        teams, note = _kona_projected_teams(client, scoring_period_id)
        kona_cache[scoring_period_id] = (teams, note)
    if teams:
        return teams, "kona", note
    return set(), "none", note


def _schedule_gate(scoreboard_teams, projected_teams):
    """The consistency gate for scoreboard-derived schedule facts.

    Compares S (the pro teams the public scoreboard says play on the
    target date) with P (the pro teams the period-scoped fantasy
    payload projects for the candidate period):

    - both empty: a consistent no-games day — pass;
    - exactly one side empty: fail;
    - otherwise pass iff the intersection covers at least
      GATE_MIN_OVERLAP of BOTH sets. The correct period projects
      (almost) exactly the teams playing that day; a period off by
      one projects a neighbouring slate, which shares only a
      fraction of the teams, so both coverages collapse.

    Returns (passed, detail); the detail is recorded on the run.
    """
    S = set(scoreboard_teams or set())
    P = set(projected_teams or set())
    detail = {
        "scoreboard_teams": sorted(S),
        "projected_teams": sorted(P),
        "overlap": len(S & P),
    }
    if not S and not P:
        detail["verdict"] = "no games and no projections: consistent off day"
        return True, detail
    if not S or not P:
        detail["verdict"] = "exactly one side is empty"
        return False, detail
    inter = len(S & P)
    detail["scoreboard_coverage"] = round(inter / len(S), 3)
    detail["projection_coverage"] = round(inter / len(P), 3)
    passed = (
        inter / len(S) >= GATE_MIN_OVERLAP
        and inter / len(P) >= GATE_MIN_OVERLAP
    )
    detail["verdict"] = "match" if passed else "poor overlap"
    return passed, detail


def _scoreboard_tipoffs(scoreboard, target_date):
    """{str(pro team id): ISO tip-off} for schedule_info, or None.

    Duck-typed like the kona getter: a scoreboard without tip-off
    support (older fakes) simply yields None, and the runner then has
    no pre-filter lock source in the fallback path — the 409 retry
    net still guards the write.
    """
    getter = getattr(scoreboard, "team_tipoffs_on", None)
    if getter is None:
        return None
    try:
        tipoffs = getter(target_date)
    except EspnError:
        return None
    if not tipoffs:
        return None
    return {
        str(team_id): moment.isoformat()
        for team_id, moment in tipoffs.items()
    }


def _resolve_period_via_scoreboard(
    client, base, season, target_date, scoreboard
):
    """Resolve a calendar date to a scoring period WITHOUT the block.

    Anchor: scoring period ``first`` (the payload's
    firstScoringPeriod, default 1) falls on the first regular-season
    date D0 from the public scoreboard, and periods advance one per
    calendar day, so the anchor candidate is
    ``first + (target_date - D0).days``. The anchor is then
    calibrated: candidates are tried in the fixed order
    0, -1, +1, -2, +2, -3, +3 around it, and the first whose
    period-scoped payload passes the schedule gate against the
    target date's scoreboard slate wins.

    Formula-only fallback: when every candidate was actually checked
    (roster payload AND kona feed) and no projection data exists for
    any of them — ESPN has published no per-day projections yet, a
    preseason reality — the gate has nothing to verify against, so
    the anchor (the deterministic formula's answer) is used with
    ``gate = "unverifiable_no_projection_data"`` recorded. If any
    candidate produced projections and none passed, or any check
    could not be completed, this is unreachable and the run fails.

    Returns (period, scoped_payload, playing_teams, schedule_info).
    Raises ValueError when no candidate passes — nothing is planned
    or submitted on an unverified period. The error message carries
    the per-candidate gate diagnostics as JSON, so the recorded
    error run shows the actual numbers, not just a summary.
    """
    start, end = _scoreboard_window(season)
    d0 = scoreboard.first_regular_season_date(start, end)
    if d0 is None:
        raise ValueError(
            "ESPN scoreboard has no regular-season games in the "
            "season-start window; cannot resolve a date to a scoring period"
        )
    first = _first_scoring_period(base)
    anchor = first + (target_date - d0).days
    playing = scoreboard.teams_on(target_date)
    kona_cache: dict = {}
    tried = []
    anchor_scoped = None
    any_projected = False
    checks_complete = True
    for offset in (0, -1, 1, -2, 2, -3, 3):
        candidate = anchor + offset
        if candidate < first:
            continue
        scoped = (
            client.get_league(
                ["mSettings", "mTeam", "mRoster"],
                scoring_period_id=candidate,
            )
            or {}
        )
        if offset == 0:
            anchor_scoped = scoped
        projected, p_source, kona_note = _gate_projected_teams(
            client, scoped, candidate, kona_cache
        )
        if projected:
            any_projected = True
        if p_source == "none" and kona_note is not None:
            # This candidate's kona check never completed, so "no
            # projections anywhere" is not established for it.
            checks_complete = False
        passed, detail = _schedule_gate(playing, projected)
        detail["p_source"] = p_source
        attempt = {
            "period": candidate,
            "passed": passed,
            "scoreboard_count": len(playing),
            "projected_count": len(projected),
            "overlap": detail["overlap"],
            "p_source": p_source,
        }
        if kona_note is not None:
            attempt["p_note"] = kona_note
        tried.append(attempt)
        if passed:
            info = {
                "source": "scoreboard",
                "target_date": target_date.isoformat(),
                "season_start_date": d0.isoformat(),
                "anchor_period": anchor,
                "candidate_offset": offset,
                "candidates_tried": tried,
                "gate": detail,
            }
            tipoffs = _scoreboard_tipoffs(scoreboard, target_date)
            if tipoffs is not None:
                info["team_tipoffs"] = tipoffs
            return candidate, scoped, playing, info
    if anchor_scoped is not None and not any_projected and checks_complete:
        # No projection data exists anywhere: the gate cannot verify
        # the anchor, and there is nothing else it could check. The
        # gate exists to catch anchor misalignment; with zero
        # published projections it has no signal, and a mislabeled
        # future day self-heals because every day is re-planned by
        # its own run — so proceed on the formula alone and say so.
        info = {
            "source": "scoreboard",
            "target_date": target_date.isoformat(),
            "season_start_date": d0.isoformat(),
            "anchor_period": anchor,
            "candidate_offset": 0,
            "candidates_tried": tried,
            "gate": "unverifiable_no_projection_data",
            "formula": {
                "first_scoring_period": first,
                "season_start_date": d0.isoformat(),
                "days_since_season_start": (target_date - d0).days,
            },
        }
        tipoffs = _scoreboard_tipoffs(scoreboard, target_date)
        if tipoffs is not None:
            info["team_tipoffs"] = tipoffs
        return anchor, anchor_scoped, playing, info
    raise ValueError(
        "schedule gate: no scoring period near the anchor "
        f"({anchor}) matched the scoreboard slate for "
        f"{target_date.isoformat()}; refusing to submit; "
        "gate candidates: "
        + json.dumps({"anchor_period": anchor, "candidates": tried})
    )


def _scoreboard_fallback_playing(
    payload, base, season, period, target_date, scoreboard, client=None
):
    """Playing set for a known period when the pro-games block is absent.

    The period is already fixed (explicit, or the league's current
    one); only its calendar date is derived — from the given date,
    from today's ET date offset by the period's distance from the
    current period, or from the season-start anchor (the
    deterministic formula: firstScoringPeriod + days since the first
    regular-season date). The derived slate is gated against the
    period's projected teams (roster payload first, kona feed when
    the payload publishes none) before it is trusted.

    Same narrow exception as the date resolver: when no projection
    data exists for the period anywhere — both sources checked,
    both empty — the slate is accepted with
    ``gate = "unverifiable_no_projection_data"`` recorded, because
    the gate has nothing to check it against.

    Returns (playing_teams, schedule_info); raises ValueError on a
    gate failure — nothing is planned or submitted. The error
    message carries the gate detail as JSON for the recorded run.
    """
    if target_date is None:
        current = (base.get("status") or {}).get("currentScoringPeriod")
        if current is not None:
            today = datetime.now(_ET).date()
            target_date = today + timedelta(days=period - int(current))
        else:
            start, end = _scoreboard_window(season)
            d0 = scoreboard.first_regular_season_date(start, end)
            if d0 is None:
                raise ValueError(
                    "ESPN scoreboard has no regular-season games in the "
                    f"season-start window; cannot date scoring period {period}"
                )
            target_date = d0 + timedelta(
                days=period - _first_scoring_period(base)
            )
    playing = scoreboard.teams_on(target_date)
    if client is not None:
        projected, p_source, kona_note = _gate_projected_teams(
            client, payload, period, {}
        )
    else:
        projected = _projected_teams(payload, period)
        p_source = "roster" if projected else "none"
        kona_note = None if projected else "kona_unavailable"
    passed, detail = _schedule_gate(playing, projected)
    detail["p_source"] = p_source
    if kona_note is not None:
        detail["p_note"] = kona_note
    tipoffs = _scoreboard_tipoffs(scoreboard, target_date)
    if passed:
        info = {
            "source": "scoreboard",
            "target_date": target_date.isoformat(),
            "gate": detail,
        }
        if tipoffs is not None:
            info["team_tipoffs"] = tipoffs
        return playing, info
    if not projected and playing and kona_note is None:
        # Both sources were checked and neither publishes any
        # projection for this period: unverifiable, not mismatched.
        info = {
            "source": "scoreboard",
            "target_date": target_date.isoformat(),
            "gate": "unverifiable_no_projection_data",
            "gate_detail": detail,
        }
        if tipoffs is not None:
            info["team_tipoffs"] = tipoffs
        return playing, info
    raise ValueError(
        f"schedule gate: projected teams for scoring period {period} "
        "do not match the scoreboard slate for "
        f"{target_date.isoformat()}; refusing to submit; "
        f"gate: {json.dumps(detail)}"
    )


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

    Players are processed highest-value first (value = fantasy PPG:
    day projection, else recent-7, else season — see
    :func:`player_value`), and Kuhn's augmenting paths only ever
    rearrange slot assignments among already-matched players, never
    unmatch one. So a player is left unmatched only when no legal
    placement exists alongside the higher-value players matched
    before him: the sitters are the lowest-value scheduled players,
    subject to eligibility (a lower-value player may still start in
    a slot a higher-value sitter is not eligible for — that is the
    eligibility jam, and it is unavoidable in any legal lineup).
    Exact value ties break deterministically by player id: the
    caller sorts by (-value, player_id), so the lower id is matched
    first and the higher id sits. Returns {player_id: slot_id}.
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

    # Roster-cap legality: ESPN counts ACTIVE players (starters +
    # bench) against the roster maximum; the IR slot is extra, so at
    # least ``min_on_ir`` players must END on IR. The only players who
    # can legally be there are current IR occupants and OUT /
    # IR-eligible players. When releasing a scheduled IR occupant
    # would leave fewer than ``min_on_ir`` of them behind, his
    # activation makes the final state illegal and ESPN rejects the
    # whole transaction (the 2026-10-24 morning 409) — so he is
    # pinned to IR before matching: he sits (a roster_cap conflict
    # below) and the planner optimizes the rest without him. Release
    # capacity is spent on the highest-value scheduled occupants
    # first, consistent with the PPG policy.
    active_cap = sum(counts.values()) - counts.get(IR_SLOT, 0)
    min_on_ir = max(0, len(players) - active_cap)
    ir_pinned: set = set()
    if min_on_ir > 0:
        ir_capable = [
            p
            for p in players
            if p["current_slot"] == IR_SLOT
            or (p["out"] and IR_SLOT in p["eligible_slots"])
        ]
        releasable = max(0, len(ir_capable) - min_on_ir)
        candidates = sorted(
            (p for p in ir_capable if p["scheduled"]),
            key=lambda p: (-p["value"], p["player_id"]),
        )
        ir_pinned = {p["player_id"] for p in candidates[releasable:]}

    matchable = [p for p in scheduled if p["player_id"] not in ir_pinned]
    assignment = _match_scheduled(matchable, instances)
    sitters = [p for p in scheduled if p["player_id"] not in assignment]
    # Report sitters deterministically, lowest value first (ties by
    # player id): that is the order a reader scans "who sat, and who
    # was closest to starting". sitting_player_ids follows the same
    # order as the conflict records.
    sitters.sort(key=lambda p: (p["value"], p["player_id"]))

    conflicts = []
    if sitters:
        kind = (
            "slot_overflow"
            if len(matchable) > len(instances)
            else "eligibility_jam"
        )
        # The value comparison behind each sit decision: the weakest
        # scheduled player who DID get a starting slot. A sitter at or
        # below him lost on value; a sitter above him lost purely on
        # eligibility (no slot he can play was left).
        kept = [p for p in scheduled if p["player_id"] in assignment]
        lowest_kept = (
            min(kept, key=lambda p: (p["value"], p["player_id"]))
            if kept
            else None
        )
        for p in sitters:
            detail = {
                "value": p["value"],
                "value_source": p["value_source"],
                "eligible_slots": sorted(
                    set(p["eligible_slots"]) & STARTING_SLOT_IDS
                ),
                "scheduled_count": len(scheduled),
                "starting_slots": len(instances),
                "on_ir": p["current_slot"] == IR_SLOT,
                "lowest_starter_value": (
                    lowest_kept["value"] if lowest_kept else None
                ),
                "lowest_starter_value_source": (
                    lowest_kept["value_source"] if lowest_kept else None
                ),
                "lowest_starter_player_id": (
                    lowest_kept["player_id"] if lowest_kept else None
                ),
                "lowest_starter_name": (
                    lowest_kept["name"] if lowest_kept else None
                ),
            }
            if p["player_id"] in ir_pinned:
                # Not a value or eligibility loss: the roster cap
                # forbids his activation outright (see the pinning
                # above). He stays on IR and scores nothing today.
                detail["roster_size"] = len(players)
                detail["active_roster_max"] = active_cap
                detail["min_on_ir"] = min_on_ir
                conflicts.append(
                    {
                        "kind": "roster_cap",
                        "scoring_period_id": scoring_period_id,
                        "player_id": p["player_id"],
                        "player_name": p["name"],
                        "reason": (
                            "scheduled player must sit: he is on IR and "
                            f"activating him would put {len(players)} "
                            f"players on the active roster (maximum "
                            f"{active_cap}); no rostered player is "
                            "eligible to take the IR slot"
                        ),
                        "detail": detail,
                    }
                )
                continue
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
                    "detail": detail,
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
        elif p["out"] and IR_SLOT in eligible and ir_left > 0:
            # Only an actually injured / IR-eligible (OUT or
            # INJURY_RESERVE) player may be MOVED to IR. A healthy
            # displaced starter must never go there — ESPN rejects the
            # whole transaction ("player is not injured", opening day
            # 2026-10-20) — he falls through to keeping his starting
            # slot or, when that slot was taken, the bench below.
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
            # Bench/IR capacity accounting is exhausted, but there is
            # still a legal real-world placement: the bench (a move
            # another starter's vacated slot makes room for — ESPN
            # accepted exactly this on 2026-10-23, Mobley 3 -> 12).
            # This is NEVER a conflict on its own (Warner's policy,
            # 2026-10-23): a player landing here is either unscheduled
            # (bench is his correct place; the old code emitted a
            # spurious "no legal bench/IR slot" eligibility_jam for
            # Brooks / Hachimura / Reid / Mobley / Boozer on
            # 2026-10-20..23 even when every scheduled player started)
            # or a scheduled sitter, who already carries his
            # slot_overflow / eligibility_jam conflict from above.
            target[pid] = BENCH_SLOT

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


def _verify(client, account: dict, plan: dict, skipped_ids=frozenset()) -> list:
    """Re-read the roster FOR THE PLAN'S PERIOD and diff actual slots.

    Returns a list of verify_mismatch conflict records (empty = the
    lineup on ESPN matches the plan exactly). Players in
    ``skipped_ids`` (locked players whose moves were excluded) are
    expected to still be in their ORIGINAL slot — they were never
    submitted, so their plan target is not a mismatch.
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
        expected = (
            entry["from_slot"] if pid in skipped_ids else entry["to_slot"]
        )
        if actual.get(pid) != expected:
            mismatches.append(
                {
                    "kind": "verify_mismatch",
                    "scoring_period_id": plan.get("scoring_period_id"),
                    "player_id": pid,
                    "player_name": entry.get("name"),
                    "reason": "lineup on ESPN does not match the submitted plan",
                    "detail": {
                        "expected_slot": expected,
                        "actual_slot": actual.get(pid),
                    },
                }
            )
    return mismatches


def _locked_players(team, payload, base, period, schedule_info, now):
    """(locked player ids, {player_id: tip-off}) for one run.

    A player is locked when his pro team's game for the target period
    has already tipped (tip-off <= now): ESPN freezes him at tip-off
    and rejects any transaction that tries to move him. Tip-off
    sources, in order: the period's pro-games block (the scoped
    payload, then the base payload), then the scoreboard tip-offs the
    fallback path recorded in ``schedule_info``. With no source at
    all, nobody is known to be locked and the 409 retry net in
    :func:`_submit_lineup` is the only guard.
    """
    tipoffs = pro_team_tipoffs(payload, period)
    if tipoffs is None:
        tipoffs = pro_team_tipoffs(base, period)
    if tipoffs is None and schedule_info:
        tipoffs = {}
        for key, value in (schedule_info.get("team_tipoffs") or {}).items():
            try:
                tipoffs[int(key)] = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                continue
    if not tipoffs:
        return set(), {}
    locked_teams = {
        team_id for team_id, moment in tipoffs.items() if moment <= now
    }
    if not locked_teams:
        return set(), {}
    locked = set()
    per_player = {}
    for p in _parse_roster(team):
        if p["pro_team_id"] in locked_teams:
            locked.add(p["player_id"])
            per_player[p["player_id"]] = tipoffs[p["pro_team_id"]]
    return locked, per_player


def _locked_skip(plan_entry: dict, source: str, tipoff) -> dict:
    """One locked-move exclusion record (plan["locked_skips"]).

    Deliberately NOT a conflict: the player is not sitting on value
    or eligibility — ESPN froze him when his game tipped, and
    conflicts count only scheduled players who actually sit.
    """
    return {
        "kind": "player_locked",
        "player_id": plan_entry["player_id"],
        "player_name": plan_entry.get("name"),
        "reason": "player_locked: his game has already started, so "
        "ESPN no longer allows moving him",
        "detail": {
            "from_slot": plan_entry["from_slot"],
            "to_slot": plan_entry["to_slot"],
            "tipoff": tipoff.isoformat() if tipoff is not None else None,
            "source": source,
        },
    }


def _submit_lineup(client, account, team_id, period, items, plan_by_id):
    """Submit LINEUP moves, shedding locked players on a 409.

    Returns (response, submitted_items, extra_skips). ESPN validates
    a transaction atomically and a player can lock between planning
    and submitting, so a 409 naming a locked player ("<name> is
    locked") drops only that player's moves and retries the rest —
    each retry removes at least one player's moves, so there is at
    most one retry per rostered player. Any other failure (auth
    included) propagates to the run's normal error handling. When
    every move is shed, returns (None, [], skips): nothing was
    written, and that is not an error.
    """
    remaining = list(items)
    extra_skips = []
    while remaining:
        try:
            response = client.post_lineup_transaction(
                member_id=account["swid"],
                team_id=team_id,
                scoring_period_id=period,
                items=remaining,
            )
            return response, remaining, extra_skips
        except EspnAuthError:
            raise
        except EspnError as e:
            if getattr(e, "status", None) != 409:
                raise
            text = str(e)
            culprit = None
            for pid, entry in plan_by_id.items():
                name = entry.get("name")
                if name and f"{name} is locked" in text:
                    culprit = pid
                    break
            if culprit is None or all(
                m["playerId"] != culprit for m in remaining
            ):
                raise
            extra_skips.append(_locked_skip(plan_by_id[culprit], "espn_409", None))
            remaining = [m for m in remaining if m["playerId"] != culprit]
    return None, [], extra_skips


def run_lineup(supabase, account: dict, client, dry_run: bool = False,
               scoring_period_id: int | None = None,
               date: str | None = None, scoreboard=None,
               now: datetime | None = None) -> dict:
    """Plan (and, unless dry_run, submit + verify) one day's lineup.

    The target day comes from ``scoring_period_id``, or ``date``
    (YYYY-MM-DD) resolved against the league's scoring periods, or —
    with neither — the league's current scoring period (one code path
    serves every trigger: endpoint, MCP tool, batch entrypoint).
    ``scoreboard`` (an espn.scoreboard.ScoreboardClient) is consulted
    only when the league payload carries no proGamesByScoringPeriod
    block; without it the no-block case keeps its legacy clean error.

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
        target_date = None
        if date is not None:
            try:
                target_date = _date.fromisoformat(date)
            except (TypeError, ValueError):
                raise ValueError(f"date must be YYYY-MM-DD, got {date!r}")
        has_block = isinstance(base.get("proGamesByScoringPeriod"), dict)
        period = None
        payload = None
        playing = None
        schedule_info = None
        if scoring_period_id is not None:
            period = int(scoring_period_id)
        elif target_date is not None:
            if has_block:
                period = resolve_scoring_period(base, date=date)
            elif scoreboard is not None:
                # No pro-games block: anchor + calibrate the period
                # against the public scoreboard. This also yields the
                # winning period's scoped payload and playing set,
                # already gate-verified.
                period, payload, playing, schedule_info = (
                    _resolve_period_via_scoreboard(
                        client,
                        base,
                        account["season"],
                        target_date,
                        scoreboard,
                    )
                )
            else:
                # No fallback available: the block-based resolver
                # raises the legacy "no dated pro games" error.
                period = resolve_scoring_period(base, date=date)
        else:
            # No target: the league's current scoring period. When the
            # payload carries no currentScoringPeriod (the in-season
            # reality on opening day 2026-10-20, not just preseason),
            # resolve "today" through the same scoreboard fallback the
            # explicit-date path uses. Before the season starts (today
            # precedes the first regular-season date) the legacy clean
            # error is preserved, so preseason runs stay silent.
            current = (base.get("status") or {}).get("currentScoringPeriod")
            if current is not None:
                period = int(current)
            elif scoreboard is not None:
                target_date = datetime.now(_ET).date()
                start, end = _scoreboard_window(account["season"])
                season_start = scoreboard.first_regular_season_date(
                    start, end
                )
                if season_start is None or target_date < season_start:
                    raise ValueError(
                        "ESPN payload has no currentScoringPeriod; cannot "
                        "tell which day to set the lineup for"
                    )
                period, payload, playing, schedule_info = (
                    _resolve_period_via_scoreboard(
                        client,
                        base,
                        account["season"],
                        target_date,
                        scoreboard,
                    )
                )
            elif has_block:
                target_date = datetime.now(_ET).date()
                period = resolve_scoring_period(
                    base, date=target_date.isoformat()
                )
            else:
                period = resolve_scoring_period(base)
        run["scoring_period_id"] = period
        current = (base.get("status") or {}).get("currentScoringPeriod")
        if payload is None:
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
        if playing is None:
            playing = pro_teams_playing(payload, period)
            if playing is None:
                playing = pro_teams_playing(base, period)
            if playing is not None:
                schedule_info = {
                    "source": "pro_games_block",
                    "target_date": (
                        target_date.isoformat() if target_date else None
                    ),
                }
            elif scoreboard is not None:
                playing, schedule_info = _scoreboard_fallback_playing(
                    payload,
                    base,
                    account["season"],
                    period,
                    target_date,
                    scoreboard,
                    client=client,
                )
            else:
                raise ValueError(
                    "ESPN payload has no proGamesByScoringPeriod schedule "
                    "block; refusing to guess who is scheduled"
                )
        plan = plan_lineup(team, payload, period, playing)
        plan["requested"] = {"date": date, "scoring_period_id": scoring_period_id}
        plan["schedule"] = schedule_info
        run["plan"] = plan
        run["moves"] = plan["moves"]
        run["conflicts"] = list(plan["conflicts"])

        # Per-player locks (see module docstring): moves for players
        # whose game has already tipped are excluded from the
        # submission and recorded in plan["locked_skips"] — never a
        # conflict, never a run failure. Computed for dry runs too,
        # as part of the preview; only a live run acts on it.
        moment = now if now is not None else datetime.now(timezone.utc)
        locked_ids, tipoffs = _locked_players(
            team, payload, base, period, schedule_info, moment
        )
        plan_by_id = {p["player_id"]: p for p in plan["players"]}
        skips = [
            _locked_skip(
                plan_by_id[m["playerId"]], "schedule", tipoffs.get(m["playerId"])
            )
            for m in plan["moves"]
            if m["playerId"] in locked_ids
        ]
        plan["locked_skips"] = skips

        if dry_run:
            run["status"] = "dry_run"
            return record_run(supabase, run)

        if plan["moves"]:
            to_submit = [
                m for m in plan["moves"] if m["playerId"] not in locked_ids
            ]
            response = None
            submitted: list = []
            if to_submit:
                response, submitted, retry_skips = _submit_lineup(
                    client,
                    account,
                    team.get("id"),
                    period,
                    to_submit,
                    plan_by_id,
                )
                if retry_skips:
                    skips = skips + retry_skips
                    plan["locked_skips"] = skips
            run["moves"] = submitted
            if response is not None:
                txn_status = (
                    response.get("status")
                    if isinstance(response, dict)
                    else None
                )
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
            skipped_ids = {s["player_id"] for s in skips}
            mismatches = _verify(client, account, plan, skipped_ids)
            run["conflicts"].extend(mismatches)

        kinds = {c["kind"] for c in run["conflicts"]}
        if "verify_mismatch" in kinds:
            run["status"] = "verify_mismatch"
        elif run["conflicts"]:
            run["status"] = "conflict"
        elif run["moves"]:
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
