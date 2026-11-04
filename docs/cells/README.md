# Cozy Commons cells: software shaped by its community

Status: **proposed direction, not implemented.** Until a phase below lands,
`docs/deployment.md#project-placement-policy` and the current Coolify/Supabase
setup remain authoritative. This document records the decisions and the plan so
later work can pick them up.

## Vision

Cozy Commons is a shared home for software that a community uses and shapes
together. Members bring their own personal agents to build and maintain it;
Cozy Commons provides the common infrastructure that makes the result usable
by the group and, when the group chooses, the public.

The intended experience is: "Create a place for our group, invite my friends,
and let us use and change the software together."

Personal agents already provide much of the ability to build and operate
software. A person with an agent and a machine can assemble hosting, sign-in,
data storage and backups themselves. Cozy Commons makes that setup reusable
and gives friends a common place to collaborate across agent vendors. This is
infrastructure for our community, not an attempt to build another personal
agent.

A smaller community is normally both the primary audience and the group that
shapes the software. Its audience can also include members who do not edit,
invited guests and the public. Using an app does not grant permission to edit
it, and publishing a screen does not expose private data or machine access.

Every app has the same cell shape. Its access, ownership and change rules can
differ:

- **Community:** a person or group that stewards the app. A personal cell is
  the one-member version.
- **Audience:** members, invited users or the public, with access decided by
  the community.
- **Change risk:** how many people a change affects and whether data could be
  lost. This decides the checks and approval needed before it goes live.

### Shared stewardship

These are overlapping responsibilities; their exact permission model remains
to be designed:

- **Stewards** manage membership, editing permissions, publishing policy and
  recovery, and decide which changes require community approval.
- **Contributors** shape the software through their agents, within the
  permissions the community grants them.
- **Users** use the app and contribute data within its rules. They need not
  be contributors or members of the stewarding community.

For example, friends maintain Dice together, tournament participants use it,
and spectators can view public scores. A friend can ask their agent to add a
feature to the same app the group already uses, rather than create a separate
copy owned by that agent.

Participation should not require reading code. Community approval can be based
on a working preview and a plain-language explanation of the effects. Whether
a change ships automatically or needs approval depends on the community's
rules and the change's impact; shared stewardship does not mean every member
can change everything without agreement.

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

- Data, in a neutral store that authorized agents can read.
- Context: `AGENTS.md`, goals, preferences and notes as plain files.
- Apps that people use in a browser without any particular agent.
- Community membership, permissions and private or public access.
- Hosting, stable domains, data storage, backups and recovery.
- State shared across agents and people.

Before building something, ask whether an agent vendor shipping it next month
would make it useless or more useful. Build only what becomes more useful.
Support at least two agent vendors so the design stays vendor-neutral.

## Architecture

