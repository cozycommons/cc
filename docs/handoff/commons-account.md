# M4 plan: Commons account page at `/account`

Status: PR 1 (profile table and backfill) built on `commons-account-profile`; PRs 2 to 5 are plan only.

Owner direction: connector auth and connectors get a home in the UI, managed at
the profile level. The Dice profile identity becomes the Commons identity for
every project. Profiles will gain more attributes and access-control pieces.

## What exists today

Identity is spread across three stores, and each project picks its own fallback
order.

| Field | Where it lives | Writers | Readers |
| --- | --- | --- | --- |
| Display name | `dice_profiles.display_name` (`0025`), created lazily by `GET /dice/me` from Google `full_name` | `PUT /dice/me` (`backend/dice/routes.py:812`, `repository.update_profile`) | Dice everywhere (~28 sites in `dice/repository.py`, `routes.py:338` live games, SQL in dice migrations 0053, 0054, 0064, 0068, 0075, 0079: rating snapshots, duo replay); `trips/profiles.py:profile_map` and `trips/matching.py:125`; `espn/team_claims.py:102,157`; `dice/virtual_currency.py:28`; connector `whoami` (`cc_mcp/commons_tools.py`, via `trips.profiles.current_profile`) |
| Fallback name | `auth.users.raw_user_meta_data.full_name` / `name` (Google rewrites it at sign-in) | Supabase Auth | Trips (`account_profile`), ESPN `_user_names`, Crowdset (`crowdset/hosting.py:66`), admin users list (`commons_accounts` view, `0085`), `TripsApp.jsx:126,164` |
| Avatar | `dice_profiles.avatar_url`; upload to the `dice-profile-photos` bucket under `<uid>/` (`PlayerProfile.jsx:18`, `supabase/dice-local-grants.sql`) | `PUT /dice/me` | Dice, Trips, ESPN claims (https only), live games |
| Venmo handle | `auth.users.raw_user_meta_data.venmo_username` + `venmo_username_provenance` | `PUT /trips/me` (`trips/routes.py:242`) via `auth.admin.update_user_by_id` | Trips (`trips/venmo.py:account_venmo`, `profiles.py`, `matching.py`, `agent_tools.py`) |
| Phone, SMS opt-in | `dice_profiles.phone_number`, `sms_notifications_enabled` | `PUT /dice/me` | Dice only; owner and admins (`_without_contact`) |
| Anonymous play | `dice_profiles.is_anonymous` (`0086`) | `PUT /dice/me` from `/dice/settings` | Dice API only (`dice/anonymity.py`) |
| Role | `commons_user_roles` (`0085_dice_commons_roles.sql`) | `commons_set_role` RPC from `/admin` Users | `commons_roles.user_role`: Dice, Trips, admin |

Corrections to the brief, verified in source:

- `dice_profiles` is **not** publicly readable any more. `0086` revoked
  `select` from `anon` and `authenticated`; every read goes through the API,
  which applies anonymity. `GET /dice/profiles/search` is still unauthenticated
  and returns every Dice profile's name and avatar.
- `venmo_profiles` (`0081`) is not per user. It is a server-side cache of
  public Venmo page lookups keyed by handle (`venmo/profiles.py:114`). The
  user's own handle is in Auth user metadata, which the user can also overwrite
  from the browser with `supabase.auth.updateUser`. That is harmless today
  (it is self-attestation and grants nothing) but it is not a store we control.
- There is no Resy owner link on `main`. It is in open PR #201
  (`0018_beli_resy_account_owner.sql`, `resy/accounts.py`), same shape as Beli
  `0017_beli_account_owner.sql`. Neither has an unlink.

Connector state (`backend/cc_mcp/`):

- `cc_mcp_oauth_state` (`0001`) is FastMCP's key/value store, Fernet-encrypted
  values, keyed by `(collection, key)`. Collections (fastmcp 2.14.7
  `oauth_proxy.py:835-890`): `mcp-oauth-proxy-clients` (DCR clients, with a
  self-reported `client_name`), `mcp-upstream-tokens` (the Supabase tokens),
  `mcp-jti-mappings`, `mcp-refresh-tokens`, transactions and codes.
- There is no user column anywhere. The user is only inside the encrypted
  upstream Supabase access token (`sub`). Listing a user's grants from current
  storage means decrypting every upstream token row. Feasible at our scale but
  not something to run per page view.
