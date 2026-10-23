# Cozy Commons

A monorepo for community projects amongst our friends.

[cozycommons.dev](https://cozycommons.dev)

## Projects

- **[Dice](docs/dice-feature-map.md)** — live scoring, tournaments, player ratings, and predictions.
- **[Crowdset](docs/crowdset/README.md)** — combine friends’ concert recordings into synchronized video and audio mixes.
- **[Cozy Trips](docs/cozy-trips.md)** — shared trip expenses, balances, and repayments.
- **[Beli](docs/beli.md)** — restaurant recommendations and bookmarks, including finds from Instagram.
- **[Partiful](docs/partiful.md)** — access to friends’ hosted, RSVP’d, and invited events.
- **[Resy](backend/resy/)** — restaurant search, availability, and reservations.
- **[ESPN Fantasy](backend/espn/)** — league stats, rosters, and opt-in lineup automation.

## Layout

- `frontend/` — shared Vite + React web app
- `backend/` — FastAPI services and integrations
- `supabase/` — local database configuration and seed data
- `scripts/` — development, migration, and verification tooling
- `docs/` — project guides, specs, and operations
- `design/` — design system and visual explorations

## Deployment

Coolify builds from `cozycommons/cc` on `main`, with separate Dockerfile applications
for the shared frontend (`frontend/Dockerfile`, port 80) and backend
(`backend/Dockerfile`, port 8000). Push webhooks trigger deployments; watch paths
limit rebuilds to relevant changes. GitHub required PR checks gate changes to `main`.

Environment variables are configured per application in Coolify. The backend runs
database migrations before starting. Crowdset has a separate hosted service.
See the [deployment guide](docs/deployment.md) and
[Crowdset hosting setup](docs/crowdset/README.md#hosted-test-configuration) for details.
