"""Approval-gated trade proposals for one ESPN account.

Trades are the ESPN module's third write, and they inherit the
add/drop gate in espn/roster_edits.py wholesale (the propose ->
approve shape Resy's booking gate established for this codebase),
because approving a trade is if anything more consequential than
approving an add/drop: approval SUBMITS a real offer the
counterparty sees, and if they accept it the rosters change for
both teams. The gate:

  1. ``propose_trade`` validates the offer against the LIVE league —
     the counterparty exists and is not the caller's own team, every
     give player is on the caller's roster, every receive player is
     on the counterparty's roster, the post-trade roster is legal
     for BOTH teams under the league's slot counts (IR accounting
     included, so 2-for-1 and 1-for-2 offers change size on both
     sides), and the league's trade deadline has not passed — then
     persists the validated snapshot as a ``pending`` proposal with
     a 30-minute expiry (table ``espn_trade_proposals``, migration
     0015). NOTHING is submitted to ESPN at propose time.

  2. ``approve_trade`` executes a pending, unexpired proposal as ONE
     ESPN ``TRADE`` transaction. The proposal is claimed atomically
     (pending -> executing) before anything is submitted, so
     approving twice — or two approvals racing — can never
     double-submit. League state is re-validated at approve time:
     a proposal whose players have moved or whose deadline has
     passed since proposal fails closed instead of submitting. The
     recorded outcome is ``offered`` (ESPN accepted the submission;
     the counterparty's accept/decline happens on ESPN and is not
     tracked here) or ``failed`` with ESPN's error.

Tenant isolation is the module-wide rule: every read and write is
scoped by ``account_id``, and the account comes from the caller's
bearer token — a proposal id from another account simply does not
exist here. Basketball only, one league per account.

Nothing in this module is wired into the scheduler, the lineup
automation, or the waiver digest: a trade exists only when a human
proposes one and then approves that exact offer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import lineup, roster_edits
from .espn_client import EspnAuthError, EspnError

PROPOSAL_TTL_MINUTES = 30

STATUS_PENDING = "pending"
STATUS_EXECUTING = "executing"
STATUS_OFFERED = "offered"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"

_PROPOSAL_COLUMNS = (
    "id,league_id,season,team_id,counterparty_team_id,"
    "give_player_ids,receive_player_ids,give_players,receive_players,"
    "preview,status,error,espn_transaction,espn_transaction_id,"
    "expires_at,executed_at,created_at"
)


class TradeError(ValueError):
    """The proposed trade is invalid (routes map this to 400)."""


class TradeNotFound(Exception):
    """No proposal with that id exists for this account (routes: 404)."""


class TradeStateError(Exception):
    """The proposal exists but cannot be approved now (routes: 409)."""


# --- helpers -------------------------------------------------------------------


def _team_by_id(payload: dict, team_id) -> dict | None:
    for team in payload.get("teams") or []:
        if isinstance(team, dict) and team.get("id") == team_id:
            return team
    return None


def _coerce_team_id(value) -> int:
    if isinstance(value, bool) or value is None:
        raise TradeError("counterparty_team_id must be a positive integer")
    if isinstance(value, int):
        team_id = value
    elif isinstance(value, str) and value.strip().isdigit():
        team_id = int(value.strip())
    else:
        raise TradeError("counterparty_team_id must be a positive integer")
    if team_id <= 0:
        raise TradeError("counterparty_team_id must be a positive integer")
    return team_id


def _coerce_player_ids(values, field: str) -> list:
    if not isinstance(values, (list, tuple)) or not values:
        raise TradeError(f"{field} must be a non-empty list of player ids")
    try:
        ids = [roster_edits._coerce_player_id(v, field) for v in values]
    except roster_edits.EditError as e:
        raise TradeError(str(e)) from e
    if len(set(ids)) != len(ids):
        raise TradeError(f"{field} contains the same player twice")
    return ids


def _trade_deadline(payload: dict) -> datetime | None:
    """The league's trade deadline (epoch ms in tradeSettings), if set."""
    settings = payload.get("settings") or {}
    raw = (settings.get("tradeSettings") or {}).get("deadlineDate")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return datetime.fromtimestamp(raw / 1000, tz=timezone.utc)


def _check_deadline(payload: dict, now: datetime) -> None:
    deadline = _trade_deadline(payload)
    if deadline is not None and now >= deadline:
        raise TradeError(
            "the league trade deadline has passed "
            f"({deadline.date().isoformat()}); trades are closed"
        )


