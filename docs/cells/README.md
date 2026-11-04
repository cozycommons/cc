# Cozy Commons cells: agent-controlled software

Status: **proposed direction, not implemented.** Until a phase below lands,
`docs/deployment.md#project-placement-policy` and the current Coolify/Supabase
setup remain authoritative. This document records the decisions and the plan so
later work can pick them up.

## Vision

Cozy Commons is software that agents change in place. A person talks to an
agent ("log my lunch", "plan today's workout", "add a protein chart") and the
agent reads and writes data, or edits and ships code, in a closed loop. No human
code review is part of that loop, and nobody needs to read the code.

Every Cozy Commons app is already agent-built, so there is no separate class of
"agent-built apps". Every app has the same shape. The differences that remain
are properties of an app, not of who wrote it:

- **Tenancy:** personal (one person's data, such as health) or shared (several
  people's data, such as Dice or Trips).
- **Change risk:** how many people a bad change affects and whether data could
  be lost. This decides how much checking a change needs before it goes live.

## Principle: own what lasts, rent what improves

Personal agents (ChatGPT, Claude, Codex, Muse, Grok and others) will keep
improving. Cozy Commons should benefit from each release instead of competing
with it.

Rent from agent products:

- Reasoning and models.
- Chat, voice and mobile interfaces.
- Proactive check-ins and scheduled tasks.
- Understanding photos and documents.
- Coding harnesses and sandboxes.
- Their own built-in memory.

Own in Cozy Commons:

- Data, in a neutral store that any agent can read.
- Context: `AGENTS.md`, goals, preferences and notes as plain files.
- Apps that people use in a browser without any particular agent.
- State shared across agents and people.

Before building something, ask whether an agent vendor shipping it next month
would make it useless or more useful. Build only what becomes more useful.
Support at least two agent vendors so the design stays vendor-neutral.

## Architecture

```
internet ─► platform proxy (Supabase Auth JWT) ─┬─► /mcp    shell + files connector
                                                └─► /<app>  cell web apps
                                                        │
          ┌─────────────────────────────────────────────▼─────────────────┐
          │ cell: AGENTS.md · code · tests · memory/ · git history          │
          │       own Postgres database + role (local Unix socket)          │
          └──────────────────────────────────────────────────────────────────┘
                     │ continuous WAL + volume snapshots
                     ▼
              off-server object storage (R2/S3)
```

### Platform

The platform is small, stable and the only part protected from careless agent
edits. It provides:

- Sign-in: Supabase Auth stays the identity provider, and the proxy verifies
  its JWT for every cell.
- A proxy that routes `/<app>` and per-person hosts to cells.
- A cell runtime: start, stop and resource limits for each cell.
- Snapshots, backups and restore.
- Preview, swap and rollback for changes.
- A generic shell and files connector for agents.
- Shared identity (today's `commons_profiles`) as a platform service.

Agents can do anything inside a cell, but they cannot remove platform controls.

### Cells

A cell is one app: a directory with `AGENTS.md`, code, tests, memory files, git
history and its own database. Dice, Trips, Beli and a personal health app are
all cells. A person's "box" is the set of cells they own.

- A cell's apps run inside the cell and read its local database.
- Cells use each other's HTTP APIs, never each other's tables.
- **Personal cells** are edited live, with a snapshot taken before each change.
  Each change is a git commit, so undoing one is a revert.
- **Shared cells** are edited in a preview copy made from a snapshot of their
  code and data (`CREATE DATABASE … TEMPLATE …`). Checks run against the copy,
  then it swaps in. Health checks after the swap trigger automatic rollback.

### Agent access

- **Chat agents** (ChatGPT, Claude) connect through one generic MCP connector
  with shell and file tools (roughly `exec`, `read_file`, `write_file`),
  protected by OAuth and limited to the cells the user owns. Apps get no
  app-specific MCP tools; agents work with files, code and SQL directly.
- **Coding agents** (Codex CLI, Claude Code) can run inside the cell or connect
  over SSH. Every route sees the same files.
- Scheduling and proactive work use the agent vendor's scheduled tasks. Cozy
  Commons does not build its own.
- Apps do not embed their own agent. They can link out ("Ask ChatGPT about
  this").

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Every app, existing or new, is a cell with the same shape | Agents build all of it, so separate classes add cost without benefit |
| D2 | Tenancy and change risk set how a change ships, not authorship | These measure the impact of a bad change |
| D3 | Each cell's database is local to the host | Sub-millisecond queries, cheap previews, isolation, and agents can work on it directly |
| D4 | One local Postgres server, one database and role per cell; Postgres is the only engine | Existing apps move by `pg_dump`/restore instead of a rewrite; `TEMPLATE` copies make previews cheap; no joins across databases enforces cell boundaries; one dialect for agents |
| D5 | Keep Supabase Auth for sign-in | Replacing it makes nothing easier for agents |
| D6 | Generic shell and files connector instead of app-specific MCP tools | New apps need no new tools, and the connector can be dropped when agent products can attach a computer natively |
| D7 | Rent agent capabilities and own data, context and apps | Benefit from each vendor release instead of competing with it |
| D8 | Store memory as plain files per user, outside git history for personal data | Readable by any vendor's agent; vendor memory acts as a cache |
| D9 | The platform stays small and changes slowly | It is the one part a careless change can break for every cell |

### Postgres details (D4)

- Each cell gets a database and a role with `CONNECT` on only that database,
  plus a per-role `statement_timeout` and connection limit. The Postgres
  container has a memory cap.
- A cell that needs strict isolation can get its own Postgres container with
  the same conventions.
- Back up continuously with WAL-G or pgBackRest to object storage, for
  point-in-time restore. Rehearse a full restore onto a new VM before moving
  any shared cell. Until that test passes, the backups are unproven.
- When moving off Supabase:
  - Define a local `auth.uid()` that reads the user ID the backend sets for
    each request, so existing row-level security policies keep working.
  - Replace foreign keys to `auth.users` with plain UUID columns.
  - Remove grants to `anon` and `authenticated`.
  - Move Supabase Storage objects to cell disk or R2.

## Prerequisites from the current pipeline

Shipping without review is safe only once the deploy loop is closed. These items
come before any shared cell ships automatically:

1. **Deploy visibility:** `/version` (backend) and `version.json` (frontend)
   report the git commit they were built from. `scripts/verify-deploy` waits for
   the new commit to be live, then runs a read-only smoke test against
   production. In `AGENTS.md`, "done" means live and verified, not merged.
2. **Automatic rollback:** a post-deploy action redeploys the previous image
   through the Coolify API when the new commit doesn't go live in time, or when
   the smoke test or `/ready` fails. It also opens an incident issue.
3. **Build once, deploy what passed:** CI builds images once, pushes them to
   GHCR and deploys that exact image through the Coolify API. This replaces the
   push webhook and the second CI run on `main`, and enables auto-merge.
4. **Contained failures:** a project router that fails to import gives 503 for
   that project only, instead of stopping the shared backend.

Items 2 and 3 need a Coolify API token and application IDs stored as GitHub
secrets.

## Example: personal health cell

- The person talks to ChatGPT through the shell connector.
- Logging a meal, a metric or a workout becomes rows in the health cell's
  database or lines in files. The agent decides how to store them and records
  its conventions in the cell's `AGENTS.md`.
- A generic `health_log` table (timestamp, kind, JSON details, note) holds new
  kinds of entries before they have a UI. When a kind is used often, the agent
  adds a proper table and screen for it.
- "Plan today's workout" reads goals, recent sessions and soreness, then writes
  a session that is ready to start in the workout app.
- Changes to the UI ship live, because the cell is personal.
- The existing workout app in `jasonkeung/dummi` moves into this cell.
- Wearables come later. Apple Health needs an on-device exporter (a Shortcut or
  an export app) posting to an authenticated endpoint. Whoop, Oura and Garmin
  have web APIs that can be synced on a schedule.

## Plan

1. **Deploy loop:** prerequisites 1–4 above, for the current shared app.
2. **Platform skeleton:**
   - Cell runtime on Coolify.
   - Local Postgres with WAL backups and a rehearsed restore.
   - Proxy that checks Supabase Auth.
   - Shell and files connector with OAuth.
3. **First cell:** the personal health cell. Move the workout app from `dummi`
   and add memory files and `health_log`. This proves live editing, snapshots
   and the connector from ChatGPT and Claude.
4. **Preview and swap:** the shared-cell change path, using `TEMPLATE` copies,
   checks, swap and automatic rollback.
5. **First shared cell:** a small, loosely coupled `cc` project such as Beli or
   Partiful, moved from Supabase to local Postgres.
6. **Identity service:** move `commons_profiles` and cross-project identity
   into the platform, and replace cross-project table access with APIs.
7. **Remaining projects:** convert each one when it is next touched. Dice goes
   last because it has the most migrations and users. Until a project moves, it
   runs as today, as one large existing cell.

## Open questions

- **Codex:** Codex cloud tasks or the Codex CLI inside cells? Check whether
  automated use from a ChatGPT subscription is permitted before relying on it.
- **Hosting:** VPS (Coolify container and volume) or a hosted machine with
  persistent storage, such as Fly Machines? The default is the VPS.
- **Human access:** do people get a web terminal or SSH into their cells, or do
  only agents get in?
- **Personal vs shared UI changes:** does a UI change in a shared cell apply to
  everyone, or become a per-user setting or a fork?
- **Health data privacy:** private by default; decide what, if anything,
  friends can see.
- **Existing data:** whether `dummi` workout history moves with the app.
- **Meal estimates:** whether photo-based estimates are enough, or a nutrition
  database is needed.

## Risks

- **A single VPS** holds every cell. Off-server backups and a tested restore
  are required, not optional.
- **The internet-facing shell connector** is the largest attack surface. It
  needs strong OAuth, per-user cell scoping, no platform secrets inside cells,
  and resource limits.
- **Vendor lock-in pressure:** agent products may limit third-party connectors
  or favour their own memory. Keep the connector thin and data portable, so
  switching vendors means reconnecting, not migrating.
- **Platform creep:** every feature added to the platform is one that agents
  cannot freely change. Keep it small.
