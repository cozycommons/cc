"""Server-side scheduler for ESPN daily lineup automation.

Until now the daily lineup passes were triggered from outside the
backend (an agent cron hitting POST /espn/lineup/run per account).
This module moves the trigger in-house: a dumb hourly tick (Coolify
Scheduled Task, ``0 * * * *``) runs ``python -m espn.scheduler`` in the
backend container, and all due-logic lives here, in code:

  - Two slots a day, America/New_York: 09:00 (morning) and 18:30
    (evening), computed with zoneinfo so DST is handled by the tz
    database, not by a twice-a-year cron edit.
  - A slot is due when now(ET) is in [slot, slot + 3h) — the catch-up
    window means a tick that fires late (deploy, container restart)
    still runs the pass, and a slot is never run early.
  - Every account with ``lineup_automation_enabled`` (the accounts
    helper's server-side list) gets the shared run path —
    ``lineup.run_lineup`` with no date, i.e. the league's current
    scoring period — exactly as the run endpoint invokes it. No HTTP
    self-call, no per-user bearer token: the account row's decrypted
    cookies build the client, server-side.
  - Dedupe: before running a slot for an account, the run log is
    checked for a completed live run whose ``created_at`` falls inside
    the slot's window. "Completed" = status ok / noop / conflict (the
    pass ran end to end and the best legal lineup was submitted;
    conflict only adds a recorded caveat). error / auth_error runs do
    NOT dedupe — the next tick inside the window retries them, which
    is what the catch-up window is for. This reads no new schema: it
    keys on (account_id, mode='live', status, created_at in window).
    Approximation, deliberately: an adhoc live run a user fires by
    hand inside a window also satisfies the slot (it is the same pass
    for the same day), and a run that lands exactly on a window edge
    belongs to the window it timestamp-falls into.
  - Isolation: a per-account failure (dead cookies, an ESPN error
    that escapes the runner, a failed dedupe read) is caught, logged
    and counted; it never stops the fan-out. The runner itself
    records failed runs on the account's run log as usual.

Exit codes: 0 when nothing is due and when the tick completes (even
with per-account failures); non-zero only on systemic failure before
account work (missing service credentials, account list unreadable).

Logs go to stdout under the ``espn.scheduler`` logger — one line per
executed run and one summary line per tick — which is the audit trail
Coolify's container logs show. See docs/espn-scheduler.md for the
Coolify Scheduled Task setup and the cutover from external crons.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from supabase import create_client

from . import accounts, lineup
from .scoreboard import ScoreboardClient

logger = logging.getLogger("espn.scheduler")

ET = ZoneInfo("America/New_York")

# (ET wall-clock time, slot name): the morning pass sets the day's
# lineup, the evening pass re-checks it against late news (injuries,
# lineup announcements) for the same scoring period.
SLOT_TIMES = ((time(9, 0), "morning"), (time(18, 30), "evening"))
CATCH_UP = timedelta(hours=3)

# Live-run statuses that count as "this slot already ran" for dedupe.
SUCCESS_STATUSES = ("ok", "noop", "conflict")
# Statuses a returned run can carry that mean the pass failed.
FAILURE_STATUSES = ("error", "auth_error")


@dataclass(frozen=True)
class SlotWindow:
    """One due slot on one ET calendar day, as aware ET datetimes."""

    name: str
    start: datetime
    end: datetime


def due_slots(now: datetime) -> list[SlotWindow]:
    """Slots due at ``now`` (pure; ``now`` may carry any tz).

    At most one slot can be due at a time — the windows never overlap
    — but the return is a list so the fan-out does not depend on that.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now_et = now.astimezone(ET)
    due = []
    for slot_time, name in SLOT_TIMES:
        start = datetime.combine(now_et.date(), slot_time, tzinfo=ET)
        end = start + CATCH_UP
        if start <= now_et < end:
            due.append(SlotWindow(name=name, start=start, end=end))
    return due