def _validate_roster_after(payload: dict, team: dict, out_entries: list,
                           in_count: int, who: str) -> None:
    """Post-trade roster legality for ONE side, roster-edits accounting.

    Mirrors roster_edits._validate_roster_size: the IR slot is extra,
    so the ACTIVE roster (everyone not parked on IR) may not exceed
    the total slots minus the IR slots. Outgoing players free the
    slot they actually sit in (an outgoing IR player frees no active
    slot); incoming players always count as active — where ESPN
    parks a received player is its acceptance-time decision, and the
    active reading is the conservative one.
    """
    counts = lineup.lineup_slot_counts(payload)
    total_slots = sum(counts.values())
    active_cap = total_slots - counts.get(lineup.IR_SLOT, 0)
    roster = lineup._parse_roster(team)
    total_after = len(roster) - len(out_entries) + in_count
    active_after = (
        sum(1 for p in roster if p["current_slot"] != lineup.IR_SLOT)
        - sum(1 for e in out_entries if e["current_slot"] != lineup.IR_SLOT)
        + in_count
    )
    if total_after > total_slots or active_after > active_cap:
        raise TradeError(
            f"{who} roster would exceed the league maximum after this "
            f"trade ({active_after} active players, maximum "
            f"{active_cap}); even out the swap"
        )


def _validate(payload: dict, own_team: dict, counterparty_team: dict,
              give_ids: list, receive_ids: list,
              now: datetime) -> tuple:
    """Full offer validation; returns (give_entries, receive_entries).

    Shared by propose and approve — at approve time the same checks
    running against a moved league are what make a stale proposal
    fail closed.
    """
    own_id = own_team.get("id")
    cp_id = counterparty_team.get("id")
    if cp_id == own_id:
        raise TradeError("cannot trade with your own team")
    overlap = sorted(set(give_ids) & set(receive_ids))
    if overlap:
        raise TradeError(
            f"player(s) {overlap} cannot be both given and received"
        )
    own_roster = {p["player_id"]: p
                  for p in lineup._parse_roster(own_team)}
    cp_roster = {p["player_id"]: p
                 for p in lineup._parse_roster(counterparty_team)}
    give_entries = []
    for pid in give_ids:
        entry = own_roster.get(pid)
        if entry is None:
            raise TradeError(
                f"player {pid} is not on your roster (team {own_id}); "
                "only your own players can be offered"
            )
        give_entries.append(entry)
    receive_entries = []
    for pid in receive_ids:
        entry = cp_roster.get(pid)
        if entry is None:
            raise TradeError(
                f"player {pid} is not on team {cp_id}'s roster; "
                "only the counterparty's players can be requested"
            )
        receive_entries.append(entry)
    _validate_roster_after(
        payload, own_team, give_entries, len(receive_ids), "your"
    )
    _validate_roster_after(
        payload, counterparty_team, receive_entries, len(give_ids),
        f"team {cp_id}'s",
    )
    _check_deadline(payload, now)
    return give_entries, receive_entries


def _snapshots(entries: list, team_id: int) -> list:
    return [
        roster_edits._snapshot(
            entry["player"],
            entry["player_id"],
            lineup_slot_id=entry["current_slot"],
            team_id=team_id,
        )
        for entry in entries
    ]


def _preview(counterparty_team: dict, give_snapshots: list,
             receive_snapshots: list, team_id: int) -> str:
    def describe(snap) -> str:
        positions = "/".join(snap.get("positions") or [])
        bits = [snap.get("name") or f"player {snap.get('player_id')}"]
        detail = ", ".join(
            b for b in (positions, snap.get("pro_team")) if b
        )
        if detail:
            bits.append(f"({detail})")
        return " ".join(bits)

    cp_id = counterparty_team.get("id")
    cp_name = counterparty_team.get("name")
    target = f"{cp_name} (team {cp_id})" if cp_name else f"team {cp_id}"
    give = ", ".join(describe(s) for s in give_snapshots)
    receive = ", ".join(describe(s) for s in receive_snapshots)
    text = f"Offer to {target}: give {give}; receive {receive}"
    text += (
        f" — team {team_id} gives {len(give_snapshots)}, "
        f"receives {len(receive_snapshots)}"
    )
    text += (
        "; approving submits this offer to ESPN for the counterparty "
        "to accept or decline"
    )
    return text


# --- storage ---------------------------------------------------------------------


def _public(row: dict) -> dict:
    return {k: row.get(k) for k in _PROPOSAL_COLUMNS.split(",")}


def _insert_proposal(supabase, row: dict) -> dict:
    res = supabase.table("espn_trade_proposals").insert(row).execute()
    stored = (res.data or [{}])[0] if res.data else {}
    return _public({**row, **stored})


def _update_proposal(supabase, proposal_id, fields: dict) -> dict:
    res = (
        supabase.table("espn_trade_proposals")
        .update(fields)
        .eq("id", proposal_id)
        .execute()
    )
    stored = (res.data or [{}])[0] if res.data else {}
    return stored


