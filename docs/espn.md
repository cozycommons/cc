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

Courtside can upload a daily `public-v2` JSON snapshot (`public-v1` remains accepted) with
`POST /espn/public/predictions`, using `Authorization: Bearer <token>` matching
the backend's `ESPN_PUBLIC_PREDICTIONS_TOKEN`. Without that environment variable,
uploads return 503. The upload limit is 256 KiB; unsupported fields and invalid
values return 422 without echoing the input. V2 includes a team directory (up to
20 public team IDs, names, abbreviations, and logos), matchups referencing those
IDs, and up to 15 players per side on final/live days; projected days cannot
include players. Logos must be HTTPS URLs on `g.espncdn.com` (up to 300 chars),
embedded base64 PNGs of at most 24 KiB decoded, or null. Optional season forecasts
include standings and dated playoff odds for `projections`, `balanced`, and `hot`
modes, with place probabilities covering all teams and summing to 100 ± 0.5.
League IDs, ESPN cookies, account data, and private player fields are forbidden.
The optional `names` field accepts `real`, `abbrev`, or `initials`.
V2 also accepts `season_year` (an integer from 2000–2100) and an optional nullable
`teams[].manager` (up to 40 characters, starting with an ASCII letter and
containing only ASCII letters, spaces, apostrophes, hyphens, and periods).
The existing `season` forecast object is unchanged.

`GET /espn/public/predictions/latest` is public and returns the most recently
received snapshot of either version, with a five-minute public cache header (404 before the first
upload). Snapshots dated in the future are rejected. Rows are append-only;
retrying the same `(matchup.id, generated_at)` returns `stored: false`. Removing a
bad row needs a database administrator. These routes never contact ESPN.
Migration `0009_beli_espn_public_predictions.sql` is applied by the normal
`python -m release` step on deploy; do not apply it from a branch beforehand.

## Team claims

Signed-in Cozy users can link their Dice profile to a public fantasy team.
`GET /espn/claims/suggestions` uses the Dice display name and Google profile
names to rank teams by manager name, with weaker matches against team names.
Suggestions never claim a team automatically. Confirm with
`POST /espn/claims` and `{"season":2027,"team_id":1}`. These endpoints use the
same Supabase bearer authentication as Dice, and confirmation requires an
existing Dice profile. Each user and team can hold one claim per season;
confirming another available team moves the user's link atomically. Conflicts
return 409 with `profile_required` or `team_claimed`. Self-service links need a
name match (score ≥ 0.5, shown as `can_claim` in suggestions); other teams
return 403 `name_mismatch`. Dice admins can link any team. The owner or a Dice
admin can remove a link with `DELETE /espn/claims/{season}/{team_id}`.

`GET /espn/public/claims?season=2027` exposes only confirmed team IDs, Dice
display names, and HTTPS avatars, cached publicly for 60 seconds. An absent or
unknown season uses the latest stored snapshot's season; no snapshot returns
an empty list. Claims use `season_year`; older snapshots derive the NBA ending
year from `captured_at`, rolling over on July 1. Snapshot lookups prefer the
latest stored snapshot with a team list (v1 rows are skipped). Until uploads
exist, they fall back to the published interim snapshot at
`ESPN_PUBLIC_PREDICTIONS_FALLBACK_URL` (default: the public gist), fetched
without redirects, capped at 256 KB, validated as `public-v2`, and cached for
five minutes; any failure means no snapshot. Set the variable empty to disable
it. Migration `0010_beli_espn_team_claims.sql` advances the Beli schema
contract to 10 and installs the service-only table and atomic claim function
through the normal release step.

Migration `0011_beli_espn_seed_team_claims.sql` pre-links the 2026-27 managers
who already had Dice profiles (10 of 12, matched on the ESPN owner's full name).
It only inserts for users that exist and never replaces an existing link; those
users can unlink like any other claim.

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
