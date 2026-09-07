# AGENTS.md

This is the Cozy Commons monorepo. Dice is the first project.

## Layout

- `frontend/`: Vite + React Dice app served under `/dice`.
- `backend/`: FastAPI Dice API served under `/dice`.
- `supabase/`: isolated local Supabase configuration and synthetic seed data.
- `scripts/`: Dice development, migration, and verification tooling.
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

## Invariants

- Developer tooling must run on Ubuntu and macOS Bash 3.2.
- Keep Dice feature implementation behavior stable during repository migration.
- Preserve `/dice` frontend and API paths until an explicit product change.
- Never edit or renumber historical migrations. New migrations must use the
  `NNNN_dice_description.sql` form.
- Run database work only against the loopback Supabase stack unless the user
  explicitly requests a production-connected operation.
- Preserve the sandbox's loopback, hostname, dotenv-scrubbing, and port-privacy
  guards. Never weaken them to make a test pass.
- Do not commit `.env.local`, service-role keys, database credentials, or
  production data.
- Keep the old `jasonkeung.com/dice` deployment untouched during migration.

See `docs/dice-sandbox.md`, `docs/dice-data-model-testing.md`, and
`docs/deployment.md` for the authoritative workflows.
