"""Virtual Dice match-winner offers and live-match lifecycle reconciliation."""

from typing import Any

from supabase import Client

from dice.live_types import DiceLiveError, DiceLiveErrorCode


LEDGER_PAGE_SIZE = 1000


def tournament_virtual_leaderboard(client: Client, tournament_id: str) -> list[dict[str, Any]]:
    """Rank enrolled players by the sum of their append-only ledger entries."""
    enrollments = (
        client.table("dice_tournament_enrollments")
        .select("user_id")
        .eq("tournament_id", tournament_id)
        .execute()
        .data
        or []
    )
    user_ids = sorted({row["user_id"] for row in enrollments})
    if not user_ids:
        return []

    profiles = (
        client.table("dice_profiles")
        .select("user_id,display_name")
        .in_("user_id", user_ids)
        .execute()
        .data
        or []
    )
    names = {row["user_id"]: row.get("display_name") or "Player" for row in profiles}
    balances = {user_id: 0 for user_id in user_ids}

    offset = 0
    while True:
        rows = (
            client.table("dice_virtual_ledger")
            .select("user_id,amount")
            .eq("tournament_id", tournament_id)
            .range(offset, offset + LEDGER_PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        for row in rows:
            if row["user_id"] in balances:
                balances[row["user_id"]] += row["amount"]
        if len(rows) < LEDGER_PAGE_SIZE:
            break
        offset += LEDGER_PAGE_SIZE

    ordered = sorted(user_ids, key=lambda user_id: (-balances[user_id], user_id))
    return [
        {
            "rank": rank,
            "user_id": user_id,
            "display_name": names.get(user_id, "Player"),
            "balance": balances[user_id],
        }
        for rank, user_id in enumerate(ordered, start=1)
    ]


def fixed_winner_selections(team_order: list[str], team1_probability: float) -> dict[str, dict[str, int]]:
    if len(team_order) != 2 or len(set(team_order)) != 2:
        raise DiceLiveError(DiceLiveErrorCode.INVALID_STATE, "winner market requires two distinct teams")
    if not 0.0 < team1_probability < 1.0:
        raise DiceLiveError(DiceLiveErrorCode.INVALID_STATE, "winner market probabilities must be non-terminal")
    team1 = min(999_999, max(1, round(team1_probability * 1_000_000)))
    return {
        team_order[0]: {"probability_millionths": team1},
        team_order[1]: {"probability_millionths": 1_000_000 - team1},
    }


def reconcile_match_winner_markets(
    client: Client,
    match_id: str,
    team_order: list[str],
    current_version: int,
    official_result: dict[str, Any] | None,
) -> None:
    """Map accepted live state to existing close and settlement operations."""
    markets = (
        client.table("dice_virtual_markets")
        .select("id,status,match_version")
        .eq("live_match_id", match_id)
        .eq("kind", "match_winner")
        .execute()
        .data
        or []
    )
    if not markets:
        return

    for market in markets:
        if market["status"] == "open" and current_version > market["match_version"]:
            (
                client.table("dice_virtual_markets")
                .update({"status": "closed"})
                .eq("id", market["id"])
                .eq("status", "open")
                .execute()
            )

    result_state = None
    if official_result is not None:
        result_state = official_result.get("state", official_result.get("live_result_state"))
        if result_state not in {"official", "reopened"}:
            raise ValueError("official result has an invalid state")
    result_is_official = result_state == "official"
    if result_is_official:
        winner_team = official_result.get("winner_team")
        if winner_team is None:
            winner_selection = None
        elif type(winner_team) is int and 1 <= winner_team <= len(team_order):
            winner_selection = team_order[winner_team - 1]
        else:
            raise ValueError("official result has an invalid winner_team")
        for market in markets:
            client.rpc(
                "dice_virtual_settle_market",
                {"p_market_id": market["id"], "p_winner_selection": winner_selection},
            ).execute()
        return

    # In-progress closed markets stay pending. Only prior settlements need a
    # compensating void/refund when their official result disappears.
    for market in markets:
        if market["status"] == "settled":
            client.rpc(
                "dice_virtual_settle_market",
                {"p_market_id": market["id"], "p_winner_selection": None},
            ).execute()