def get_proposal(supabase, account_id, proposal_id) -> dict | None:
    """One proposal belonging to this account (and only this account)."""
    res = (
        supabase.table("espn_trade_proposals")
        .select(_PROPOSAL_COLUMNS)
        .eq("account_id", account_id)
        .eq("id", proposal_id)
        .execute()
    )
    rows = res.data or []
    return _public(rows[0]) if rows else None


def list_proposals(supabase, account_id, limit: int = 25,
                   status: str | None = None) -> dict:
    """Newest trade proposals for one account (and only that account)."""
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    query = (
        supabase.table("espn_trade_proposals")
        .select(_PROPOSAL_COLUMNS)
        .eq("account_id", account_id)
    )
    if status is not None:
        query = query.eq("status", status)
    res = query.order("created_at", desc=True).limit(limit).execute()
    proposals = [_public(row) for row in (res.data or [])]
    return {"proposals": proposals, "count": len(proposals)}


def _claim_proposal(supabase, proposal_id) -> bool:
    """Atomically move pending -> executing; False when already claimed."""
    res = (
        supabase.table("espn_trade_proposals")
        .update({"status": STATUS_EXECUTING})
        .eq("id", proposal_id)
        .eq("status", STATUS_PENDING)
        .execute()
    )
    return bool(res.data)


# --- propose ---------------------------------------------------------------------


def propose_trade(supabase, account: dict, client,
                  counterparty_team_id=None, give_player_ids=None,
                  receive_player_ids=None,
                  now: datetime | None = None) -> dict:
    """Validate a trade offer and persist it as a pending proposal.

    Validates against the live league and stores the snapshot of both
    sides; submits NOTHING to ESPN — approving is what sends the
    offer. Returns the stored proposal (status ``pending``), including
    its id, the human preview, and its expiry. Raises TradeError for
    an invalid offer, EspnAuthError / EspnError from the wire, and
    ValueError when the account's team cannot be resolved.
    """
    cp_id = _coerce_team_id(counterparty_team_id)
    give_ids = _coerce_player_ids(give_player_ids, "give_player_ids")
    receive_ids = _coerce_player_ids(
        receive_player_ids, "receive_player_ids"
    )
    now = now or datetime.now(timezone.utc)

    payload = client.get_league(["mSettings", "mTeam", "mRoster"]) or {}
    own_team = lineup.find_member_team(payload, account["swid"])
    team_id = own_team.get("id")
    if cp_id == team_id:
        raise TradeError("cannot trade with your own team")
    counterparty_team = _team_by_id(payload, cp_id)
    if counterparty_team is None:
        raise TradeError(f"team {cp_id} is not in this league")
    give_entries, receive_entries = _validate(
        payload, own_team, counterparty_team, give_ids, receive_ids, now
    )
    give_snapshots = _snapshots(give_entries, team_id)
    receive_snapshots = _snapshots(receive_entries, cp_id)

    expires_at = now + timedelta(minutes=PROPOSAL_TTL_MINUTES)
    row = {
        "account_id": account["id"],
        "league_id": account.get("league_id"),
        "season": account.get("season"),
        "team_id": team_id,
        "counterparty_team_id": cp_id,
        "give_player_ids": give_ids,
        "receive_player_ids": receive_ids,
        "give_players": give_snapshots,
        "receive_players": receive_snapshots,
        "preview": _preview(
            counterparty_team, give_snapshots, receive_snapshots, team_id
        ),
        "status": STATUS_PENDING,
        "error": None,
        "espn_transaction": None,
        "espn_transaction_id": None,
        "expires_at": expires_at.isoformat(),
        "executed_at": None,
    }
    return _insert_proposal(supabase, row)


# --- approve / execute -----------------------------------------------------------


def _classify_outcome(response: dict) -> tuple:
    """(status, error) from ESPN's transaction response.

    A trade submission that ESPN accepts is an OFFER — it stays open
    until the counterparty accepts or declines on ESPN — so anything
    that is not an explicit rejection classifies as ``offered``.
    """
    raw_status = str(response.get("status") or "").upper()
    if raw_status.startswith("FAILED") or response.get("error"):
        detail = response.get("error") or raw_status
        return STATUS_FAILED, f"ESPN rejected the transaction: {detail}"
    return STATUS_OFFERED, None