- `UpstreamTokenSet.upstream_token_id` is stable across refreshes
  (`oauth_proxy.py:1537` re-puts the same key). It identifies one connection
  (one approval, its refresh family). `ResourceBoundOAuthProxy._revoke_proxy_token_set`
  already deletes it, and `load_access_token` returns `None` as soon as it is
  gone (`oauth_proxy.py:1658`), so every access and refresh token of that
  connection stops working on the next request. Server-side disconnect is
  feasible with today's code.
- All agents share one upstream Supabase OAuth client
  (`CC_MCP_OAUTH_CLIENT_ID`). The Supabase consent covers the proxy, not an
  individual agent. Disconnecting one agent must not touch it.
- `cc_mcp_project_settings` (`0002`) holds explicit per-user enable choices;
  `ProjectAccessMiddleware` re-reads it on every `tools/list` and `tools/call`.

Frontend: `SiteHeader.jsx` renders an `Account` disclosure with one link,
"Connect your agent". It shows whether or not anyone is signed in.
`/connect` (`connect/Connect.jsx:84`) says there is no in-app revocation page.
`/oauth/consent` uses `supabase.auth.oauth.*` from supabase-js 2.78.0, which
has no grant-listing API.

## 1. Data model

### Recommendation: a new `commons_profiles` table; `dice_profiles` keeps its job

Promoting `dice_profiles` to the Commons profile fails on concrete behavior:

- Every Commons user would need a Dice row. `list_elo_leaderboard` with
  provisional players selects every row with `ranked_games_played < threshold`
  (`dice/repository.py:278`), and `/dice/profiles/search` returns every row. A
  Trips-only user would appear on the Dice leaderboard and in Dice player
  pickers. Filtering that out touches the rating code that AGENTS.md says to
  keep stable.
- The table is mostly Dice state (ELO, rating deviation, model version, win
  counts, phone, SMS). It is the FK target of `dice_game_players` and anchors
  the dice schema contract and readiness. Renaming it or widening its grants
  means rewriting readiness for a table the release gate already pins.

A new table holds only cross-project identity. Dice keeps everything else.

```sql
-- backend/migrations/0087_dice_commons_profiles.sql (dice family, contract 87)
create table public.commons_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (length(btrim(display_name)) between 1 and 80),
  avatar_url text check (avatar_url is null or length(avatar_url) <= 2048),
  venmo_username text check (venmo_username is null or venmo_username = lower(venmo_username)),
  venmo_owner_confirmed boolean not null default false,
  venmo_confirmed_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- RLS on, browser roles revoked, service_role select/insert/update/delete,
-- and the table added to the dice readiness function and dice_schema_contract.sql.
```

Why the dice family: it follows `0085_dice_commons_roles.sql`, and the backfill
and mirror trigger must run in the same transaction as `dice_profiles`. A new
`commons_account` family would need runner, contract-script and CI changes for
no behavioral gain. The retired `commons` family is off limits (its README).

**Extensible attributes.** New attributes are typed columns added by forward
migrations, not a `jsonb` bag. Each field has a validator and a visibility, and
a bag loses both. Visibility lives in one code registry so readers cannot drift:

```python
# backend/commons_account/profile.py
FIELDS = {
    'display_name': 'public',       # anyone who sees you in any project
    'avatar_url': 'public',
    'venmo_username': 'shared',     # people who share a trip with you
    'venmo_owner_confirmed': 'shared',
    'venmo_confirmed_name': 'shared',
}
def public_profiles(client, user_ids) -> dict[str, dict]: ...
def shared_profiles(client, user_ids) -> dict[str, dict]: ...  # caller proves the relationship
def own_profile(client, user) -> dict: ...                      # ensures the row exists
```

Email stays in Supabase Auth and shows read-only. Phone and SMS stay in
`dice_profiles` (Dice-only, owner and admin) for M4.

### Backfill

In `0087`, one row per non-anonymous `auth.users` row:

- `display_name = coalesce(dice_profiles.display_name, meta.full_name, meta.name, split_part(email,'@',1), 'Friend')`, trimmed to 80.
  Dice first, matching `trips/profiles.py:current_profile` today.
- `avatar_url = coalesce(dice_profiles.avatar_url, meta.avatar_url)`.
- Venmo fields from `meta.venmo_username` / `venmo_username_provenance`, using
  the same rules as `trips/venmo.py:account_venmo` (confirmed only when
  `owner_confirmed` is true and the provenance handle, when present, matches).

