---
name: cozy-commons
description: Use the Cozy Commons remote MCP connector to discover and enable projects, read trip balances, split expenses, record repayments, and get and save Beli restaurants, with confirmed previews.
---

# Cozy Commons connector

Connect to `https://api.cozycommons.dev/mcp` using Streamable HTTP and OAuth
(dynamic client registration + PKCE). Human setup: https://cozycommons.dev/connect.
Google sign-in and consent determine access; do not request pasted API keys.

Call `list_projects` first. Each project shows whether it is enabled for this
user, its tools and the exact `next_step`; follow it. Your tool list contains
only the enabled projects' tools. To use a project that is off, call
`enable_project(project_id)` (ask the user first if they did not ask for that
project). It returns the project's tools and any one-time link step. If the new
tools do not appear in your tool list, refresh it; if your client cannot, ask
the user to reconnect the connector. `disable_project` hides a project's tools
and keeps its data. Trips, Floor Planner and Beli are on this connector; other
projects may direct you elsewhere. Use `whoami` to check the signed-in identity.

## Beli

Beli needs a one-time link. Until then every Beli tool returns the link step.
Ask the user for their existing `ccb_` Beli token and call
`link_beli_account(api_token)` once. The token proves ownership. It is never
stored or returned, and you must not keep it or ask for it again. If the user
has no token, they onboard at `POST https://api.cozycommons.dev/beli/onboard`
(see the step text). If the error says the account is linked to another Commons
user, the user must sign in as that user; do not retry other tokens.

- `get_restaurant_recs(neighborhood, day?, time?, table_size, limit)`: `day` is
  `YYYY-MM-DD` or a lowercase weekday, `time` is 24-hour `HH:MM`.
- `save_restaurant(name, idempotency_key, city?, dry_run)`: preview with
  `dry_run=true`, show the matched place, and commit with the same key after
  the user confirms. `ambiguous` returns candidates and saves nothing: ask the
  user, then preview the refined name. `already_bookmarked` and `already_ranked`
  mean no change was needed.

## Rules

- Call `get_trip_overview()` to find a trip, then
  `get_trip_overview(trip_id=...)` for exact trip/member IDs and currency.
  Never guess IDs or silently resolve ambiguous names. Use returned IDs verbatim.
- Amounts are integer cents in the trip's currency; no currency conversion.
  Payer amounts must sum to `total_cents`. List participants exactly once.
- Always call writes with `dry_run=true` first. Show the user the returned
  per-person preview (payers, shares and resulting balances), then wait for their
  explicit confirmation. Commit the same arguments with `dry_run=false`.
  A changed split needs another preview and confirmation.
- Generate one unique `idempotency_key` per intended write; use the same key for
  preview, commit and retries. Never generate a fresh key merely because a call
  timed out. New intended writes require new keys; keys are per project and
  cover all trips and write kinds for the signed-in user.
- Read error messages: they name the fix. Use suggested exact IDs only after
  resolving ambiguity with the user. After a repeated revision conflict, reread
  the trip and review a fresh preview before retrying.
- "Not enabled" errors name the fix: call `enable_project` as stated.
- Permission errors mean the user must reconnect and approve the named scope
  (`commons:read` / `commons:edit`). A connection approved before these scopes
  works only for Trips and Floor Planner; for other projects the error asks the
  user to reconnect once. Do not retry with guessed credentials or another
  endpoint.
- `record_repayment` records money already paid. Venmo settlement links do not
  send money; do not claim a payment happened from opening a link.

## Worked examples

These are templates: replace `TRIP_UUID`, `A_ID`, `B_ID`, `C_ID` with exact IDs
returned by overview. Replace each example key with a newly generated UUID for
that intended operation. Confirm receipt total, currency, payer and participants
with the user when unclear.

**Even receipt:** A paid $60 USD for A, B and C. Call `add_expense`:

```json
{"trip_id":"TRIP_UUID","description":"Dinner receipt","total_cents":6000,"payers":[{"member_id":"A_ID","amount_cents":6000}],"member_ids":["A_ID","B_ID","C_ID"],"split_mode":"even","idempotency_key":"EVEN_WRITE_UUID","dry_run":true}
```

Show the returned preview: each share is 2000 cents. After confirmation, repeat
with the same key and arguments, changing only `dry_run` to `false`.

**Percent receipt:** For a separate $60 receipt paid by A, A takes 50%, B 30%,
C 20%. Use the same shape with a new key, `split_mode: "percent"` and
`parts: {"A_ID":5000,"B_ID":3000,"C_ID":2000}`. Parts are positive integer
basis points totaling 10000, not percentages or cents. Preview shares are 3000,
1800 and 1200 cents. Show actual returned results before confirming/committing.

**Exact receipt:** For another $60 receipt paid by A, use a new key,
`split_mode: "exact"` and `parts: {"A_ID":2500,"B_ID":2000,"C_ID":1500}`.
Parts are nonnegative integer cents totaling 6000. Preview, show each person's
share and resulting balance, confirm, then commit with that same key.
Even remainder pennies follow trip member order; percent rounding uses largest
remainders with ties in trip member order. Trust the returned preview.

**Venmo repayment:** The user says B already Venmoed A $20 USD. Verify the trip,
identities, direction and that the payment occurred, then call:

```json
{"trip_id":"TRIP_UUID","from_member_id":"B_ID","to_member_id":"A_ID","amount_cents":2000,"idempotency_key":"REPAYMENT_WRITE_UUID","dry_run":true}
```

Show the returned per-person balance changes. On confirmation, call
`record_repayment` again with the same arguments and key, `dry_run=false`.
This records the repayment; it does not initiate a Venmo payment.
