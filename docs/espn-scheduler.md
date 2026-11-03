# ESPN lineup scheduler (server-side)

The daily lineup passes for automation-enabled ESPN accounts run
inside the Cozy Commons backend — no external cron or agent is
involved. Onboarding is the only setup step a leaguer ever takes:
new accounts are created with lineup automation enabled (product
decision, 2026-10-29), and this scheduler picks them up on the next
due slot. `POST /espn/automation/lineup` remains the opt-out /
re-enable switch.

## How it works

`backend/espn/scheduler.py`, invoked as `python -m espn.scheduler`
in the backend container:

- **Hourly tick, all due-logic in code.** Two slots a day,
  America/New_York: **09:00** (morning) and **18:00** (evening),
  computed with `zoneinfo`, so DST transitions need no cron edits.
  A slot is due in the window [slot, slot + 3h) — the catch-up window
  means a late tick (deploy, restart) still runs the pass, and a
  slot never runs early.
- **Fan-out.** For each due slot, every account with
  `lineup_automation_enabled = true` gets the shared run path
  (`lineup.run_lineup`, no date → the league's current scoring
  period) — the same code the `POST /espn/lineup/run` endpoint and
  the MCP tool invoke. Runs are recorded on `espn_lineup_runs` as
  usual, including failures (dead cookies → `auth_error`).
- **Dedupe.** The runner first resolves the league's actual current
  scoring period, including its scoreboard fallback. Before planning
  or writing, it checks for a completed live run (status `ok` / `noop` /
  `conflict`) for the same account, league, season and scoring period
  whose `created_at` falls inside the slot window. A matching run skips
  the pass without adding another run row. Failed runs do not dedupe;
  the next tick in the window retries them. A manual run for the current
  period satisfies the slot; a manual future-day run does not.
- **Rate limits.** Fantasy and scoreboard clients share a cooldown within each
  tick. HTTP 429 records `Retry-After` (seconds or HTTP date; default
  60 seconds when absent or invalid), blocks further ESPN requests
  during that cooldown, and defers the remaining accounts to a later
  hourly tick. The Coolify process does not sleep for the cooldown or
  retry transaction writes. This also applies when a projection helper
  catches the HTTP error or the runner returns a recorded `error`.
  Deferred accounts have no new run row and count as `deferred` in the
  summary. The cooldown is process-local; separate CLI invocations do
  not share a persisted deadline. Catch-up retries occur only while
  the slot's three-hour window remains open.
- **Isolation & logging.** A per-account failure never stops the
  fan-out. Stdout carries the audit trail under the `espn.scheduler`
  logger: one line per executed run and one summary line per tick
  (`espn scheduler tick: due=... considered=... ran=... skipped=...
  failed=... deferred=...`) — visible in the container logs.
- **Exit codes.** 0 when nothing is due or the tick completes (even
  with per-account failures); non-zero only on systemic failure
  before account work (missing service credentials, account list
  unreadable).

## Coolify setup (one-time)

On the **production backend application** (the one built from
`backend/Dockerfile`):

1. Open **Scheduled Tasks** → **Create**.
2. **Name:** `espn-lineup-scheduler`
3. **Command:** `python -m espn.scheduler`
   (The image's WORKDIR is `/app`, where the `espn` package lives,
   so the module resolves as-is. The app environment already carries
   `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` and
   `ESPN_CREDENTIALS_KEY` — the scheduler needs no new variables.)
4. **Frequency:** `0 * * * *` (hourly; due windows are enforced in
   code, not by the cron expression).
5. **Container:** the backend application container (default).
6. **Timeout:** a single account's pass makes a sequence of paced
   ESPN calls and normally finishes in well under a minute, but a
   tick over many accounts can run for several minutes. If your
   Coolify version exposes a per-task timeout, set it generously
   (e.g. 1800s). Overlapping ticks are safe regardless — the
   run-log dedupe plus the runner's idempotency make a second pass
   a recorded no-op.

## Verify after enabling

- Container logs show an hourly `espn scheduler tick:` line; outside
  due windows it reads `no slot due`.
- At the first due slot after enabling, expect one
  `espn scheduler run: account=... slot=morning|evening status=...`
  line per enabled account, and the runs appear in each account's
  `GET /espn/lineup/runs` history.

## Cutover from external agent crons

The agent-side lineup crons (morning + evening) retire **the day
this Coolify task is enabled** — running both during a transition is
safe (the scheduler dedupes against any completed live run in the
window, whoever fired it), but leaving both on indefinitely just
adds a redundant daily pass. Reporting (conflict/failure surfacing
to the user) stays agent-side: it reads the run log, which this
scheduler keeps filling exactly as before.

## Follow-up (outside this change)

The hosted connect page copy (cozycommons.dev/fantasy/connect)
should disclose that onboarding turns on automatic lineup setting —
the flow no longer asks, it informs. Frontend copy lives outside
this backend change.
