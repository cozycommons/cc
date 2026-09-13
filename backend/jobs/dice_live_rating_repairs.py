"""Retry canonical rating replay for durable ranked live-result work."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from supabase import create_client

from dice.repository import (
    list_pending_live_rating_repairs,
    record_live_rating_repair_failure,
    sync_live_result_rating,
)

logger = logging.getLogger(__name__)


def repair_pending_live_ratings(client, limit: int = 25, *, raise_on_error: bool = False) -> int:
    repaired = 0
    failed = 0
    for match_id in list_pending_live_rating_repairs(client, limit):
        try:
            sync_live_result_rating(client, match_id, bounded=True)
            repaired += 1
        except Exception as error:  # noqa: BLE001 - transport errors vary
            failed += 1
            logger.exception("Dice live rating repair failed for match %s", match_id)
            try:
                record_live_rating_repair_failure(client, match_id, error)
            except Exception:  # noqa: BLE001 - the durable queue already exists
                logger.exception("Could not annotate Dice live rating repair for match %s", match_id)
    if failed and raise_on_error:
        raise RuntimeError(f"Dice rating maintenance failed for {failed} match(es); {repaired} repaired")
    return repaired


def run_job() -> None:
    load_dotenv(dotenv_path=".env.local", override=False)
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("Dice live rating repair requires Supabase service credentials")
    repaired = repair_pending_live_ratings(create_client(url, key))
    logger.info("Dice live rating repair processed %s matches", repaired)