The migration does not modify `auth.users` metadata or `dice_profiles`.
Users created later get a row from `own_profile` (called by `GET /account`,
`GET /dice/me` and `GET /trips/me`). Readers keep their existing Auth-metadata
fallback for users who have no row yet, so a missing row changes nothing.

### Keeping Dice and `/dice` stable: a one-way mirror

`commons_profiles` is the source of truth for name and avatar.
`dice_profiles.display_name` and `avatar_url` become a read-only copy:

- Trigger `commons_profiles_mirror_dice` (after update of `display_name`,
  `avatar_url`) updates the matching `dice_profiles` row if one exists.
- `dice.repository.update_profile` writes name and avatar to `commons_profiles`
  (the trigger mirrors them) and everything else to `dice_profiles`, in that
  order. `get_or_create_profile` takes its defaults from `own_profile`.
- `PUT /dice/me`, `/dice/settings` and every Dice reader, RPC and SQL snapshot
  are unchanged. The dice SQL functions that read `dice_profiles.display_name`
  (0053, 0054, 0064, 0068, 0075, 0079) keep working because the column keeps its value.
- Writes go through `app.state.supabase` (the cached client), so the per-worker
  query cache is cleared as it is for Dice edits today.

Mirroring is cheaper than moving every Dice reader to a join and does not touch
rating code. A later PR can retire the copy once readers move; not in M4.

### As built in PR 1

Where `0087` and `commons_account/profile.py` refine the sketch above:

- `venmo_username` must match `^[a-z0-9_-]{5,30}$` (the lowercased output of
  `venmo.usernames.normalize_username`), not only `= lower(...)`. The backfill
  applies `stored_username`'s URL/`@` stripping in SQL; invalid handles become null.
- The backfill skips a blank Dice name and a Dice avatar over 2048 characters
  (Dice has no cap) and falls through to the next source instead of failing.
- The mirror copies only the column that changed and bumps
  `dice_profiles.updated_at`. A Venmo-only edit leaves the Dice row alone.
- `dice_release_readiness()` keeps its name: the 0084 body is renamed to
  `dice_schema_0084_readiness()` and the entry point now also calls
  `commons_profiles_readiness()` (the `cc_mcp` 0002 pattern).
- `own_profile` refuses Supabase anonymous sessions. `default_profile` is the
  Python twin of the backfill; the DB test asserts they agree per user.
- Dice players with no Dice avatar get their Google avatar in
  `commons_profiles`. Nothing reads it until PR 2, which decides whether Trips
  and the connector show it.

### Public, private and anonymous

- Name and avatar are public in practice already (`/dice/profiles/search` is
  unauthenticated). The account page says so next to the fields.
- Venmo is `shared`: Trips shows it only to co-members (`render_groups`). Moving
  it off Auth metadata makes the server the only writer.
- Anonymous play stays a **Dice** setting in `dice_profiles.is_anonymous`. Its
  meaning is Dice-specific (aliasing recorded results; pickers and live games
  still show real names), and `dice/anonymity.py` already nulls `avatar_url` in
  aliased output, whatever the avatar's source. The account page shows it under
  Dice privacy and writes through the existing `PUT /dice/me {is_anonymous}`.
  There is no Commons-wide anonymous mode in M4. If later projects want one,
  each gets its own per-project privacy row, because "anonymous" means
  different things per project.

## 2. Connected agents

### Storage: an index table beside the encrypted store

```sql
-- backend/cc_mcp/migrations/0003_cc_mcp_connections.sql (contract 3)
create table public.cc_mcp_connections (
  id uuid primary key default gen_random_uuid(),     -- the only id the API exposes
  upstream_token_id text not null unique,             -- FastMCP connection key
  user_id uuid not null references auth.users(id) on delete cascade,
  client_id text not null,
  client_name text,                                   -- DCR self-reported, display only
  redirect_host text,                                 -- e.g. claude.ai, from the client's redirect URI
  scopes text[] not null,
  approved_at timestamptz not null,
  last_used_at timestamptz,
  expires_at timestamptz,                             -- refresh family end
  revoked_at timestamptz
);
create index on public.cc_mcp_connections (user_id) where revoked_at is null;
-- RLS, browser revokes, service grants, readiness folded into cc_mcp_release_readiness().
-- RPC cc_mcp_touch_connection(...): insert ... on conflict (upstream_token_id)
-- do update set last_used_at = excluded.last_used_at, expires_at = ...;
-- never overwrites approved_at or revoked_at.
```

Writes, all in `ResourceBoundOAuthProxy` (`cc_mcp/server.py`):

