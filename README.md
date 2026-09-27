# Cozy Commons

Monorepo for Cozy Commons projects

https://cozycommons.dev

## Layout

- `frontend/` — Vite + React Dice web app
- `backend/` — FastAPI Dice API
- `backend/beli/` — multi-tenant Beli restaurant app (`/beli` routes, `/beli/mcp` MCP server)
- `supabase/` — local Supabase configuration and synthetic seed data
- `scripts/` — isolated Dice development and migration tooling
- `docs/` — Dice behavior and operations documentation; `docs/beli.md` covers the Beli app

## Beli app

Personal restaurant recommendations and "Want to Try" bookmarks backed by
each friend's own Beli account. Onboarding: `POST /beli/onboard` with the
friend's Beli login returns a personal API token (shown once); all other
`/beli/*` endpoints take `Authorization: Bearer <token>`. See
[docs/beli.md](docs/beli.md) for the architecture and
[docs/beli/SKILL.md](docs/beli/SKILL.md) — the agent-readable skill for
Muse/Claude Code, ChatGPT (Custom GPT Action via `/openapi.json`), MCP
clients (`/beli/mcp`), or raw REST.

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
