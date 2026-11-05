# Security

Cozy Commons stores other services' passwords, cookies and session tokens
(Beli, Resy, ESPN, Partiful) and acts as its users there. Treat every change
that touches that path as security-critical. The rules below are the bar; each
one exists because a review found the opposite in this repository.

Read this before changing credential storage or entry, account linking, auth or
OAuth, SQL functions, grants or migrations, dependencies or lockfiles, CI
workflows, the frontend CSP, or any outbound network call.

## What we defend against

- **A rogue dependency in the API process.** It can read every environment
  variable (the `*_CREDENTIALS_KEY`s, `SUPABASE_SERVICE_KEY`) and patch any
  module. Defend by keeping it out (locks, cooldown) and leaving it nowhere to
  send data (outbound allowlist).
- **One Commons user acting as another on a third-party service**, through
  account matching, a race, or a partial write.
- **Secrets leaking** into responses, error bodies, logs, agent transcripts or
  exception text.
- **Agents as a leak path.** Agent chats are stored and replayed; a secret typed
  there is a secret disclosed.

Accepted for now: the API holds both the database and the keys, one key per
service covers every user, rate limits live in one worker's memory, and the real
providers are exercised only through fakes. Revisit the separate credential
broker before Commons serves users beyond friends, or before a provider holds
payment methods.

## Credentials

- Users enter third-party credentials only on `/account`, which loads as its
  own document under the strict CSP (`frontend/csp.js` `documentKind`,
  `docs/frontend-csp.md`). Credential forms call only `${api}/account/...`.
  Agents send users to `cozycommons.dev/account#<service>` and never ask for a
  password, cookie, code or token.
- Encrypt every stored secret with the project's key through
  `backend/credential_keys.py`. Never log, return or embed a secret in an
  exception message.
- Prove ownership with the third-party login itself. Identifiers are printable
  ASCII and only ASCII is case-folded (`str.lower()` maps look-alikes such as
  the Kelvin sign onto ASCII). Match phone numbers by digits.
- Link through the project's `*_link_account` RPC first, then write secrets
  only to the caller's own row (`.eq("owner_user_id", caller)`). When a link
  also rewrites credentials, tokens or settings, do all of it in one RPC so a
  failed second write cannot leave ownership changed and credentials stale.
- A write to an existing row must be conditional on the state the request
  read. Never acquire an unowned row as a side effect of refreshing one.
- A weaker proof never displaces a stronger one; a proven claim can take over
  an unproven one. Takeover retires the old token and expires everything the
  previous holder left pending.
- One-time codes are bound to the Commons user and the normalized identifier,
  expire, are reserved under a short lock (never held across a network call),
  and are consumed as soon as the provider accepts them.
- Rate-limit credential attempts per Commons user and per third-party
  identifier.
- Request validation errors never echo input: `backend/request_validation.py`
  is installed app-wide. Check secret lengths in the route rather than with
  pydantic constraints.

## SQL

- Functions are `security invoker`, `set search_path = ''`, fully qualified,
  revoked from `public, anon, authenticated`, executable by `service_role` only.
- Grant explicitly every privilege a function relies on, and add a readiness
  contract check for it; do not rely on Supabase default privileges.
- Lock every row a function will change in one id-ordered `for update` before
  branching. Validate parameters (no NULL user ids, no empty secrets).
- Never edit a migration that has been applied anywhere, including the shared
  local stack; add the next number. Page through tables by id (keyset), never
  by offset.

## Supply chain and CI

- Every Python install uses a hash-locked file with
  `--require-hashes --only-binary=:all:`. Change dependencies in the `.in`
  file, regenerate with `scripts/lock-backend-requirements.sh`, and read the
  lockfile diff for unfamiliar package names.
- Bump `uv-exclude-newer` only to a date at least seven days old. Most
  malicious releases are found and yanked within days.
- Pin actions by commit SHA. Quote any YAML `run:` value that contains `: `,
  or the workflow silently stops parsing.
- GitHub provides, free for this public repository: Dependabot alerts and
  security PRs, secret scanning with push protection, and CodeQL (extended
  suite). Fix their findings; do not dismiss without a written reason.

## Review before merge

Any change in the scope above gets adversarial review before merge, separate
from the author:

1. Fable plus the other model family's top model (Astra for Claude-built work,
   Opus for Codex-built work), each read-only and told to try to break it.
2. Give reviewers the diff, what earlier passes already found, and the attack
   surfaces to probe. Ask for file:line, a concrete exploit path, a confidence
   score, blocking versus hardening, and PASS or FAIL.
3. Verify a disputed finding by reproducing it before acting. Fix blocking
   findings and recommended hardening as new commits, then re-review only the
   fix commits until both reviewers pass.
4. Record the findings and fixes in the PR description. A finding in merged
   code ships as its own fix PR immediately.
