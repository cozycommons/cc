"""Shared safeguards for approval-gated writes with an unknown outcome."""

from .espn_client import EspnError

UNCERTAIN = "uncertain"
UNKNOWN = "unknown"
UNRESOLVED = {"uncertain", "unknown", "executing"}
UNCERTAIN_MESSAGE = (
    "ESPN submission outcome is unresolved; reread ESPN to reconcile this "
    "proposal before replacing it. No automatic resubmission is allowed."
)


def may_have_submitted(error: EspnError) -> bool:
    # An HTTP rejection is conclusive; a lost response or server error is not.
    return (getattr(error, "uncertain", False) or error.status is None
            or error.status >= 500 or error.status == 408)


def player_ids(row: dict) -> set:
    return {pid for pid in (
        row.get("add_player_id"), row.get("drop_player_id"),
        *(row.get("give_player_ids") or []),
        *(row.get("receive_player_ids") or []),
    ) if pid is not None}


def check_unresolved(supabase, account, client, players, error_type, exclude=None):
    """Block overlapping writes across both gates, scoped to this account/league.

    Executing rows also block replacements: a process can lose its connection
    after ESPN accepted a write but before recording the result locally.
    """
    for table in ("espn_roster_edits", "espn_trade_proposals"):
        for status in sorted(UNRESOLVED):
            rows = (supabase.table(table).select("*")
                    .eq("account_id", account["id"])
                    .eq("league_id", account.get("league_id"))
                    .eq("season", account.get("season"))
                    .eq("status", status).execute()).data or []
            for row in rows:
                if exclude == (table, row["id"]):
                    continue
                if players & player_ids(row):
                    # A new proposal first tries read-only reconciliation of the old
                    # write. Import locally to keep the two gates independent.
                    from . import roster_edits, trades
                    module = roster_edits if table == "espn_roster_edits" else trades
                    resolved = module._reconcile(supabase, account, client, row)
                    if resolved["status"] not in UNRESOLVED:
                        continue
                    raise error_type(
                        f"unresolved ESPN write {row['id']} involves the same "
                        "players; reconcile it before creating or approving a replacement"
                    )


def transactions(payload):
    """Only complete transaction objects can supply positive evidence."""
    rows = payload.get("transactions")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def baseline(client):
    payload = client.get_league(["mTransactions2"]) or {}
    if not isinstance(payload.get("transactions"), list):
        return None  # An incomplete baseline cannot exclude an older identical offer.
    return [str(row["id"]) for row in transactions(payload)
            if row.get("id") is not None]


def metadata(response, baseline_ids, period, error=None):
    return {"response": response, "baseline_transaction_ids": baseline_ids,
            "scoring_period_id": period,
            "submission_error": str(error) if error else None}


def matching_transaction(payload, row, kind, expected_items):
    """Match a NEW, exact directed transaction, never an older identical offer."""
    audit = row.get("espn_transaction") or {}
    if not isinstance(audit.get("baseline_transaction_ids"), list):
        return None
    previous_ids = set(audit["baseline_transaction_ids"])
    for txn in transactions(payload):
        if (txn.get("id") is None or str(txn["id"]) in previous_ids
                or txn.get("type") not in kind
                or txn.get("teamId") != row["team_id"]):
            continue
        actual = [(item.get("playerId"), item.get("type"),
                   item.get("fromTeamId"), item.get("toTeamId"))
                  for item in txn.get("items") or [] if isinstance(item, dict)]
        if len(actual) == len(expected_items) and set(actual) == set(expected_items):
            return txn
    return None
