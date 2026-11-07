# Apps prototype technical design

Hosted candidate configuration and its separate rollout gates are documented in [HOSTING.md](HOSTING.md). The local workflow below remains unchanged.

## Context

The approved direction is in [README.md](README.md); observable behavior is in
[PRODUCT.md](PRODUCT.md). Current shared deployment policy permits a separate
runtime for persistent state and independently managed processes. This prototype
requires privileged container lifecycle operations, so it is separate from the
shared FastAPI API and does not mount Docker access into that existing service.

## Proposed changes

- `backend/app_runtime`: a single-process FastAPI runtime manager, Docker driver,
  SQLite registry, CLI and stdio MCP adapter. SQLite holds platform metadata,
  not app data. The manager alone receives Docker access.
- `infra/apps`: reproducible Docker Compose manager and Caddy,
  plus a Python/Node/Git/supervisor image for app environments.
- Creating a new app initializes a local Git repository on main after starting
  its container. Starter AGENTS.md and .gitignore are the first commit. This
  initialization runs only during new app provisioning, not on restart or
  recreation; existing app files and history are not reseeded.
- MCP exposes list_apps, create_app, set_app_member and exec_command through the
  existing manager API. File operations and publishing use the app shell.
  APPS_CREATORS controls who can allocate new apps independently of app roles.
- Each app gets a named workspace volume and its own Docker bridge network.
  Only its app container, shared proxy join that network. The
  manager reaches Docker via its socket, never exposes it to an app, and only
  accepts bounded, validated application operations.
- Apps choose their own storage engines. The starter recommends SQLite in
  /workspace/data; no database provisioning, credentials or DATABASE_URL are
  supplied by the manager. Python sqlite3 and the sqlite3 CLI are available.
- Root inside a non-privileged app container permits package installation;
  host mounts, Docker socket and platform secrets are absent. CPU/memory/PID
  limits bound accidental load. This is a trusted-contributor prototype, not a
  hardened hostile-tenant hosting service. Egress remains available for downloads.
- Named services use validated `<app>--<service>` hosts; `--` is disallowed in
  either slug. Caddy provides reverse proxying and WebSockets, and calls the
  manager for route authorization. All routes check current registry visibility,
  so failures cannot silently leave a previously public route public.
- Local user bearer credentials also work as local browser Basic-auth passwords.
  Membership is rechecked on new private HTTP requests and WebSocket handshakes. Platform credentials are stripped
  before app forwarding. No cookies or hosted OAuth are introduced in this slice.
- Route mutations are serialized with Caddy regeneration/reload. Its admin API
  stays on container loopback; the manager reloads through Docker exec. Caddy
  startup loads the durable route config. Platform routes are never app-owned.
- An app-scoped token enables the in-container `commons expose` command. It only
  permits route mutations for that app; it cannot use shell or membership APIs.
  Recreating the container rotates it.
- Shell jobs use Docker exec with GNU timeout and bounded retained output; internal MCP polling
  separates long commands from individual HTTP request lifetimes while the tool
  waits and returns the completed result. Apps manage long-lived services
  with supervisor, not through special preview APIs.
- A lifespan-managed thread checks persisted per-app backup deadlines every 30
  seconds. Successful snapshots set the next deadline 24 hours later; failures
  retry in five minutes. Only the newest three completed manifests per app are
  retained, shared by automatic/manual snapshots. An atomic manifest marks
  completion; partial failures never evict a good snapshot. A durable backup-only
  marker restores prior running/stopped state after manager interruption.
- Per-app locks serialize mutations without holding the registry lock during
  Docker or archive operations; other apps remain available during backups.
- Backups stop the app and archive its entire workspace using a helper
  container. Restore is explicit and occurs while stopped. It stages extraction on the
  workspace volume before replacement, with rollback on ordinary rename failures. Platform routes and
  membership are not restored from app-owned files. Local backups are not disaster
  recovery; off-server copies and hosted restore drills remain a hosted gate.

## Testing and validation

Unit tests cover names, route rendering, permission checks, credential removal,
command limits and role transitions (PRODUCT 1, 3–7, 11). A real-Docker smoke
script provisions two apps and local identities, writes files through MCP,
starts servers on two ports, tests private/public routes and cross-app denial,
checks restart persistence, and verifies backup/restore (PRODUCT 2–10).

The loopback prototype uses localhost hosts and explicit Host headers in automated
checks. No DNS changes, production credentials, or current services are involved.
Record actual results and known gaps in this document after verification.

## Current verification

See [PROTOTYPE.md](PROTOTYPE.md) and [verification.json](verification.json) for
current results. The demo creates its own SQLite schema and proves that data,
Git history and service configuration survive recreation and workspace restore.
The smoke test also verifies the actual daily scheduler, pruning and restart
persistence. There is no shared Postgres service in the new stack.

Legacy Postgres app records and backup formats are rejected for backup/restore
and recreation until migrated explicitly. No automatic migration or deletion of
old Postgres volumes is performed. This prevents a workspace-only snapshot from
being presented as a complete backup of an older external database.