- **Approve.** Override `exchange_authorization_code`: after `super()`, resolve
  the issued access token's JTI mapping to `upstream_token_id`, take `sub` from
  the verified upstream token, and insert the row (client name and redirect
  host from the DCR client record, truncated to 80 chars).
- **Use.** In `load_access_token`, after a successful load, call the touch RPC
  at most once per connection per 5 minutes per worker (in-process timestamp
  map). Best effort: a failed touch is logged and never fails auth. This also
  lazily indexes connections approved before M4, so any connection in use shows
  up after its next call; unused ones expire within 30 days.
- **Refresh.** Override `exchange_refresh_token` to update `expires_at`.
- **Client revoke.** `revoke_token` (the `/revoke` endpoint) sets `revoked_at`
  when it removes a refresh family.

`last_used_at` is accurate to about 5 minutes; the UI shows "today",
"3 days ago" and so on.

### Disconnect

`DELETE /account/connections/{id}`:

1. Load the row by `id` and `user_id = caller`, else 404 (no existence leak).
2. `await oauth._revoke_proxy_token_set(upstream_token_id)` (exists today).
   From the next request every token of that connection fails to load.
3. Set `revoked_at`. Repeating the call is a no-op 204.

Order matters: delete first, then mark, so a failure never shows
"disconnected" while tokens still work. The DCR client record and the Supabase
consent stay; the agent can reconnect through the consent screen.

The account router reaches the proxy through
`app.state.cc_mcp_oauth = cc_mcp_app.state.cc_mcp_oauth` set in `main.py`
after `create_agent_app`. When the connector is unconfigured
(`unavailable_agent_app`), the connections endpoints return 503 and the page
says agent connections are unavailable.

To verify in the PR, not assumed: whether the upstream Supabase session behind
the OAuth grant should also be signed out (`POST /auth/v1/logout?scope=local`
with the upstream access token). Deleting our only copy of the upstream refresh
token already makes it unusable, so this is defense in depth, not a requirement.

## 3. Projects and linked accounts

Shared logic, not a second copy:

- `cc_mcp/commons_tools.py:project_listing` already returns structured project
  state. The web API calls it and drops the agent-phrased `next_step` text; the
  UI writes its own copy from `enabled`, `enabled_reason`, `linked`, `account`.
- `projects.set_enabled` raises `ToolError`. Move the failure to a neutral
  `ProjectSettingsUnavailable` in `cc_mcp/projects.py`; the MCP tools map it to
  `ToolError`, the web API to 503. Same table, same default rule (no row means
  `in_use`), so a web toggle and `enable_project` are the same write.
- Add `unlink: Callable[[client, user], bool] | None` to `AccountLink`
  (`cc_mcp/server.py`). Beli: `update beli_accounts set owner_user_id = null
  where owner_user_id = :user`. One statement, so no RPC and no migration. Resy
  gets the same in #201 or right after it. Unlink keeps the account row, its
  `ccb_`/`ccr_` token, receipts, `/beli/*` and watcher subscriptions, and keeps
  the project's enable choice; the project's tools then return the link step.
- No `unlink_*` MCP tool in M4: unlinking is an account decision made on the
  page. Linking stays where it is (`link_beli_account`, the Resy link tool).

Agents learn about web toggles on their next `tools/list`. There is no stream
to push `list_changed` from a web request (stateless HTTP), so the page says
"Your agent sees this change after it refreshes its tools."

## 4. Roles and access

- M4 shows the role read-only: "Member" or "Admin", with a link to `/admin` for
  admins. Roles stay in `commons_user_roles` and change only through
  `commons_set_role`. The account page never edits roles, and nothing on the
  profile grants permission (PRODUCT.md rule 5 holds).
- Connector grants and roles stay separate. Scopes (`commons:read`,
  `commons:edit`) bound what an agent may do; roles bound what the person may
  do. No MCP tool checks `is_admin` today (grep of `*/agent_tools.py`,
  `cc_mcp/`); keep it that way: agent calls act with member powers even for
  admins. PR 4 adds a safety test for that.
- When a project needs its own role, add `commons_project_roles(user_id,
  project_id, role, assigned_by, updated_at)` with the `0085` pattern (advisory
  lock, history, expected-role check). Not in M4. The `GET /account` response
  reserves a `project_roles` list (empty) so the page layout already has a slot.

## 5. API endpoints

