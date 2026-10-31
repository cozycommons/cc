"""Approval-gated roster edits (add / drop) for one ESPN account.

Roster edits are the ESPN module's second write, and they are gated
harder than the first: lineup moves run automatically under the user's
standing instructions, but an add/drop changes who is ON the roster, so
every edit goes through an explicit two-step gate (the propose ->
approve shape Resy's booking gate established for this codebase,
enforced server-side here):

  1. ``propose_edit`` validates the edit against the LIVE league —
     the add target is currently a free agent in this league's pool
     (the league-scoped kona fetch the waiver report uses), the drop
     target is on the account's own roster, and the post-edit roster
     is legal under the league's slot counts, IR accounting included —
     then persists the validated snapshot as a ``pending`` edit with
     a 30-minute expiry (table ``espn_roster_edits``, migration 0014).
     NOTHING is submitted to ESPN at propose time.

  2. ``approve_edit`` executes a pending, unexpired edit as ONE ESPN
     transaction containing both moves. The edit is claimed atomically
     (pending -> executing) before anything is submitted, so approving
     twice — or two approvals racing — can never double-submit. The
     outcome is recorded back on the row: ``executed``,
     ``waiver_pending`` (ESPN parked the add as a waiver claim; bid 0,
     no FAAB support), or ``failed`` with ESPN's error. League state
     is re-validated at approve time: an edit whose add target got
     rostered (or whose drop target left the roster) since proposal
     fails closed instead of submitting.

Tenant isolation is the module-wide rule: every read and write is
scoped by ``account_id``, and the account comes from the caller's
bearer token — an edit id from another account simply does not exist
here. Basketball only, one league per account. Trades are a separate
gate with the same shape, in espn/trades.py.

Nothing in this module is wired into the scheduler or the lineup
automation: edits happen only when a human proposes and then approves
one. The daily waiver digest stays recommendations-only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import lineup, waivers
from .espn_client import EspnAuthError, EspnError

EDIT_TTL_MINUTES = 30

STATUS_PENDING = "pending"
STATUS_EXECUTING = "executing"
STATUS_EXECUTED = "executed"
STATUS_WAIVER_PENDING = "waiver_pending"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"

_EDIT_COLUMNS = (
    "id,league_id,season,team_id,add_player_id,drop_player_id,"
    "add_player,drop_player,preview,status,error,espn_transaction,"
    "expires_at,executed_at,created_at"
)

# kona pool entry / player ``status`` values that mean the player is
# sitting on waivers (a claim processes later) rather than a true free
# agent (an add executes immediately). Anything else — including the
# field being absent, which the live pool often does — is "unknown".
_WAIVER_STATUSES = {"WAIVERS", "ON_WAIVERS"}
_FREE_AGENT_STATUSES = {"FREEAGENT", "FREE_AGENT"}


class EditError(ValueError):
    """The proposed edit is invalid (routes map this to 400)."""


class EditNotFound(Exception):
    """No edit with that id exists for this account (routes: 404)."""


class EditStateError(Exception):
    """The edit exists but cannot be approved in its state (routes: 409)."""


# --- helpers -------------------------------------------------------------------


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _coerce_player_id(value, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise EditError(f"{field} must be a positive integer player id")
    if isinstance(value, int):
        pid = value
    elif isinstance(value, str) and value.strip().isdigit():
        pid = int(value.strip())
    else:
        raise EditError(f"{field} must be a positive integer player id")
    if pid <= 0:
        raise EditError(f"{field} must be a positive integer player id")
    return pid


def _waiver_flag(entry: dict, player: dict):
    """True / False / None: is this pool player on waivers?

    Reads the ``status`` the kona entry (or its player object) carries;
    None when the payload doesn't say, which is common — the approve
    step's outcome classification does not depend on this flag being
    known, it only picks the transaction type up front.
    """
    raw = entry.get("status")
    if not isinstance(raw, str):
        raw = player.get("status")
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().upper()
    if normalized in _WAIVER_STATUSES:
        return True
    if normalized in _FREE_AGENT_STATUSES:
        return False
    return None


def _snapshot(player: dict, player_id: int, **extra) -> dict:
    snapshot = {
        "player_id": player_id,
        "name": player.get("fullName"),
        "positions": waivers._positions(player),
        "pro_team": waivers.PRO_TEAM_ABBR.get(player.get("proTeamId")),
        "injury_status": player.get("injuryStatus"),
    }
    snapshot.update(extra)
    return snapshot


def _pool_by_id(client) -> dict:
    """{player_id: (entry, player)} from the league-scoped kona pool."""
    pool = {}
    for entry in client.get_league_players(waivers.POOL_LIMIT) or []:
        player = waivers._entry_player(entry)
        pid = waivers._entry_player_id(entry, player)
        if pid is not None:
            pool[pid] = (entry, player)
    return pool


def _rostered_by_id(payload: dict) -> dict:
    """{player_id: team_id} for every player rostered in the league."""
    rostered = {}
    for team in payload.get("teams") or []:
        if not isinstance(team, dict):
            continue
        entries = ((team.get("roster") or {}).get("entries")) or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            player = ((entry.get("playerPoolEntry") or {}).get("player")) or {}
            pid = entry.get("playerId")
            if pid is None and isinstance(player, dict):
                pid = player.get("id")
            if pid is not None:
                rostered[pid] = team.get("id")
    return rostered


def _validate_add(client, payload: dict, add_player_id: int, pool=None) -> dict:
    """Snapshot for a legal add target, or raise EditError."""
    rostered = _rostered_by_id(payload)
    if add_player_id in rostered:
        raise EditError(
            f"player {add_player_id} is already rostered "
            f"(team {rostered[add_player_id]}) in this league"
        )
    if pool is None:
        pool = _pool_by_id(client)
    found = pool.get(add_player_id)
    if found is None:
        raise EditError(
            f"player {add_player_id} is not in this league's player pool"
        )
    entry, player = found
    on_team = entry.get("onTeamId")
    if on_team not in (None, 0):
        raise EditError(
            f"player {add_player_id} is already rostered "
            f"(team {on_team}) in this league"
        )
    return _snapshot(
        player, add_player_id, on_waivers=_waiver_flag(entry, player)
    )


def _validate_roster_size(payload: dict, team: dict, drop_entry,
                          add_player_id) -> None:
    """Post-edit roster legality under the league's slot counts.

    Mirrors the lineup planner's accounting: the IR slot is extra, so
    the ACTIVE roster (everyone not parked on IR) may not exceed the
    total slots minus the IR slots. A swap is size-neutral; an
    add-only edit needs an open active slot; dropping an IR player
    frees no active slot.
    """
    counts = lineup.lineup_slot_counts(payload)
    total_slots = sum(counts.values())
    active_cap = total_slots - counts.get(lineup.IR_SLOT, 0)
    roster = lineup._parse_roster(team)
    active = sum(
        1 for p in roster if p["current_slot"] != lineup.IR_SLOT
    )
    total_after = len(roster)
    active_after = active
    if drop_entry is not None:
        total_after -= 1
        if drop_entry["current_slot"] != lineup.IR_SLOT:
            active_after -= 1
    if add_player_id is not None:
        total_after += 1
        active_after += 1
    if total_after > total_slots or active_after > active_cap:
        raise EditError(
            "roster would exceed the league maximum after this edit "
            f"({active_after} active players, maximum {active_cap}); "
            "drop a player as part of the edit"
        )


def _preview(add_snapshot, drop_snapshot, team_id: int) -> str:
    def describe(snap) -> str:
        positions = "/".join(snap.get("positions") or [])
        bits = [snap.get("name") or f"player {snap.get('player_id')}"]
        detail = ", ".join(
            b for b in (positions, snap.get("pro_team")) if b
        )
        if detail:
            bits.append(f"({detail})")
        return " ".join(bits)

    parts = []
    if add_snapshot is not None:
        parts.append(f"Add {describe(add_snapshot)}")
    if drop_snapshot is not None:
        parts.append(f"drop {describe(drop_snapshot)}")
    text = " and ".join(parts) + f" — team {team_id}"
    if add_snapshot is not None and add_snapshot.get("on_waivers"):
        text += (
            "; the add target is on waivers, so approving files a "
            "waiver claim (bid 0) instead of an immediate add"
        )
    return text


def _current_period(client, payload: dict, scoreboard) -> int:
    """The league's current scoring period (the lineup runner's anchors).

    status.currentScoringPeriod first, then the pro-games date map,
    then the public-scoreboard anchor the waiver report uses.
    """
    status = payload.get("status") or {}
    current = status.get("currentScoringPeriod")
    if isinstance(current, int):
        return current
    today = datetime.now(lineup._ET).date()
    try:
        return lineup.resolve_scoring_period(payload, date=today.isoformat())
    except ValueError:
        pass
    if scoreboard is not None:
        first = lineup._first_scoring_period(payload)
        start, end = lineup._scoreboard_window(client.season)
        season_start = scoreboard.first_regular_season_date(start, end)
        if season_start is not None:
            derived = first + (today - season_start).days
            if derived >= first:
                return derived
    raise ValueError(
        "league payload has no current scoring period and none could "
        "be derived"
    )


# --- storage ---------------------------------------------------------------------


def _public(row: dict) -> dict:
    return {k: row.get(k) for k in _EDIT_COLUMNS.split(",")}


def _insert_edit(supabase, row: dict) -> dict:
    res = supabase.table("espn_roster_edits").insert(row).execute()
    stored = (res.data or [{}])[0] if res.data else {}
    return _public({**row, **stored})


def _update_edit(supabase, edit_id, fields: dict) -> dict:
    res = (
        supabase.table("espn_roster_edits")
        .update(fields)
        .eq("id", edit_id)
        .execute()
    )
    stored = (res.data or [{}])[0] if res.data else {}
    return stored


def get_edit(supabase, account_id, edit_id) -> dict | None:
    """One edit belonging to this account (and only this account)."""
    res = (
        supabase.table("espn_roster_edits")
        .select(_EDIT_COLUMNS)
        .eq("account_id", account_id)
        .eq("id", edit_id)
        .execute()
    )
    rows = res.data or []
    return _public(rows[0]) if rows else None


def list_edits(supabase, account_id, limit: int = 25,
               status: str | None = None) -> dict:
    """Newest roster edits for one account (and only that account)."""
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    query = (
        supabase.table("espn_roster_edits")
        .select(_EDIT_COLUMNS)
        .eq("account_id", account_id)
    )
    if status is not None:
        query = query.eq("status", status)
    res = query.order("created_at", desc=True).limit(limit).execute()
    edits = [_public(row) for row in (res.data or [])]
    return {"edits": edits, "count": len(edits)}


def _claim_edit(supabase, edit_id) -> bool:
    """Atomically move pending -> executing; False when already claimed."""
    res = (
        supabase.table("espn_roster_edits")
        .update({"status": STATUS_EXECUTING})
        .eq("id", edit_id)
        .eq("status", STATUS_PENDING)
        .execute()
    )
    return bool(res.data)


# --- propose ---------------------------------------------------------------------


def propose_edit(supabase, account: dict, client,
                 add_player_id=None, drop_player_id=None,
                 now: datetime | None = None) -> dict:
    """Validate a roster edit and persist it as a pending edit.

    Validates against the live league and stores the snapshot; submits
    NOTHING to ESPN. Returns the stored edit (status ``pending``),
    including its id, the human preview, and its expiry. Raises
    EditError for an invalid edit, EspnAuthError / EspnError from the
    wire, and ValueError when the account's team cannot be resolved.
    """
    if add_player_id is None and drop_player_id is None:
        raise EditError(
            "pass add_player_id and/or drop_player_id "
            "(a swap is both; add-only and drop-only are allowed)"
        )
    add_id = (
        _coerce_player_id(add_player_id, "add_player_id")
        if add_player_id is not None
        else None
    )
    drop_id = (
        _coerce_player_id(drop_player_id, "drop_player_id")
        if drop_player_id is not None
        else None
    )
    if add_id is not None and add_id == drop_id:
        raise EditError("add_player_id and drop_player_id are the same player")

    payload = client.get_league(["mSettings", "mTeam", "mRoster"]) or {}
    team = lineup.find_member_team(payload, account["swid"])
    team_id = team.get("id")
    roster = {p["player_id"]: p for p in lineup._parse_roster(team)}

    add_snapshot = None
    if add_id is not None:
        add_snapshot = _validate_add(client, payload, add_id)
    drop_snapshot = None
    drop_entry = None
    if drop_id is not None:
        drop_entry = roster.get(drop_id)
        if drop_entry is None:
            raise EditError(
                f"player {drop_id} is not on your roster "
                f"(team {team_id}); only your own players can be dropped"
            )
        drop_snapshot = _snapshot(
            drop_entry["player"],
            drop_id,
            lineup_slot_id=drop_entry["current_slot"],
        )
    _validate_roster_size(payload, team, drop_entry, add_id)

    now = now or datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=EDIT_TTL_MINUTES)
    row = {
        "account_id": account["id"],
        "league_id": account.get("league_id"),
        "season": account.get("season"),
        "team_id": team_id,
        "add_player_id": add_id,
        "drop_player_id": drop_id,
        "add_player": add_snapshot,
        "drop_player": drop_snapshot,
        "preview": _preview(add_snapshot, drop_snapshot, team_id),
        "status": STATUS_PENDING,
        "error": None,
        "espn_transaction": None,
        "expires_at": expires_at.isoformat(),
        "executed_at": None,
    }
    return _insert_edit(supabase, row)


# --- approve / execute -----------------------------------------------------------


def _classify_outcome(response: dict, add_snapshot) -> tuple:
    """(status, error) from ESPN's transaction response.

    Keyed off the transaction's own ``type``/``status``, not the
    propose-time snapshot alone: a WAIVER transaction is a claim and
    stays pending until waivers process, whatever its status echo,
    and an explicitly pending/processing status is a claim parked
    with ESPN. A FREEAGENT transaction ESPN reports EXECUTED has
    executed — possibly effective from the next scoring period, but
    executed; it is never a waiver claim.
    """
    raw_status = str(response.get("status") or "").upper()
    if raw_status.startswith("FAILED") or response.get("error"):
        detail = response.get("error") or raw_status
        return STATUS_FAILED, f"ESPN rejected the transaction: {detail}"
    raw_type = str(response.get("type") or "").upper()
    if (
        raw_type == "WAIVER"
        or raw_status.startswith("PENDING")
        or raw_status == "PROCESSING"
    ):
        return STATUS_WAIVER_PENDING, None
    if raw_status == "EXECUTED":
        return STATUS_EXECUTED, None
    if add_snapshot is not None and add_snapshot.get("on_waivers"):
        # A waiver claim ESPN accepted without a status echo is still
        # a claim: it cannot have executed immediately.
        return STATUS_WAIVER_PENDING, None
    return STATUS_EXECUTED, None


def approve_edit(supabase, account: dict, client, edit_id,
                 scoreboard=None, now: datetime | None = None) -> dict:
    """Execute one pending edit as a single ESPN transaction.

    The edit must belong to the caller's account, still be ``pending``
    and be unexpired; anything else raises EditNotFound (404) or
    EditStateError (409) BEFORE anything is submitted, and the atomic
    claim means a second approval can never double-submit. ESPN
    submission failures are recorded on the edit (status ``failed``)
    and returned, not raised — the same philosophy as lineup runs —
    except auth failures, which propagate as EspnAuthError after being
    recorded (the user must re-onboard; a fresh proposal follows).
    """
    now = now or datetime.now(timezone.utc)
    edit = get_edit(supabase, account["id"], edit_id)
    if edit is None:
        raise EditNotFound("no roster edit with that id for this account")
    if edit["status"] != STATUS_PENDING:
        raise EditStateError(
            f"edit is {edit['status']}, not pending; "
            "only a pending edit can be approved"
        )
    expires = _parse_dt(edit.get("expires_at"))
    if expires is not None and now >= expires:
        _update_edit(supabase, edit["id"], {"status": STATUS_EXPIRED})
        raise EditStateError(
            "edit has expired; propose it again to re-validate it"
        )
    if not _claim_edit(supabase, edit["id"]):
        raise EditStateError("edit is already being executed")

    try:
        return _execute(supabase, account, client, edit, scoreboard, now)
    except EspnAuthError as e:
        _update_edit(
            supabase,
            edit["id"],
            {"status": STATUS_FAILED, "error": str(e)},
        )
        raise
    except EspnError as e:
        _update_edit(
            supabase,
            edit["id"],
            {"status": STATUS_FAILED, "error": str(e)},
        )
        raise
    except ValueError as e:
        # Payload-shape failures while re-reading the league (the
        # account's team vanished, no current period could be derived):
        # record the claimed edit as failed rather than stranding it,
        # then let the route map it to a 400 like other payload errors.
        _update_edit(
            supabase,
            edit["id"],
            {"status": STATUS_FAILED, "error": str(e)},
        )
        raise


def _execute(supabase, account: dict, client, edit: dict, scoreboard,
             now: datetime) -> dict:
    edit_id = edit["id"]
    # Re-validate against the live league: the world may have moved
    # since proposal, and a stale edit must fail closed, not submit.
    payload = client.get_league(["mSettings", "mTeam", "mRoster"]) or {}
    team = lineup.find_member_team(payload, account["swid"])
    if team.get("id") != edit["team_id"]:
        _update_edit(
            supabase,
            edit_id,
            {
                "status": STATUS_FAILED,
                "error": "the account's team changed since proposal",
            },
        )
        raise EditStateError("the account's team changed since proposal")
    roster = {p["player_id"]: p for p in lineup._parse_roster(team)}
    add_snapshot = edit.get("add_player")
    try:
        if edit.get("add_player_id") is not None:
            fresh = _validate_add(client, payload, edit["add_player_id"])
            if fresh.get("on_waivers") is not None:
                add_snapshot = fresh
        if (
            edit.get("drop_player_id") is not None
            and edit["drop_player_id"] not in roster
        ):
            raise EditError(
                f"player {edit['drop_player_id']} is no longer on your "
                "roster"
            )
    except EditError as e:
        _update_edit(
            supabase,
            edit_id,
            {
                "status": STATUS_FAILED,
                "error": f"no longer valid at approval time: {e}",
            },
        )
        raise EditStateError(
            f"edit is no longer valid at approval time: {e}"
        ) from e

    period = _current_period(client, payload, scoreboard)
    moves = []
    if edit.get("add_player_id") is not None:
        moves.append({"action": "ADD", "playerId": edit["add_player_id"]})
    if edit.get("drop_player_id") is not None:
        moves.append({"action": "DROP", "playerId": edit["drop_player_id"]})
    on_waivers = bool(add_snapshot and add_snapshot.get("on_waivers"))
    try:
        response = client.post_roster_transaction(
            member_id=account["swid"],
            team_id=edit["team_id"],
            scoring_period_id=period,
            moves=moves,
            on_waivers=on_waivers,
        )
    except EspnError as e:
        # EspnAuthError subclasses EspnError: let it propagate to
        # approve_edit's auth handling; a plain failure is recorded
        # and returned as the failed edit.
        if isinstance(e, EspnAuthError):
            raise
        stored = _update_edit(
            supabase,
            edit_id,
            {"status": STATUS_FAILED, "error": str(e)},
        )
        return _public({**edit, **stored, "status": STATUS_FAILED,
                        "error": str(e)})

    status, error = _classify_outcome(response, add_snapshot)
    if (
        status == STATUS_EXECUTED
        and on_waivers
        and edit.get("add_player_id") is not None
    ):
        # Verify a waiver claim ESPN echoed as EXECUTED actually
        # landed on the roster (the lineup runner's verify
        # philosophy); a contradiction means the claim was parked
        # after all. A straight free-agent edit is NOT verified this
        # way: ESPN applies a FREEAGENT move submitted after the
        # day's games lock from the next scoring period, so the add
        # legitimately is not on the current-period roster yet and
        # absence proves nothing (2026-10-30 incident, edit
        # baefb882: FREEAGENT/EXECUTED, effective the next period,
        # misrecorded as waiver_pending by this check).
        try:
            after = client.get_league(["mTeam", "mRoster"]) or {}
            after_team = lineup.find_member_team(after, account["swid"])
            after_ids = {
                p["player_id"] for p in lineup._parse_roster(after_team)
            }
            if edit["add_player_id"] not in after_ids:
                status = STATUS_WAIVER_PENDING
        except EspnError:
            pass  # Verification is best-effort; ESPN's status stands.

    fields = {
        "status": status,
        "error": error,
        "espn_transaction": response,
    }
    if status in (STATUS_EXECUTED, STATUS_WAIVER_PENDING):
        fields["executed_at"] = now.isoformat()
    stored = _update_edit(supabase, edit_id, fields)
    return _public({**edit, **stored, **fields})