```
internet ─► platform proxy (route access policy) ─┬─► /mcp    shell + files connector
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

The platform supplies the setup each community would otherwise have to arrange
with its agents: identity and OAuth connections, hosting and domains,
permissions, publishing, storage and recovery. It should stay small and stable,
and is the only part protected from careless agent edits. It provides:

- Sign-in: Supabase Auth stays the identity provider. Authenticated access
  verifies its JWT; agent connections use OAuth and scoped authorization.
- Membership and permissions: invite people and grant use, contribution or
  stewardship access. Agents act within the connecting person's permissions.
- Hosting and domains: stable addresses and a proxy routing `/<app>` and cell
  hosts to their runtimes.
- Publishing: explicit private, community or public route policies. Public
  app access never grants shell, file or database access.
- A cell runtime: start, stop and resource limits for each cell.
- Snapshots, backups and restore.
- Preview, swap and rollback for changes.
- A generic shell and files connector for agents.
- Shared identity (today's `commons_profiles`) as a platform service.

Authorized agents can change cell software within their granted access, but
they cannot remove platform controls or grant themselves additional access.

### Cells

A cell is one app: a directory with `AGENTS.md`, code, tests, memory files, git
history and its own database. Dice, Trips, Beli and a personal health app are
all cells. Each cell is stewarded by a person or community. A person can belong
to several cells with different permissions in each.

- A cell's apps run inside the cell and read its local database.
- Cells use each other's HTTP APIs, never each other's tables.
- **Personal cells** can allow low-risk live edits, with a snapshot taken
  before each change. Personal ownership does not make destructive data
  changes low risk.
- **Shared cells** use a preview and checks, plus approval where the community
  requires it, before a change goes live. A snapshot-based preview database
  (`CREATE DATABASE … TEMPLATE …`) is proposed; promotion must preserve writes
  made to the live app while the preview is running. The exact promotion and
  recovery protocol remains to be designed.
- Each code change is a git commit. Reverting code and restoring data are
  distinct operations; a code revert alone cannot undo database or file writes.
  Health checks and automatic rollback must account for that distinction.

### Agent access

- **Chat agents** (ChatGPT, Claude) connect through one generic MCP connector
  with shell and file tools (roughly `exec`, `read_file`, `write_file`),
  protected by OAuth and limited to the cells and operations the user is
  authorized to access. Apps get no app-specific MCP tools; agents work with
  files, code and SQL directly.
- **Coding agents** (Codex CLI, Claude Code) can run inside the cell or connect
  over SSH. Every route sees the same files.
- MCP and SSH are access mechanisms, not the defining property of a cell.
  Either must enforce the same access boundaries. Machine access is a trusted
  contribution capability, separate from ordinary app use; more granular
  contributor permissions need a concrete enforcement design.
- Scheduling and proactive work use the agent vendor's scheduled tasks. Cozy
  Commons does not build its own.
- Apps do not embed their own agent. They can link out ("Ask ChatGPT about
  this").

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Every app, existing or new, is a cell with the same shape | Agents build all of it, so separate classes add cost without benefit |
| D2 | Community policy and change risk set how a change ships | Members can shape software without granting every change automatic publication |
| D3 | Each cell's database is local to the host | Sub-millisecond queries, cheap previews, isolation, and agents can work on it directly |
| D4 | One local Postgres server, one database and role per cell; Postgres is the only engine | Existing apps move by `pg_dump`/restore instead of a rewrite; `TEMPLATE` copies make previews cheap; no joins across databases enforces cell boundaries; one dialect for agents |
| D5 | Keep Supabase Auth for sign-in | Replacing it makes nothing easier for agents |
| D6 | Generic machine access, initially shell and files over MCP, with SSH for coding agents | The shared environment stays independent of the agent vendor and access transport |
| D7 | Rent agent capabilities and own data, context and apps | Benefit from each vendor release instead of competing with it |
| D8 | Store memory as plain files per user, outside git history for personal data | Readable by any vendor's agent; vendor memory acts as a cache |
| D9 | The platform stays small and changes slowly | It is the one part a careless change can break for every cell |
| D10 | Cells support shared stewardship, contribution and use as distinct responsibilities | A community can shape an app whose audience includes non-editors and the public |
| D11 | Cozy Commons supplies common identity, hosting, domains, publishing and recovery | Each group should not have to assemble this infrastructure separately with its agents |

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

Automated checks and recovery are prerequisites for automatic shipping; they
do not replace a community's approval rules. These items come before any shared
cell ships automatically:

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
- Low-risk UI changes can ship live under the owner's policy. Changes that
  risk stored history need checks and an explicit recovery path.
- The existing workout app in `jasonkeung/dummi` moves into this cell.
- Wearables come later. Apple Health needs an on-device exporter (a Shortcut or
  an export app) posting to an authenticated endpoint. Whoop, Oura and Garmin
  have web APIs that can be synced on a schedule.

## Plan

1. **Deploy loop:** prerequisites 1–4 above, for the current shared app.
2. **Platform skeleton:**
   - Cell runtime on Coolify.
   - Local Postgres with WAL backups and a rehearsed restore.
   - Proxy with Supabase Auth, membership permissions and explicit public routes.
   - Stable domains and private/community/public publishing controls.
   - Shell and files connector with OAuth and per-member cell authorization.
3. **First cell:** the personal health cell. Move the workout app from `dummi`
   and add memory files and `health_log`. This proves live editing, snapshots
   and the connector from ChatGPT and Claude.
4. **Preview and promotion:** define the shared-cell change path, including
   community approval rules, concurrent live writes, schema changes and data
   recovery. Prove it before relying on automatic promotion or rollback.
5. **First shared cell:** a small, loosely coupled `cc` project such as Beli or
   Partiful, moved from Supabase to local Postgres. Validate the central shared
   stewardship workflow: invite another contributor, connect their agent,
   preview a change, approve and publish it, and recover from a failed change.
   Also verify that a non-editor can use the app and that a public route exposes
   only its intended content. The health cell tests the mechanics; this step
   tests collaboration across people and agents.
6. **Identity service:** move `commons_profiles` and cross-project identity
   into the platform, and replace cross-project table access with APIs.
7. **Remaining projects:** convert each one when it is next touched. Dice goes
   last because it has the most migrations and users. Until a project moves, it
   runs as today, as one large existing cell.

## Open questions

- **Community governance:** which changes can contributors ship independently,
  which need approval, who approves, and how is stewardship transferred?
- **Concurrent editing:** how do multiple members' agents coordinate changes
  to the same cell and resolve conflicting edits?
- **Permission enforcement:** what capabilities does each role receive, and
  how are they enforced consistently through MCP, SSH and app access?
- **Public access:** which screens and operations can be public, and who may
  change that policy? Public readership must not imply public data access.
- **Promotion and recovery:** how do preview changes preserve concurrent live
  writes, and what does undo mean for code, schema, data and memory files?

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
  needs strong OAuth, per-member cell authorization, no platform secrets inside
  cells, and resource limits.
- **Vendor lock-in pressure:** agent products may limit third-party connectors
  or favour their own memory. Keep the connector thin and data portable, so
  switching vendors means reconnecting, not migrating.
- **Platform creep:** every feature added to the platform is one that agents
  cannot freely change. Keep it small.
