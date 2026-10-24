# ESPN Fantasy

Per-user ESPN Fantasy basketball on Cozy Commons: read analytics for your
league (standings, rosters, trends) plus automatic daily lineup setting.
Code: `backend/espn/`. Routes: `/espn/*`. MCP: `/espn/mcp`.

Lineup setting means slot moves only — starters, bench, IR. There are no
add/drop/trade endpoints, and there never will be in this integration.

## What you need

- Your **league ID** — the `leagueId` number in your league's URL on
  fantasy.espn.com.
- The **season** — the ending year. The 2026–27 season is `2027`.
- Two cookies from your logged-in ESPN session: **`espn_s2`** and **`SWID`**.

Get the cookies in Chrome:

1. Log in at fantasy.espn.com and open your league.
2. Press F12 → **Application** tab → **Storage → Cookies** → the ESPN site.
3. Copy the values of `espn_s2` and `SWID` (SWID includes the `{ }` braces — copy it whole).

Treat both cookies like a password: together they are a login to your ESPN
account. On the server they're encrypted at rest; never paste them into a
chat or a shared doc.

## Onboard

```bash
curl -s -X POST https://<backend-host>/espn/onboard \
  -H 'Content-Type: application/json' \
  -d '{"label":"your-name","league_id":1234567,"season":2027,"espn_s2":"...","swid":"{...}"}'
# -> {"id":"...","label":"your-name","league_id":1234567,"season":2027,"token":"cce_..."}
```

The response contains your personal **`cce_...` token — it is shown once.**
Save it somewhere safe; it cannot be retrieved later. Every other call uses it:

```bash
curl -s https://<backend-host>/espn/me -H "Authorization: Bearer <token>"
# -> your account, plus "lineup_automation_enabled": false (for now)
```

## Turn on daily lineup setting

```bash
curl -s -X POST https://<backend-host>/espn/automation/lineup \
  -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
  -d '{"enabled": true}'
```

Honest fine print: the backend has no scheduler. Opting in flags your
account, but a run only happens when someone calls `POST /espn/lineup/run`
(or the `run_lineup` MCP tool) — e.g. a daily cron on your own Muse.
Nothing runs your lineup until that trigger exists.

## The daily rule

Every player who has a game that day starts (a player ruled OUT doesn't
count; questionable/game-time-decision does). If the scheduled players
can't all fit — more players than starting slots, or positions that can't
be reconciled — the higher fantasy-PPG player starts and the lower one
sits. Each sit is recorded as a **conflict**, visible in
`GET /espn/lineup/runs`, so you always know who sat and why.

## Good to know

- **One league per account, basketball only.**
- **Current day only.** ESPN rejects lineup writes for future days.
  Previewing tomorrow still works: `POST /espn/lineup/run` with
  `{"date":"2026-10-24","dry_run":true}` shows the plan without applying it.
- **Cookies expire.** When calls start returning 401 / `auth_error`, log in
  to ESPN again and re-onboard with fresh cookies. Re-onboarding mints a
  new account and a new token — update wherever the old token was saved.
- Runs are idempotent per day: calling `/espn/lineup/run` twice is safe.

## Public predictions

Courtside can upload a daily `public-v1` JSON snapshot with
`POST /espn/public/predictions`, using `Authorization: Bearer <token>` matching
the backend's `ESPN_PUBLIC_PREDICTIONS_TOKEN`. Without that environment variable,
uploads return 503. The upload limit is 256 KiB; unsupported fields and invalid
values return 422. Only team display names and aggregate estimates are accepted:
no player data, team/league IDs, ESPN cookies, or account data are accepted.
The optional `names` field accepts `real`, `abbrev`, or `initials`.

`GET /espn/public/predictions/latest` is public and returns the most recently
received snapshot, with a five-minute public cache header (404 before the first
upload). Snapshots dated in the future are rejected. Rows are append-only;
retrying the same `(matchup.id, generated_at)` returns `stored: false`. Removing a
bad row needs a database administrator. These routes never contact ESPN.
Migration `0009_beli_espn_public_predictions.sql` is applied by the normal
`python -m release` step on deploy; do not apply it from a branch beforehand.

## Routes

| Route | What it does |
| --- | --- |
| `POST /espn/onboard` | Store your ESPN cookies, get your token (once) |
| `GET /espn/me` | Check a token / describe your account |
| `GET /espn/league` | League settings + team list |
| `GET /espn/standings` | Teams ranked by wins, then points for |
| `GET /espn/teams/{team_id}` | One team + its roster |
| `GET /espn/transactions` | Recent transactions (player IDs only) |
| `GET /espn/trends/players` | Ownership + performance trends |
| `GET /espn/trends/teams` | Per-team form / all-play / luck trends |
| `GET /espn/draft` | Draft picks in overall-pick order |
| `POST /espn/automation/lineup` | Opt in/out of lineup automation (`{"enabled": true}`) |
| `POST /espn/lineup/run` | Set a day's lineup now (or `dry_run` a plan) |
| `GET /espn/lineup/runs` | Past runs + their conflicts |

The same operations are available as MCP tools at `/espn/mcp` — pass your
token as the `api_token` argument.
