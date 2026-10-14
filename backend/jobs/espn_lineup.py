"""Optional ESPN lineup batch entrypoint (inert — nothing self-schedules).

The trigger surface for lineup automation is the run endpoint
(POST /espn/lineup/run) and the MCP tool ``run_lineup``, invoked
externally — in production a daily caller hits the endpoint for each
opted-in account and reads conflicts back from the run log
(GET /espn/lineup/runs).

This module is a callable convenience for running the same shared path
across every opted-in account in one process. It registers no timers,
threads, or schedules: it does work only when someone invokes it, e.g.
from the backend directory with service credentials in the environment
(or ``.env.local``):

    python -m jobs.espn_lineup

It calls the shared run path with NO date argument, which defaults to
the league's current scoring period — the exact code path adhoc runs
use for any date. Runs are idempotent: when a lineup is already
correct the run records ``noop`` and submits nothing, so extra
invocations are harmless. Conflicts (a scheduled player forced to
sit, dead cookies, verify mismatches) land on the run rows in
``espn_lineup_runs``.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from supabase import create_client

from espn import accounts, lineup

logger = logging.getLogger(__name__)


def run_all_accounts(client_supabase) -> dict:
    """Run the lineup pass for every opted-in account; returns a summary."""
    summary = {"accounts": 0, "statuses": {}}
    for account in accounts.list_lineup_automation_accounts(client_supabase):
        summary["accounts"] += 1
        client = accounts.make_client_for_account(account)
        run = lineup.run_lineup(client_supabase, account, client)
        status = run.get("status")
        summary["statuses"][status] = summary["statuses"].get(status, 0) + 1
        logger.info(
            "ESPN lineup run account=%s league=%s status=%s conflicts=%s",
            account.get("id"),
            account.get("league_id"),
            status,
            len(run.get("conflicts") or []),
        )
    return summary


def run_job() -> None:
    load_dotenv(dotenv_path=".env.local", override=False)
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("ESPN lineup job requires Supabase service credentials")
    summary = run_all_accounts(create_client(url, key))
    logger.info("ESPN lineup job finished: %s", summary)


if __name__ == "__main__":
    run_job()