def _has_completed_run(supabase, account_id, slot: SlotWindow) -> bool:
    """True when a completed live run already exists inside ``slot``.

    The created_at window is the dedupe key (see module docstring for
    the approximation): PostgREST compares the timestamptz server-side
    against the slot's UTC bounds.
    """
    res = (
        supabase.table("espn_lineup_runs")
        .select("id")
        .eq("account_id", account_id)
        .eq("mode", "live")
        .in_("status", list(SUCCESS_STATUSES))
        .gte("created_at", slot.start.astimezone(timezone.utc).isoformat())
        .lt("created_at", slot.end.astimezone(timezone.utc).isoformat())
        .limit(1)
        .execute()
    )
    return bool(res.data)


def run_tick(
    supabase,
    now: datetime | None = None,
    *,
    accounts_loader=accounts.list_lineup_automation_accounts,
    runner=lineup.run_lineup,
    client_factory=accounts.make_client_for_account,
    scoreboard_factory=ScoreboardClient,
) -> dict:
    """One scheduler tick: run every due slot for every enabled account.

    Returns a summary dict: {"due_slots", "considered", "ran",
    "skipped", "failed"} — considered = enabled accounts loaded, and
    ran + skipped + failed accounts for the considered set (per due
    slot; with the windows never overlapping there is at most one).
    A failure to load the account list propagates (systemic).
    """
    now = now or datetime.now(timezone.utc)
    slots = due_slots(now)
    summary = {
        "due_slots": [slot.name for slot in slots],
        "considered": 0,
        "ran": 0,
        "skipped": 0,
        "failed": 0,
    }
    if not slots:
        logger.info(
            "espn scheduler tick: no slot due (now=%s ET)",
            now.astimezone(ET).isoformat(),
        )
        return summary

    enabled = accounts_loader(supabase)
    summary["considered"] = len(enabled)
    for slot in slots:
        for account in enabled:
            account_id = account.get("id")
            if not account.get("lineup_automation_enabled"):
                # The loader already filters on the flag; this is a
                # belt-and-braces guard so a disabled account can
                # never be run by the fan-out.
                summary["skipped"] += 1
                continue
            try:
                already_ran = _has_completed_run(supabase, account_id, slot)
            except Exception:
                summary["failed"] += 1
                logger.exception(
                    "espn scheduler: account=%s slot=%s dedupe check failed",
                    account_id,
                    slot.name,
                )
                continue
            if already_ran:
                summary["skipped"] += 1
                logger.info(
                    "espn scheduler: account=%s slot=%s skipped "
                    "(completed live run already in window)",
                    account_id,
                    slot.name,
                )
                continue
            try:
                client = client_factory(account)
                run = runner(
                    supabase,
                    account,
                    client,
                    scoreboard=scoreboard_factory(),
                )
            except Exception:
                summary["failed"] += 1
                logger.exception(
                    "espn scheduler: account=%s slot=%s run raised",
                    account_id,
                    slot.name,
                )
                continue
            status = run.get("status")
            if status in FAILURE_STATUSES:
                summary["failed"] += 1
            else:
                summary["ran"] += 1
            logger.info(
                "espn scheduler run: account=%s slot=%s period=%s "
                "status=%s conflicts=%s",
                account_id,
                slot.name,
                run.get("scoring_period_id"),
                status,
                len(run.get("conflicts") or []),
            )
    logger.info(
        "espn scheduler tick: due=%s considered=%d ran=%d skipped=%d "
        "failed=%d",
        ",".join(summary["due_slots"]) or "none",
        summary["considered"],
        summary["ran"],
        summary["skipped"],
        summary["failed"],
    )
    return summary


def main() -> int:
    """Container entry point: ``python -m espn.scheduler``.

    Mirrors the batch entrypoint's credential handling (jobs/
    espn_lineup.py): service credentials come from the environment
    (Coolify injects them in the container; a local .env.local is
    honoured for manual runs from the backend directory).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv(dotenv_path=".env.local", override=False)
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        logger.error(
            "espn scheduler: SUPABASE_URL / SUPABASE_SERVICE_KEY are "
            "not set; cannot run"
        )
        return 1
    supabase = create_client(url, key)
    try:
        run_tick(supabase)
    except Exception:
        logger.exception("espn scheduler: tick failed (systemic)")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