def approve_trade(supabase, account: dict, client, proposal_id,
                  scoreboard=None, now: datetime | None = None) -> dict:
    """Submit one pending proposal's offer as a single ESPN transaction.

    The proposal must belong to the caller's account, still be
    ``pending`` and be unexpired; anything else raises TradeNotFound
    (404) or TradeStateError (409) BEFORE anything is submitted, and
    the atomic claim means a second approval can never double-submit.
    ESPN submission failures are recorded on the proposal (status
    ``failed``) and returned, not raised — the same philosophy as
    roster edits — except auth failures, which propagate as
    EspnAuthError after being recorded (the user must re-onboard; a
    fresh proposal follows).
    """
    now = now or datetime.now(timezone.utc)
    proposal = get_proposal(supabase, account["id"], proposal_id)
    if proposal is None:
        raise TradeNotFound(
            "no trade proposal with that id for this account"
        )
    if proposal["status"] != STATUS_PENDING:
        raise TradeStateError(
            f"proposal is {proposal['status']}, not pending; "
            "only a pending proposal can be approved"
        )
    expires = roster_edits._parse_dt(proposal.get("expires_at"))
    if expires is not None and now >= expires:
        _update_proposal(
            supabase, proposal["id"], {"status": STATUS_EXPIRED}
        )
        raise TradeStateError(
            "proposal has expired; propose it again to re-validate it"
        )
    if not _claim_proposal(supabase, proposal["id"]):
        raise TradeStateError("proposal is already being executed")

    try:
        return _execute(supabase, account, client, proposal, scoreboard,
                        now)
    except EspnAuthError as e:
        _update_proposal(
            supabase,
            proposal["id"],
            {"status": STATUS_FAILED, "error": str(e)},
        )
        raise
    except EspnError as e:
        _update_proposal(
            supabase,
            proposal["id"],
            {"status": STATUS_FAILED, "error": str(e)},
        )
        raise
    except ValueError as e:
        # Payload-shape failures while re-reading the league (the
        # account's team vanished, no current period could be derived):
        # record the claimed proposal as failed rather than stranding
        # it, then let the route map it to a 400 like other payload
        # errors. TradeError subclasses ValueError, but _execute turns
        # stale-offer validation failures into TradeStateError before
        # they can reach here.
        _update_proposal(
            supabase,
            proposal["id"],
            {"status": STATUS_FAILED, "error": str(e)},
        )
        raise


def _execute(supabase, account: dict, client, proposal: dict, scoreboard,
             now: datetime) -> dict:
    proposal_id = proposal["id"]
    # Re-validate against the live league: the world may have moved
    # since proposal, and a stale offer must fail closed, not submit.
    payload = client.get_league(["mSettings", "mTeam", "mRoster"]) or {}
    own_team = lineup.find_member_team(payload, account["swid"])
    if own_team.get("id") != proposal["team_id"]:
        _update_proposal(
            supabase,
            proposal_id,
            {
                "status": STATUS_FAILED,
                "error": "the account's team changed since proposal",
            },
        )
        raise TradeStateError("the account's team changed since proposal")
    counterparty_team = _team_by_id(
        payload, proposal["counterparty_team_id"]
    )
    try:
        if counterparty_team is None:
            raise TradeError(
                f"team {proposal['counterparty_team_id']} is no longer "
                "in this league"
            )
        _validate(
            payload,
            own_team,
            counterparty_team,
            proposal["give_player_ids"],
            proposal["receive_player_ids"],
            now,
        )
    except TradeError as e:
        _update_proposal(
            supabase,
            proposal_id,
            {
                "status": STATUS_FAILED,
                "error": f"no longer valid at approval time: {e}",
            },
        )
        raise TradeStateError(
            f"proposal is no longer valid at approval time: {e}"
        ) from e

    period = roster_edits._current_period(client, payload, scoreboard)
    try:
        response = client.post_trade_transaction(
            member_id=account["swid"],
            team_id=proposal["team_id"],
            counterparty_team_id=proposal["counterparty_team_id"],
            scoring_period_id=period,
            give_player_ids=proposal["give_player_ids"],
            receive_player_ids=proposal["receive_player_ids"],
        )
    except EspnError as e:
        # EspnAuthError subclasses EspnError: let it propagate to
        # approve_trade's auth handling; a plain failure is recorded
        # and returned as the failed proposal.
        if isinstance(e, EspnAuthError):
            raise
        stored = _update_proposal(
            supabase,
            proposal_id,
            {"status": STATUS_FAILED, "error": str(e)},
        )
        return _public({**proposal, **stored, "status": STATUS_FAILED,
                        "error": str(e)})

    status, error = _classify_outcome(response)
    transaction_id = response.get("id")
    fields = {
        "status": status,
        "error": error,
        "espn_transaction": response,
        "espn_transaction_id": (
            transaction_id
            if isinstance(transaction_id, str)
            else None
        ),
    }
    if status == STATUS_OFFERED:
        fields["executed_at"] = now.isoformat()
    stored = _update_proposal(supabase, proposal_id, fields)
    return _public({**proposal, **stored, **fields})
