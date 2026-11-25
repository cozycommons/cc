# Maple Telemetry

Per-user MapleStory Classic telemetry in the shared Cozy Commons backend.
Phase 1 is the EXP producer: the EXP Overlay's log lines (one per day /
map / level / class / party size, with EXP and mesos totals) shipped from
the player's machine and read back by agents. The FM watcher is a planned
second producer on the same account model.

## Layout

- `backend/maple/` — accounts (tokens), run logic, REST routes, MCP server.
- Routes under `/telemetry`; MCP at `/telemetry/mcp` (streamable HTTP).
- `clients/maple-shipper/` — the stdlib-only Python shipper that runs on
  the player's Mac (launchd agent) and POSTs log lines as they change.
  It lives in this repo so ingest-contract changes land atomically with
  the client that implements them.
- Tables (migration `0094_beli_maple_telemetry.sql`, beli family):
  `maple_accounts`, `maple_exp_runs`.

## Accounts and tokens

Onboarding is open and identical for every user (mirrors the ESPN
pattern): `POST /telemetry/onboard {"label": "..."}` creates an account
and returns a personal token (`ccm_...`) **once**. Only the token's
sha256 hash is stored; there are no third-party credentials in this
module. Every request resolves the bearer token to exactly one account,
and every telemetry row carries that account's id as `user_id` — one
user's token can never read or write another's rows. Token resolution
uses the uncached `app.state.maple_supabase` client, so deleting an
account (`DELETE /telemetry/account`) retires its token on the next
request. Onboarding is rate-limited per IP (10/hour).

## Ingest contract

`POST /telemetry/ingest/exp-runs {"runs": [<overlay entry>, ...]}` —
entries exactly as the overlay writes them in `exp_log.json`, plus the
file's top-level `install` id on each entry. A run's identity is its key
(producer, install, date, map, level, party, class); the `run_id` is a
sha256 over that key, computed identically by the shipper
(`clients/maple-shipper/shipper.py`) and the backend
(`backend/maple/logic.py`). Entries keep growing while a player stays on
a map, so ingest **upserts** on `(user_id, run_id)`: re-posting a line
replaces its totals instead of duplicating it. Rows are validated
independently; the response is `{"accepted": [run_id...], "rejected":
[{"index", "error"}...]}` and batches cap at 500.

Rates are computed on read, mirroring the overlay's arithmetic:
EXP/hr = `exp / seconds`, mesos/hr = `mesos / mesos_seconds`,
net/hr = mesos/hr − `potion_cost / potion_seconds` (null when no potion
cost was counted).

## Reads

- `GET /telemetry/me` — the token's account.
- `GET /telemetry/exp/runs?limit=&map=&level=` — runs, newest first.
- `GET /telemetry/exp/maps?level=` — per-map aggregates (best and
  time-weighted average EXP/hr), best first.
- MCP tools (`api_token` per call, the legacy per-project pattern):
  `get_me`, `get_recent_exp_runs`, `get_exp_runs_by_map`,
  `get_best_exp_rates`.

## Shipper behavior

The shipper checkpoints a fingerprint of every server-confirmed line in
a local `checkpoint.json` and advances it only on acceptance
(store-and-forward). First run backfills the entire existing
`exp_log.json` history. Install and token steps:
`clients/maple-shipper/README.md`.
