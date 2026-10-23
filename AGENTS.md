# AGENTS.md

This is the `cozycommons/cc` monorepo. Dice and Cozy Trips (`/trips`) are
features of its shared application. A local checkout name or location does not
define a separate repository or make a feature WSL-specific.

## Layout

- `frontend/`: Vite + React Cozy Commons home, Dice at `/dice`, and Cozy Trips at `/trips`.
- `backend/`: FastAPI shared API with Commons routes under `/commons`, Dice under `/dice`, and Trips under `/trips`.
- `backend/ig_logger/`: generic Instagram-source → sink platform; routes under `/ig-logger`. `backend/ig_logger/sinks/beli/`: multi-tenant Beli restaurant app (the first sink); routes under `/beli`, MCP server at `/beli/mcp`.
- `supabase/`: isolated local Supabase configuration and project seed data.
- `scripts/`: shared development plus project-specific migration and verification tooling.
- `docs/`: product contracts and operational guidance.

## Commands

Run from the repository root unless noted otherwise.

- Setup: `scripts/dice-dev.sh setup`
- Local services: `scripts/dice-dev.sh local`
- Health: `scripts/dice-dev.sh status`
- Reset synthetic data: `scripts/dice-dev.sh reset`
- Stop: `scripts/dice-dev.sh stop`
- Frontend tests: `cd frontend && npm test -- --run`
- Frontend build: `cd frontend && npm run build`
- Backend tests: `cd backend && source .venv/bin/activate && python -m pytest tests -v`
- Commons migration check: `scripts/commons-dev.sh check`
- Commons local migration: `scripts/commons-dev.sh local-migrate`

## Developer-platform compatibility

Developer tooling must work on Ubuntu (including WSL2 and Codespaces) and
macOS. Shell entry points must use Unix-compatible syntax accepted by Bash 3.2.
Do not commit Linux-only process or filesystem assumptions such as `/proc`,
`ss`, or `setsid` in shared scripts. Do not add PowerShell, `cmd.exe`, or
Windows-path syntax to repository scripts or documented developer commands.

## GitHub batching and CI cost

- Distinguish branch backups from PR updates. This repository's CI runs on
  `pull_request` events, merge queues, and pushes to `main`. Pushing a feature
  branch without an open PR does not trigger this workflow; frequent branch
  backups are fine when useful. Draft PRs still trigger CI.
- Open a PR when a coherent delivery is ready for review and proportional local
  checks pass. Do not open a draft PR solely to back up unfinished work or use
  remote CI as the first local test loop, unless the user explicitly requests it.
- Once a branch has an open PR, batch related changes and local commits into one
  verified push per meaningful review checkpoint. Do not push each file edit,
  test attempt, progress update, or documentation-only handoff separately.
- After a CI failure, inspect its logs, reproduce and fix locally where possible,
  then push the complete fix batch. Rerun unchanged CI only for a demonstrated
  transient failure; avoid repeated speculative reruns.
- Check whether the branch already has an open PR when choosing push cadence.
  Keep required checks enabled and do not rewrite shared branch history merely
  to avoid CI. Include instruction/documentation edits with the next appropriate
  verified batch rather than triggering a separate run for them.

## Invariants

- Keep the root README brief and describe only projects and behavior on `main`.
  Never mention ongoing branches or work in progress; any branch references must
  point to `main`.
- Developer tooling must run on Ubuntu and macOS Bash 3.2.
- Keep Dice feature implementation behavior stable during repository migration.
- Preserve `/dice` frontend and API paths until an explicit product change.
- Never edit or renumber historical migrations. Existing Dice migrations retain
  the `NNNN_dice_description.sql` form; Commons migrations use
  `backend/commons/migrations/NNNN_commons_description.sql` and the Commons
  migration scripts.
- Run database work only against the loopback Supabase stack unless the user
  explicitly requests a production-connected operation.
- Preserve the sandbox's loopback, hostname, dotenv-scrubbing, and port-privacy
  guards. Never weaken them to make a test pass.
- Do not commit `.env.local`, service-role keys, database credentials, or
  production data.
- Keep the old `jasonkeung.com/dice` deployment untouched during migration.

See `docs/dice-sandbox.md`, `docs/dice-data-model-testing.md`, and
`docs/deployment.md` for the authoritative workflows.
