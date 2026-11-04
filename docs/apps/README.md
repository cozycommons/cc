# Cozy Commons apps: software shaped by its community

Status: **local prototype; hosted platform remains proposed.** See
[the local walkthrough](PROTOTYPE.md), [product contract](PRODUCT.md) and
[technical design](TECH.md). Existing deployed projects still follow
`docs/deployment.md#project-placement-policy` and the current Coolify/Supabase
setup. No existing app migration or VPS deployment is part of this prototype.

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

Every app follows the same basic structure. Its access, ownership and change
rules can differ:

- **Community:** a person or group that stewards the app. A personal app is
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
- Coding harnesses and temporary task sandboxes; the app environment stays ours.
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
                                               └─► app subdomains → chosen ports
                                                        │
          ┌─────────────────────────────────────────────▼─────────────────┐
          │ app: AGENTS.md · code · tests · memory/ · git history           │
          │       own Postgres database + role (local service)              │
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
- Hosting and domains: `<app>.cozycommons.dev` routes to the app's default
  published port. Additional services use `<app>--<service>.cozycommons.dev`.
  Platform names such as admin, api, auth and www are reserved; `--` is reserved
  as the service separator. The local prototype uses `.localhost` on port 8090.
- Publishing: explicit private, community or public route policies. Public
  app access never grants shell, file or database access.
