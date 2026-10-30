# ESPN Fantasy

Per-user ESPN Fantasy basketball on Cozy Commons: read analytics for your
league (standings, rosters, trends) plus automatic daily lineup setting.
Code: `backend/espn/`. Routes: `/espn/*`. MCP: `/espn/mcp`.

Lineup setting means slot moves only — starters, bench, IR. Roster
add/drop exists, but only as an approval-gated two-step (propose, then
approve — see below); there are no trade endpoints.

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

## Onboard with your ESPN login (no DevTools)

The easy path — no cookies to extract:

1. Open the connect page: **https://cozycommons.dev/fantasy/connect**
2. On the **Automatic lineups** form, enter your ESPN email and password,
   tick "Set my lineup automatically every day" if you want daily lineups,
   and hit **Connect ESPN**.
3. If you're in more than one basketball league, pick yours from the list.
4. Save the `cce_...` token it shows you — like the cookie flow, it's
   **shown once**.

Your password travels once, over HTTPS, straight to the backend, which
uses it for a single MyDisney login and then discards it. It is never
stored or logged; the only secret kept is the pair of ESPN session
cookies the login returns, encrypted at rest exactly like the cookie
flow. The form answers with your league name and your team name, so you
can confirm it connected the right team before you close the page.

If ESPN demands extra verification for your account (a CAPTCHA or a
code), the form can't complete that step — it will say so, and the
cookie flow below is the fallback.

The same flow is available as an API call:

```bash
curl -s -X POST https://api.cozycommons.dev/espn/onboard/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"...","enable_automation":true}'
# one league  -> {"id":"...","label":"...","league_id":1234567,"season":2027,
#                 "token":"cce_...","lineup_automation_enabled":true,
#                 "league_name":"...","team_name":"...","team_id":1}
# many leagues -> {"status":"league_selection_required","season":2027,
#                  "leagues":[{"league_id":...,"name":"...","team_name":"..."}]}
#                 -> re-submit with "league_id": <the chosen one>
```

`league_id` and `season` are optional: omit `league_id` and the backend
discovers your basketball leagues (season defaults to the current one —
the ending year, rolling over July 1). Error outcomes are stable detail
codes: `invalid_credentials` (401), `account_not_found` (404),
`challenge_required` (403), `no_league_found` (400),
`league_discovery_failed` / `disney_unavailable` (502). The endpoint
shares the cookie flow's rate limit: 10 attempts per IP per hour — and it
attempts the Disney login exactly once per call, because repeated failed
logins can lock an ESPN account.

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

## Roster edits (approval-gated add/drop)

Changing who is ON the roster is a bigger deal than setting a lineup, so
it never happens in one call. `POST /espn/roster/edits` with
`{"add_player_id": ..., "drop_player_id": ...}` (either id may be
omitted for an add-only or drop-only edit) validates the edit against the
live league — the add target is a free agent, the drop target is on your
own roster, the post-edit roster is legal — and stores it as a pending
edit (30-minute expiry) with a human-readable preview. Nothing is
submitted to ESPN. `POST /espn/roster/edits/{id}/approve` then executes
that exact edit as ONE ESPN transaction and records the outcome on the
edit: `executed`, `waiver_pending` (the add target was on waivers, so the
approval filed a waiver claim at bid 0 — no FAAB support), or `failed`
with ESPN's error. Approving twice, or after expiry, is rejected and
never double-submits. Edits are per-account: your token only ever sees
your own. Migration `0014_beli_espn_roster_edits.sql` adds the audit
table through the normal release step.

## Public predictions

A publisher can upload a daily `public-v2` JSON snapshot (`public-v1` remains accepted) with
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

`GET /espn/claims/links` returns ESPN links for the signed-in user's claimed
team in the latest season: `team`, `lineup`, `free_agents`, and `matchups`
(boxscore links keyed by each current matchup's home team ID). It needs Cozy
auth (401) and a confirmed claim (403 `claim_required`), and is never cached
(`Cache-Control: private, no-store`). The league ID comes from the season's service-only `fantasy_leagues` row,
cached for 30 seconds; it never appears in snapshots or public responses.
A missing setting returns 404
`league_links_unavailable` and the page hides those links. Player links on
`/fantasy` use public ESPN player pages and need no league ID.

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
| `POST /espn/roster/edits` | Propose a roster add/drop (validates + persists a pending edit; submits nothing) |
| `POST /espn/roster/edits/{id}/approve` | Approve + execute one pending edit as a single transaction |
| `GET /espn/roster/edits` | Past roster edits + their outcomes (audit trail) |
| `GET /espn/roster/edits/{id}` | One roster edit |

The same operations are available as MCP tools at `/espn/mcp` — pass your
token as the `api_token` argument.

Observed-day players may carry an optional `acquired` field: `{"how":"draft","round":11,"pick":130}`, `{"how":"add"}`, `{"how":"trade"}`, or null. The fantasy page uses it to tag this week's outperformers (players furthest above their expected points on finished days).

ESPN link UI captures use the synthetic public-v2 fixture:
[390px phone](images/espn-links/phone-390.png) ·
[1440px desktop](images/espn-links/desktop-1440.png).

## Fantasy admin

Sign in with a Cozy admin account at `/fantasy`, open **Admin**, select the
ending season year, paste the **ESPN league ID**, and choose **Save**.
**Open league** verifies the league on ESPN. The existing Dice admin allowlist
controls access; user-editable profile metadata grants no privileges.

`GET /espn/admin` checks administrator access. Admin-only
`GET /espn/admin/leagues/{season}` reads the setting; `PUT` saves
`{"espn_league_id":"<digits>"}` (1–12 ASCII digits). Responses are private
and not cached. Saving invalidates the local links cache; other workers
refresh within 30 seconds. The old league ID environment variable is unused.

Migration `0012_beli_fantasy_leagues.sql` advances the Beli contract to 12
through `python -m release` on deploy. Do not apply it from a branch.
The table has RLS and no anon/authenticated privileges or policies; only the
backend service role can select, insert, or update. No additional services
or extensions are needed.

Admin UI captures use synthetic settings:
[390px admin](images/fantasy-admin/admin-390.png) ·
[1440px admin](images/fantasy-admin/admin-1440.png) ·
[390px member](images/fantasy-admin/member-390.png).
