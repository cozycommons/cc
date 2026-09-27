# Beli skill — restaurant recs + Want to Try bookmarks (Cozy Commons)

You are a friend's personal food agent. This skill lets you answer "where
should we eat in <neighborhood>?" from their own Beli bookmarks plus Beli
trending, and save restaurants to their Beli "Want to Try" list.

## Setup (do this once)

You need two values, kept as secrets, never pasted into a public chat:

- `BELI_API_URL` — the deployed Cozy Commons backend URL (ask the user; it
  looks like `https://api.cozycommons.example.com`). All paths below are
  relative to it.
- `BELI_API_TOKEN` — the user's personal token. If they don't have one yet,
  walk them through onboarding (below), then store the returned token.

## Onboarding a new user

The user creates their account by sending ONE request with their Beli login
(Beli email or phone number like `+15551234567`, plus their Beli password):

```
POST {BELI_API_URL}/beli/onboard
Content-Type: application/json

{"label": "my beli", "beli_id": "<email or phone>", "password": "<password>"}
```

The response contains `token` — **shown once, never retrievable**. Have the
user save it in their secrets (or yours, as `BELI_API_TOKEN`). Verify with
`GET {BELI_API_URL}/beli/me` using the token.

Security notes: the password is only used to validate the Beli login, then
encrypted server-side. Never log the token or password. Every token resolves
to exactly one Beli account.

## Auth

All other endpoints: `Authorization: Bearer {BELI_API_TOKEN}`.

## Get recommendations

```
GET {BELI_API_URL}/beli/recs?neighborhood=Greenwich%20Village&day=Saturday&time=7pm&table_size=2&limit=10
```

- `neighborhood` (required): e.g. "Greenwich Village", "Williamsburg".
- `day` (optional): `YYYY-MM-DD` or a day name; defaults to today.
- `time` (optional): "19:00" / "7pm" — used for open-at-time status and slots.
- `table_size`, `limit` (optional): defaults 2 and 10.

Results: `recs[]`, each with `name`, `source` (`bookmark` = their own saved
spots ranked by their Beli scores, then `trending`), `hours_today`,
`open_at_time`, `cuisines`, `price`, and `reservation` (`has_links`,
`platforms`, `slots`). Hours/slots are best-effort — never promise a table.

## Bookmark a restaurant (Want to Try)

```
POST {BELI_API_URL}/beli/bookmark
Content-Type: application/json

{"name": "Table Mercato", "city": "New York, NY", "dry_run": true}
```

- `dry_run: true` resolves the match WITHOUT writing — use it first when
  unsure.
- Statuses: `bookmarked` | `already_bookmarked` | `already_ranked` |
  `would_bookmark` (dry run) | `ambiguous` (no write; `candidates` listed) |
  `no_results`.
- Only an exact/near-exact name match writes. If the status is `ambiguous`,
  ask the user which candidate they meant instead of guessing.

## @beli_eats watcher

Users can opt into automatic bookmarking of restaurants posted by
`@beli_eats`: `POST {BELI_API_URL}/beli/watcher-opt-in?enabled=true`
(`false` to opt out). Same confidence gate applies.

## Per-agent integration

There is no agent-specific setup — every agent uses the same generic paths:

- **ChatGPT:** create a Custom GPT → Actions → import
  `{BELI_API_URL}/openapi.json`, set authentication to Bearer with the user's
  token.
- **Claude (web/desktop) and other MCP clients:** add an MCP integration for
  `{BELI_API_URL}/beli/mcp`. Tools `get_recs` and `bookmark_restaurant` take
  `api_token` as a parameter (the user's personal token).
- **Any HTTP-capable agent (including Muse/Claude Code):** use the REST
  endpoints above directly with `Authorization: Bearer <token>`.
