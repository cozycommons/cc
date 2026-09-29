"""Authorization for ig_logger scan-job endpoints.

Two auth modes, same as the original Beli watcher:
- Harness service key (BELI_EATS_INGEST_KEY env var): platform-wide work —
  creating a job scoped to every subscribed account ('all').
- Personal API token (ccb_...): the caller's own account only.

The key name is historical (it predates the platform); it is the
platform-wide ingest key regardless of which sink's data is flowing.
"""

from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request

from .accounts import AccountError, get_account_row_by_token


def ingest_service_key_ok(request: Request) -> bool:
    """Validate the harness service key.

    Fail closed: missing server-side key never authenticates.
    """
    expected = os.environ.get("BELI_EATS_INGEST_KEY")
    if not expected:
        return False
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return scheme.lower() == "bearer" and bool(token) and secrets.compare_digest(
        token, expected
    )


def resolve_scan_scope(request: Request) -> str | None:
    """Resolve scan-job authorization to a scope.

    Returns None when the harness service key authenticated (every
    subscribed account), or the account id when a personal API token
    authenticated (the caller's account only). Raises 401 otherwise.
    """
    if ingest_service_key_ok(request):
        return None
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    try:
        if scheme.lower() != "bearer" or not token:
            raise AccountError("missing bearer token")
        account = get_account_row_by_token(
            request.app.state.supabase, token
        )
    except AccountError:
        raise HTTPException(status_code=401, detail="invalid service key or token")
    return account["id"]
