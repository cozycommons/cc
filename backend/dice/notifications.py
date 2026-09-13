"""SMS notifications for ranked Dice game results, sent via Twilio."""

from __future__ import annotations

import logging
import os

from supabase import Client

from dice.repository import PROFILES_TABLE
from dice.schemas import DiceGame
from runtime_policy import RuntimePolicy

logger = logging.getLogger(__name__)

SITE_URL = os.getenv("SITE_URL", "http://localhost:8080").rstrip("/")


def _team_label(game: DiceGame, team: int) -> str:
    names = [p.display_name for p in game.players if p.team == team]
    return " & ".join(names) if names else f"Team {team}"


def _build_message(game: DiceGame) -> str:
    loser_team = 2 if game.winner_team == 1 else 1
    winner = _team_label(game, game.winner_team)
    loser = _team_label(game, loser_team)
    winner_score = game.team1_score if game.winner_team == 1 else game.team2_score
    loser_score = game.team2_score if game.winner_team == 1 else game.team1_score
    link = f"{SITE_URL}/dice/game/{game.id}"
    return f"Dice: {winner} beat {loser} {winner_score}-{loser_score}. {link}"


def notify_ranked_game(
    supabase: Client, game: DiceGame, runtime_policy: RuntimePolicy
) -> None:
    """Text every player who's opted in to ranked-game-result alerts, whether
    or not they were in this particular game.

    Best-effort: this runs as a background task after the game is already
    saved, so a Twilio outage or a bad phone number must never surface back
    to the game-logging flow.
    """
    if not runtime_policy.allow_external_side_effects:
        logger.info("Dice local harness; skipping game-result SMS")
        return

    if not game.ranked:
        return

    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_PHONE_NUMBER")
    if not account_sid or not auth_token or not from_number:
        logger.warning("Twilio not configured; skipping Dice game-result SMS")
        return

    rows = (
        supabase.table(PROFILES_TABLE)
        .select("user_id, phone_number")
        .eq("sms_notifications_enabled", True)
        .execute()
        .data
        or []
    )
    recipients = [row["phone_number"] for row in rows if row.get("phone_number")]
    if not recipients:
        return

    from twilio.rest import Client as TwilioClient

    client = TwilioClient(account_sid, auth_token)
    body = _build_message(game)
    for phone_number in recipients:
        try:
            client.messages.create(to=phone_number, from_=from_number, body=body)
        except Exception:
            logger.exception("Failed to send Dice game-result SMS to %s", phone_number)
