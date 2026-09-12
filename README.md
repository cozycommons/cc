# Cozy Commons

Monorepo for Cozy Commons projects. Dice is the first application.

https://cozycommons.dev

## Layout

- `frontend/` — Vite + React Dice web app
- `backend/` — FastAPI Dice API
- `supabase/` — local Supabase configuration and synthetic seed data
- `scripts/` — isolated Dice development and migration tooling
- `docs/` — Dice behavior and operations documentation

## Local development

```bash
scripts/dice-dev.sh doctor
scripts/dice-dev.sh setup
scripts/dice-dev.sh local
```

The Dice app runs at <http://localhost:8080/dice>.

Copy the `.env.example` files only for normal direct service runs. The isolated
Dice harness injects verified loopback credentials and intentionally ignores
dotenv files.

`doctor` is a non-destructive prerequisite check. `install` installs locked
dependencies without starting services or resetting data. Before opening a PR,
run `scripts/dice-dev.sh verify` for the frontend, backend, shell, and migration
contract checks.

## Deployment

Production uses two Coolify applications sourced from this repository: the
FastAPI backend under `backend/` and the static Vite frontend under `frontend/`.
See [docs/deployment.md](docs/deployment.md) for the exact resource settings,
environment-variable boundaries, and first-deployment checklist.
