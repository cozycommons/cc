from __future__ import annotations

import asyncio
import logging
import os
from time import perf_counter

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()
_process_start = perf_counter()
_READINESS_TIMEOUT_SECONDS = float(os.getenv("READINESS_TIMEOUT_SECONDS", "2"))


def _check_required_schema(supabase) -> None:
    """Attest actual Dice and Commons schema, not a copied version ledger."""
    result = supabase.rpc("dice_release_readiness").execute()
    if result.data is not True:
        raise RuntimeError("Release schema attestation failed")


@router.get("/health")
def health_check():
    """Cheap process liveness probe; deliberately performs no network I/O."""
    return {
        "status": "ok",
        "uptime_seconds": round(perf_counter() - _process_start, 3),
    }


@router.get("/ready")
async def readiness_check(request: Request):
    """Bounded dependency and core-schema probe for deployment readiness."""
    supabase = getattr(request.app.state, "readiness_supabase", None) or getattr(request.app.state, "supabase_admin", None)
    if supabase is None:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "reason": "supabase_not_configured"},
        )

    try:
        await asyncio.wait_for(
            asyncio.to_thread(_check_required_schema, supabase),
            timeout=_READINESS_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Readiness database check timed out")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "reason": "database_timeout"},
        )
    except Exception:
        logger.exception("Readiness database check failed")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "reason": "database_unavailable"},
        )

    return {"status": "ready"}