- An app runtime: start, stop and resource limits for each app.
- Snapshots, backups and restore.
- Dynamic publication and removal of named HTTP ports, private by default.
- A generic shell and files connector for agents.
- Shared identity (today's `commons_profiles`) as a platform service.

Authorized agents can change app software within their granted access, but
they cannot remove platform controls or grant themselves additional access.

### Apps

One app normally has one persistent Docker container, organized around a purpose:
a new app idea, someone's health, or a particular trip. It holds files, code,
`AGENTS.md`, tests, memory and git history, with access to its own database. It
can start with context and files and acquire interfaces and behavior over time.
Each app is stewarded by a person or community; people may belong to several.

- The container behaves like a small computer. Authorized agents can download
  files, install dependencies, write code and start multiple processes.
- A primary web server, an experiment, a background worker and a preview can all
  run in the same container. They are part of the same purpose-oriented app.
- Agents expose selected ports through the platform. The platform owns hostname
  allocation, access policy and proxy configuration; arbitrary container ports
  are not automatically public. Publishing a port does not start its server.
- There is no special preview subsystem. An agent can run another server and
  publish its port when useful. Processes in the same container share resources
  and an access boundary; a preview is not isolated from the live process.
- Workspace files persist on a volume. Dependencies installed outside it must
  be reproducible when replacing the container. Registered services restart with
  the container; ad-hoc processes do not necessarily restart.
- Apps use each other's HTTP APIs, never each other's tables.
- Community policy decides which changes need agreement. The local prototype
  trusts contributors with the entire app and does not implement approval gates.
- Code reverts and data recovery are distinct. The local prototype supports
  explicit maintenance-window workspace/database backups and restoration, not
  automatic rollback or swapping preview data into a live database.

### Agent access

- **Chat agents** (ChatGPT, Claude) connect through one generic MCP connector
  with shell and file tools (roughly `exec`, `read_file`, `write_file`),
  protected by OAuth and limited to the apps and operations the user is
  authorized to access. Apps get no app-specific MCP tools; agents work with
  files, code and SQL directly.
- **Coding agents** (Codex CLI, Claude Code) can run inside the app's runtime or connect
  over SSH. Every route sees the same files.
- MCP and SSH are access mechanisms, not the defining property of an app.
  Either must enforce the same access boundaries. Machine access is a trusted
  contribution capability, separate from ordinary app use; more granular
  contributor permissions need a concrete enforcement design.
- Scheduling and proactive work use the agent vendor's scheduled tasks. Cozy
  Commons does not build its own.
- For now, people invoke agents in their existing agent products and connect
  them to the app. Invoking an agent from inside the app is explicitly deferred;
  seamless in-app interaction is not a prerequisite for this prototype.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Every app, existing or new, follows the same basic structure | Agents build all of it, so separate classes add cost without benefit |
| D2 | Community policy and change risk set how a change ships | Members can shape software without granting every change automatic publication |
| D3 | Each app's database is local to the host | Direct agent access and locally managed storage and recovery |
| D4 | One local Postgres server, one database and role per app; Postgres is the only engine | A common SQL dialect and separate data ownership; existing apps can eventually migrate with dump/restore |
| D5 | Keep Supabase Auth for sign-in | Replacing it makes nothing easier for agents |
| D6 | Generic machine access, initially shell and files over MCP, with SSH for coding agents | The shared environment stays independent of the agent vendor and access transport |
| D7 | Rent agent capabilities and own data, context and apps | Benefit from each vendor release instead of competing with it |
| D8 | Store memory as plain files per user, outside git history for personal data | Readable by any vendor's agent; vendor memory acts as a cache |
| D9 | The platform stays small and changes slowly | It is the one part a careless change can break for every app |
| D10 | Apps support shared stewardship, contribution and use as distinct responsibilities | A community can shape an app whose audience includes non-editors and the public |
| D11 | Cozy Commons supplies common identity, hosting, domains, publishing and recovery | Each group should not have to assemble this infrastructure separately with its agents |
| D12 | Normally one app, one persistent Docker container; agents control its files and processes | An app can evolve around its purpose without prescribing its interfaces or process layout |
| D13 | Publish a default port and arbitrary named service ports through the shared proxy | Previews and experiments need no special platform abstraction |
| D14 | Invoke external agents; defer invoking an agent from inside the app | Prove the shared environment before building an agent interaction surface |

### Postgres details (D4)

- Each app gets a database and a role with `CONNECT` on only that database,
  plus a per-role `statement_timeout` and connection limit. The Postgres
  container has a memory cap.
- An app that needs strict isolation can get its own Postgres container with
  the same conventions.
- Back up continuously with WAL-G or pgBackRest to object storage, for
  point-in-time restore. Rehearse a full restore onto a new VM before moving
  any shared app. Until that test passes, the backups are unproven.
- When moving off Supabase:
  - Define a local `auth.uid()` that reads the user ID the backend sets for
    each request, so existing row-level security policies keep working.
  - Replace foreign keys to `auth.users` with plain UUID columns.
  - Remove grants to `anon` and `authenticated`.
  - Move Supabase Storage objects to the app's disk or R2.

## Prerequisites from the current pipeline

Automated checks and recovery are prerequisites for automatic shipping; they
do not replace a community's approval rules. These items come before any shared
app ships automatically:

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

## Example: personal health app

- The person talks to ChatGPT through the shell connector.
- Logging a meal, a metric or a workout becomes rows in the health app's
  database or lines in files. The agent decides how to store them and records
  its conventions in the app's `AGENTS.md`.
- A generic `health_log` table (timestamp, kind, JSON details, note) holds new
  kinds of entries before they have a UI. When a kind is used often, the agent
  adds a proper table and screen for it.
- "Plan today's workout" reads goals, recent sessions and soreness, then writes
  a session that is ready to start in the workout app.
- Low-risk UI changes can ship live under the owner's policy. Changes that
  risk stored history need checks and an explicit recovery path.
- The existing workout app in `jasonkeung/dummi` moves into this app.
- Wearables come later. Apple Health needs an on-device exporter (a Shortcut or
  an export app) posting to an authenticated endpoint. Whoop, Oura and Garmin
  have web APIs that can be synced on a schedule.

## Plan

1. **Local prototype:** persistent app containers, generic MCP shell/files,
   contributor/viewer permissions, dynamic port publication, and a tested local
   backup/restore path. Use synthetic data and loopback-only host ports.
2. **Hosted pilot:** OAuth for external agents, real DNS/TLS, hosted browser
   sign-in, durable off-server backups and a restore drill. Use a new app before
   moving any existing personal or shared app.
3. **Shared stewardship:** exercise two people's agents shaping the same app,
   including non-editor use and intentional public publication. Refine change
   agreement and concurrent editing policies from actual use.
4. **Existing projects:** evaluate migrations separately after the platform is
   proven. Preserve the shared application and its deployment workflow until a
   specific migration is approved; Dice remains last due to its users and history.

## Open questions

- **Community governance:** which changes can contributors ship independently,
  which need approval, who approves, and how is stewardship transferred?
- **Concurrent editing:** how do multiple members' agents coordinate changes
  to the same app and resolve conflicting edits?
- **Permission enforcement:** what capabilities does each role receive, and
  how are they enforced consistently through MCP, SSH and app access?
- **Public access:** which screens and operations can be public, and who may
  change that policy? Public readership must not imply public data access.
- **Recovery:** what additional recovery guarantees are needed beyond explicit
  local workspace/database restoration before hosting real community data?

- **Codex:** Codex cloud tasks or the Codex CLI inside app runtimes? Check whether
  automated use from a ChatGPT subscription is permitted before relying on it.
- **Hosting:** VPS (Coolify container and volume) or a hosted machine with
  persistent storage, such as Fly Machines? The default is the VPS.
- **Human access:** do people get a web terminal or SSH into their app runtimes, or do
  only agents get in?
- **Personal vs shared UI changes:** does a UI change in a shared app apply to
  everyone, or become a per-user setting or a fork?
- **Health data privacy:** private by default; decide what, if anything,
  friends can see.
- **Existing data:** whether `dummi` workout history moves with the app.
- **Meal estimates:** whether photo-based estimates are enough, or a nutrition
  database is needed.

## Risks

- **A single VPS** holds every app. Off-server backups and a tested restore
  are required, not optional.
- **The internet-facing shell connector** is the largest attack surface. It
  needs strong OAuth, per-member app authorization, no platform secrets inside
  apps, and resource limits.
- **Vendor lock-in pressure:** agent products may limit third-party connectors
  or favour their own memory. Keep the connector thin and data portable, so
  switching vendors means reconnecting, not migrating.
- **Platform creep:** every feature added to the platform is one that agents
  cannot freely change. Keep it small.