New router `backend/commons_account/routes.py`, `app.include_router(...,
prefix="/account")` in `backend/main.py` before `mount_agent_app` (the MCP app
is mounted at `/`, so ordering matters). Auth: the Supabase session bearer,
resolved with `client.auth.get_user(token)` like `trips/routes.py:current_user`;
Supabase anonymous users get 403. Every response gets
`Cache-Control: private, no-store` (extend the `private_admin_responses`
middleware). Request models use `extra='forbid'`.

| Method | Path | Body / result |
| --- | --- | --- |
| GET | `/account` | `{user_id, email, verified, role, project_roles: [], profile: {display_name, avatar_url, venmo_username, venmo_owner_confirmed, venmo_confirmed_name}, visibility: FIELDS, dice: {has_profile, is_anonymous}}`; creates the profile row if missing |
| PATCH | `/account/profile` | any of `display_name`, `avatar_url`, `venmo_username`, `venmo_owner_confirmed`; reuses `trips/profiles.avatar_url` and the `AccountVenmo` validator; returns the profile |
| GET | `/account/connections` | `[{id, client_name, redirect_host, scopes, approved_at, last_used_at, expires_at}]`, active only (not revoked, not expired) |
| DELETE | `/account/connections/{id}` | 204; 404 if not yours |
| GET | `/account/projects` | `[{id, name, description, url, on_connector, enabled, enabled_reason, linked, account, tool_count}]` from `project_listing` |
| PUT | `/account/projects/{project_id}` | `{enabled: bool}` → `projects.set_enabled`; 404 for unknown or catalog-only projects |
| DELETE | `/account/projects/{project_id}/link` | 204, idempotent; 404 if the project has no link |

Dice anonymity uses the existing `PUT /dice/me`. Existing `GET/PUT /trips/me`
keep their response shape and read and write `commons_profiles` underneath
(PR 2), so the Trips UI keeps working while the account page takes over
editing.

## 6. UI structure

Route `/account` in `frontend/src/App.jsx`, wrapped in `SupabaseProvider`
like `/oauth/consent`, code in `frontend/src/account/`. Signed out: one Google
sign-in button. Header: `SiteHeader product="Account" to="/account"`.

One page, four sections, in this order, following `docs/crowdset/DESIGN.md`
(functional copy, no taglines):

1. **Profile.** Avatar (upload through the existing `dice-profile-photos`
   bucket helper from `PlayerProfile.jsx`), display name, Venmo handle with the
   existing owner-confirmation checkbox and live Venmo preview
   (`/venmo` lookup). A one-line visibility note per field: "Shown in every
   project", "Shown to people on your trips". Email read-only.
2. **Connected agents.** One row per connection: client name, redirect host,
   "Read" or "Read and save changes", "Connected Oct 4 · Used today",
   Disconnect with a confirm naming the agent. Empty state links to `/connect`.
3. **Projects.** One row per connector project: enabled switch, link status
   ("Linked: <account summary>" or "Not linked" with the link step), Unlink with
   confirm. Catalog projects (Dice, Partiful, ESPN until M3d/M3e) show their
   URL and no switch.
4. **Privacy and access.** Dice "Play anonymously" (same confirm copy as
   `/dice/settings`), role badge, admin link.

Header: the `Account` menu gets "Account" (to `/account`) above "Connect your
agent". `/connect` replaces its Disconnect paragraph with a link to
`/account#agents`. `/dice/settings` keeps working and links to `/account` for
name and avatar.

## 7. PR split

One branch per PR, merged in order; each gets the test plan below plus the
repo's frontend and backend suites. PRs 1, 3 and 5 touch auth or identity data
and get one external review.

1. **Commons profile table and backfill** (`0087_dice_commons_profiles.sql`,
   `commons_account/profile.py`, dice contract 87).
   Tests: real-Postgres migration test (fresh and upgrade from 86) asserting
   backfill precedence on synthetic users (Dice name wins, metadata fallback,
   email fallback, Venmo confirmed only with matching provenance), browser
   roles denied, readiness tampering fails, mirror trigger updates
   `dice_profiles` and is a no-op without a Dice row. Upgrade test leaves
   `auth.users` metadata byte-identical.
2. **Readers and writers use the Commons profile.** `dice.repository.update_profile`
   and `get_or_create_profile`, `trips/profiles.py`, `trips/matching.py`,
   `trips/routes.py /me`, `espn/team_claims.py`, connector `whoami`.
   Tests: `PUT /dice/me` name change shows in Trips `render_groups`, ESPN
   claims and `whoami`; existing Dice API tests unchanged and passing; anonymous
   player stays aliased after an avatar change; `PUT /trips/me` writes
   `commons_profiles` and no longer calls `update_user_by_id`.
