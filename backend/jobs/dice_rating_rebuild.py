"""Periodically reconcile persisted individual ratings with canonical history."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from supabase import create_client

from dice.rating_replay import build_rating_plan, verify_rating_state

logger = logging.getLogger(__name__)


def rebuild_canonical_ratings(client, attempts: int = 3) -> int:
    for attempt in range(attempts):
        source = client.rpc("dice_rating_source_snapshot").execute().data
        plan = build_rating_plan(source)
        try:
            result = client.rpc("dice_rating_commit_rebuild", {
                "p_source": plan.source,
                "p_player_snapshots": plan.player_snapshots,
                "p_profile_states": plan.profile_states,
            }).execute().data
        except Exception as error:  # noqa: BLE001 - PostgREST errors vary
            if "dice_rating.source_changed" in str(error) and attempt + 1 < attempts:
                continue
            raise
        verify_rating_state(result.get("state"), plan)
        return plan.eligible_ranked_games
    raise AssertionError("unreachable")


def run_job() -> None:
    load_dotenv(dotenv_path=".env.local", override=False)
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("Dice rating rebuild requires Supabase service credentials")
    games = rebuild_canonical_ratings(create_client(url, key))
    logger.info("Dice canonical rating rebuild replayed %s ranked games", games)
