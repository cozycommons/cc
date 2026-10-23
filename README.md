# Cozy Commons

Cozy Commons is a monorepo for community projects amongst our friends.

[cozycommons.dev](https://cozycommons.dev)

## Projects

- **Dice** — our Dice game app at `/dice`, with live scoring, tournaments, player ratings, and predictions. See the [feature map](docs/dice-feature-map.md).
- **Crowdset** — a shared set catalog at `/crowdset` that combines friends' concert recordings into synchronized video and audio mixes. See the [Crowdset README](docs/crowdset/README.md).
- **Beli** — personal restaurant recommendations and Want to Try bookmarks, with Instagram restaurant-post ingestion. API at `/beli`; MCP at `/beli/mcp`. See the [Beli docs](docs/beli.md).
- **Partiful** — access to each friend's hosted, RSVP'd, and invited events. API at `/partiful`; MCP at `/partiful/mcp`. See the [Partiful docs](docs/partiful.md).
- **Resy** — restaurant search, reservation availability, booking, and cancellation. API at `/resy`; MCP at `/resy/mcp`. Code lives in [`backend/resy/`](backend/resy/).
- **ESPN Fantasy** — league standings, rosters, trends, draft history, and opt-in lineup automation. API at `/espn`; MCP at `/espn/mcp`. Code lives in [`backend/espn/`](backend/espn/).

## Layout

- `frontend/` — shared Vite + React homepage and project apps
- `backend/` — FastAPI services for the projects above; Crowdset runs as a separate service
- `backend/ig_logger/` — shared Instagram-source → sink platform, with Beli as its first sink
- `supabase/` — local Supabase configuration and synthetic seed data
- `scripts/` — shared and project-specific development, migration, and verification tooling
- `docs/` — project guides, behavior contracts, design decisions, and operations documentation
- `design/` — shared design system, visual explorations, and component previews

## Local development

For the isolated Dice sandbox and shared frontend:

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

Crowdset has its own setup and service commands in the [Crowdset README](docs/crowdset/README.md).
Integration setup and onboarding are documented in the project guides linked above, where available.

## Deployment

The shared production stack uses Coolify applications sourced from this repository:
the FastAPI backend under `backend/` and the static Vite frontend under `frontend/`.
See [docs/deployment.md](docs/deployment.md) for the exact resource settings,
environment-variable boundaries, and first-deployment checklist.
Crowdset has a separate hosted service; see its [hosted configuration](docs/crowdset/README.md#hosted-test-configuration).
