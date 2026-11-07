# Security

Cozy Commons stores other services' passwords, cookies and session tokens
(Beli, Resy, ESPN, Partiful) and acts as its users there. Treat every change
that touches that path as security-critical.

Read this before changing credential storage or entry, account linking, auth or
OAuth, agent tools, SQL functions, grants or migrations, dependencies or
lockfiles, CI workflows, the frontend CSP, background jobs, or any outbound
network call.

## What we defend against

- **A rogue dependency in the API process.** It can read every environment
  variable (the `*_CREDENTIALS_KEY`s, `SUPABASE_SERVICE_KEY`) and patch any
  module. Today the only defense is keeping it out (hash locks, the seven-day
  cooldown); there is no outbound allowlist yet, so it could reach any host.
- **One Commons user acting as another on a third-party service**, through
  account matching, a race, or a partial write.
- **Secrets leaking** into responses, error bodies, logs, agent transcripts or
  exception text.
- **Agents as a leak path.** Agent chats are stored and replayed; a secret typed
  there is a secret disclosed.

Accepted for now: the API holds both the database and the keys, one key per
service covers every user, and rate limits live in one worker's memory. Revisit
a separate credential broker before Commons serves users beyond friends, or
before a provider holds payment methods.

## Credentials

- Users enter third-party credentials only on `/account`, which loads as its
  own document under the strict CSP (`frontend/csp.js` `documentKind`,
  `docs/frontend-csp.md`). Credential forms call only `${api}/account/...`.
  Agents send users to `cozycommons.dev/account#<service>` and never ask for a
  password, cookie, code or token.
- New agent capabilities go on `/mcp` (`backend/cc_mcp`), where the user is the
  OAuth session. Never add a tool that takes a token as a parameter. The
  `/<project>/mcp` servers take `api_token` per call and are legacy; a token
  that reaches an agent transcript counts as leaked and gets retired.
- On `/mcp`, a tool is callable only if `ProjectAccessMiddleware` registers it
  and `check_access` passes on every call. Hiding a tool from the list is not
  authorization; write tools need `commons:edit` and a linked account.
- Encrypt every stored secret with the project's key through
  `backend/credential_keys.py`. Agent OAuth state stays encrypted under
  `CC_MCP_STORAGE_ENCRYPTION_KEY`. Never log, return or embed a secret in an
  exception message, and never present the agent-supplied `client_name` as
  verified (show `redirect_host` beside it).
- Prove ownership with the third-party login itself. Identifiers are printable
  ASCII and only ASCII is case-folded (see `login_key`). Match phone numbers by
  digits.
- Insert a new row unowned, link it through the project's `*_link_account`
  RPC, and refresh an existing row's secrets only after the link, filtered by
  `.eq("owner_user_id", caller)`. When a link also rewrites credentials, tokens
  or settings, do all of it in one RPC, as ESPN's `espn_claim_account_proven`
  does. Beli, Resy and Partiful still refresh in a second write; fold that into
  their RPC when next touched.
- A write to an existing row must be conditional on the state the request
  read. Never acquire an unowned row as a side effect of refreshing one.
- A weaker proof never displaces a stronger one; a proven claim can take over
  an unproven one. Takeover retires the old token and expires everything the
  previous holder left pending.
- One-time codes are bound to the Commons user and the normalized phone,
  expire, and are consumed the moment the provider accepts them; the lock is
  never held across the provider call (`reserve_partiful_challenge`).
- Rate-limit credential and token attempts per Commons user and per
  third-party identifier.
- Request validation errors never echo input: `backend/request_validation.py`
  is installed app-wide. Check secret lengths in the route rather than with
  pydantic constraints.
- Never read a credential or token through `CachedSupabaseClient`
  (`app.state.supabase`); a retired token must stop working on the next
  request.
- Rotate a `*_CREDENTIALS_KEY` only by prepending the new key, deploying,
  running `python -m scripts.rotate_credentials`, then removing the old key
  (`docs/deployment.md#credential-key-rotation`).

## Data access, logging and background jobs

- Every backend Supabase client uses the service role, so row-level security
  does not protect anything from the API. Every query returning a user's data
  filters by the caller's id in the API. A new table still gets `enable row
  level security` and `revoke all ... from public, anon, authenticated`, so the
  anon key the frontend ships cannot read it.
- Log identifiers (row ids, HTTP status, hostnames), never request bodies,
  cookies, `Authorization` headers or third-party error bodies; a provider's
  error text can contain the credential that was sent.
- Background jobs (the Instagram watcher, ESPN lineup automation) load only the
  rows they are about to act on, never log decrypted values, and stop acting for
  a row once its owner changes or its token is retired.
- The admin SQL tool runs as `commons_analytics_reader` over `analytics.*`
  views (`backend/admin/query.py`). Exposing a new view, function, type or
  operator there is a security change and must not reach a table holding
  `*_enc`, `token_hash` or OAuth state.
- `CORS_EXTRA_ORIGINS` is combined with credentialed CORS: add only Commons
  frontends, never a wildcard. `/revoke` allowing any origin is the one
  deliberate exception (RFC 7009 public clients).

## SQL

- Functions are `security invoker`, `set search_path = ''`, revoked from
  `public, anon, authenticated`, and executable by `service_role` only.
- Grant explicitly every privilege a function relies on, and check it in the
  project's `backend/migrations/*_schema_contract.sql`; do not rely on Supabase
  default privileges.
- Lock every row a function will change in one id-ordered `for update` before
  branching. Validate parameters (no NULL user ids, no empty secrets).
- Never edit a migration that has been applied anywhere, including the shared
  local stack; add the next number. Page credential and token tables by id,
  never by offset.

## Supply chain and CI

- Every Python install uses a hash-locked file with
  `--require-hashes --only-binary=:all:`. Change dependencies in the `.in`
  file, regenerate with `scripts/lock-backend-requirements.sh`, and read the
  lockfile diff for unfamiliar package names.
- Bump `uv-exclude-newer` only to a date at least seven days old. Take a
  younger release only as a reviewed security exception.
- Pin actions by commit SHA.
- Dependabot, secret scanning with push protection, and CodeQL (extended suite)
  are enabled on the repository. Fix their findings; never dismiss one without a
  written reason.

## Review before merge

For changes in the scope above, an adversarial review before merge is
recommended, best effort, not a merge requirement. When you do one:

1. Use a reviewer other than the author, a person or a separate agent session
   on any model, and ask them to try to break the change.
2. Give the reviewer the diff, what earlier passes already found, and the
   attack surfaces to probe. Ask for blocking versus hardening findings.
3. Verify a disputed finding by reproducing it before acting, and fix blocking
   findings as new commits.
4. Note the review and its fixes in the PR description. A finding in merged
   code ships as its own fix PR.

Contributors may hold their own work to a stricter personal bar, such as
multiple reviewers or a specific model; that bar is theirs, not the repository's.