3. **Connection index and server-side disconnect** (`0003_cc_mcp_connections.sql`,
   proxy overrides, `commons_account` connections endpoints).
   Tests: unit (touch throttle, lazy index of a pre-M4 connection, revoke marks
   row); `tests/test_cc_mcp.py` real OAuth flow: approve → listed with client
   name; call → `last_used_at` set; disconnect → next tool call and refresh both
   fail; another user's id → 404. E2E (`scripts/commons-connector-local.sh
   test`) gains "PASS disconnect from account revokes access and refresh".
4. **Projects and unlink.** `ProjectSettingsUnavailable`, `AccountLink.unlink`,
   Beli unlink, project endpoints.
   Tests: web toggle and `enable_project` produce the same row and the same
   `tools/list`; unlink → Beli tools return the link step, legacy `ccb_` token
   still works on `/beli`, receipts kept; safety test: admin user's agent call
   gets no admin-only behavior.
5. **`/account` page and header.** `frontend/src/account/*`, `App.jsx`,
   `SiteHeader.jsx`, `/connect` copy.
   Tests: Vitest for each section (loading, empty, error, confirm dialogs,
   pending state disables controls), header link; production build; a local
   browser run against the loopback stack with synthetic users: edit name and
   see it in Dice and Trips, disconnect a real local OAuth connection, toggle
   and unlink Beli against the fake Beli API.

Resy unlink lands in #201 if it is still open, else as a follow-up commit in PR 4.

## 8. Risks and open questions for the owner

Risks:

- **Name precedence changes for some users.** Users with a Dice row already see
  the Dice name everywhere Trips looks. Users without one are backfilled from
  Google, so nothing visible changes at migration. Later, a Dice name edit
  reaches Trips, ESPN and the connector, which is the point but is new.
- **Mirror drift.** Any future code that writes `dice_profiles.display_name`
  directly bypasses the source of truth. PR 2 adds a test that only
  `commons_profiles` writes name and avatar.
- **Cache staleness.** The query cache is per worker with a 120 s TTL; other
  workers can show an old name for up to 2 minutes. Same as Dice today.
- **Client names are self-reported.** A DCR client can call itself "Claude".
  Showing the redirect host next to it is the mitigation; the page never
  claims the name is verified.
- **Pre-M4 connections** appear only after their next call. An idle one stays
  invisible until it expires (≤30 days), and the page cannot revoke it.
- **Venmo leaves Auth metadata.** After PR 2 the server ignores browser writes
  to `user_metadata.venmo_username`. Old clients still sending `PUT /trips/me`
  keep working; anything reading the metadata directly (none found outside
  `trips/`) would go stale.

Questions, with the owner's answers (2026-11-03):

1. Should a Commons admin editing another player through `PUT /dice/me
   {user_id}` rename them Commons-wide? Today it renames them in Dice. The plan
   keeps the endpoint, which makes it Commons-wide.
   **Answer: yes, an admin rename is Commons-wide.**
2. Is a display name public across all projects acceptable, given
   `/dice/profiles/search` is unauthenticated? Alternative: require sign-in on
   that endpoint, which is a Dice behavior change.
   **Answer: names stay public; `/dice/profiles/search` is unchanged.**
3. Move phone and SMS opt-in to the Commons profile now, or leave them Dice-only
   until a second project sends texts?
   **Answer: phone and SMS stay Dice-only.**
4. Crowdset (hosted separately) reads names from Auth metadata
   (`crowdset/hosting.py:66`). Switch it to `commons_profiles` in M4, or leave
   it until Crowdset's next release?
   **Answer: leave Crowdset for its next release.**
5. ESPN team claims show the real Dice name even for anonymous Dice players
   (`espn/team_claims.py:157` ignores `is_anonymous`). Intended, since anonymity
   is Dice-scoped, or should the claims list respect it?
   **Answer: claims stay as they are; anonymity is Dice-scoped.**
6. Disconnect revokes one agent. Do you also want "Disconnect all agents",
   which would also be the moment to sign out the upstream Supabase sessions?
   **Answer: no "disconnect all" in M4.**
7. Should Trips' Venmo editor move entirely to `/account`, or keep an inline
   editor in Trips that writes the same field?
   **Answer: Trips keeps its inline Venmo editor, writing the same field.**
