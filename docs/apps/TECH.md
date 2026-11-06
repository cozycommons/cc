# Apps prototype technical design

## Context

The approved direction is in [README.md](README.md); observable behavior is in
[PRODUCT.md](PRODUCT.md). Current shared deployment policy permits a separate
runtime for persistent state and independently managed processes. This prototype
requires privileged container lifecycle operations, so it is separate from the
shared FastAPI API and does not mount Docker access into that existing service.

## Proposed changes

- `backend/app_runtime`: a single-process FastAPI runtime manager, Docker driver,
  SQLite registry, CLI and stdio MCP adapter. SQLite holds platform metadata,
  not app data. The manager alone receives Docker and Postgres admin access.
- `infra/apps`: reproducible Docker Compose manager, Caddy and local Postgres,
  plus a Python/Node/Git/supervisor image for app environments.
- Creating a new app initializes a local Git repository on main after starting
  its container. Starter AGENTS.md and .gitignore are the first commit. This
  initialization runs only during new app provisioning, not on restart or
  recreation; existing app files and history are not reseeded.
- MCP exposes list_apps, create_app, set_app_member and exec_command through the
  existing manager API. File operations and publishing use the app shell.
  APPS_CREATORS controls who can allocate new apps independently of app roles.
- Each app gets a named workspace volume and its own Docker bridge network.
  Only its app container, shared proxy and Postgres join that network. The
  manager reaches Docker via its socket, never exposes it to an app, and only
  accepts bounded, validated application operations.
- Postgres has one non-superuser role and database per app. Apps receive only
  their own database credentials. The platform database/role is not exposed.
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
- Backups stop the app, dump its database and archive its workspace using a helper
  container. Restore is explicit and occurs while stopped. Platform routes and
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

## Verified locally — 2026-11-04

- 25 focused unit/API tests passed on macOS with Python 3.14.
- 33 real-Docker acceptance checks passed against the Python 3.12 manager,
  Caddy and Postgres: actual stdio MCP calls, shared membership, two HTTP
  services, credential stripping, cross-app network/database denial, package
  installation, WebSockets, bounded shell commands, restart/replacement, and
  coordinated workspace/database restoration.
- The WebSocket test caught upgrade headers leaking into the forward-auth
  request. The proxy now removes Upgrade and Connection only on the auth check;
  the downstream service still receives its WebSocket upgrade.
- Visually inspected the synthetic read-only demo in the in-app browser.
- Bash syntax and Python compilation checks passed. The dedicated CI workflow
  repeats setup, unit tests and Docker smoke on Ubuntu; that remote run is not
  claimed as verified yet.

The management directory is served by the standalone local manager. Integrating
management into the shared React frontend remains a hosted-pilot task. No
production deployment, real-domain routing, remote OAuth, cloud-agent account
connection or off-server recovery has been validated.

References: [Docker exec](https://docs.docker.com/reference/cli/docker/container/exec/),
[Caddy forward_auth](https://caddyserver.com/docs/caddyfile/directives/forward_auth),
[Caddy reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).

## Agent-owned operation

App Git repositories live on persistent storage inside their app environments.
A remote Git provider is optional. CC contains platform code and starter assets;
app source does not need to be checked into CC. Agents choose deployment scripts,
source layout, process configuration and restart commands. The starter recommends
committed main as the live source, but no platform hook enforces it or deploys on
commit. Backup includes .git because it archives the entire workspace.

## Local Git iteration — 2026-11-04

26 focused unit/API tests and 43 real-Docker acceptance checks passed. Additional
coverage creates and shares an app through MCP, verifies a clean local main with
an initial commit and no remote, commits app source before starting services,
and checks that recreation and coordinated restoration preserve .git and the
expected main commit. The setup launcher now tolerates transient empty HTTP
responses while the manager starts. This is a local prototype; hosted agent
authentication and deployment remain separate follow-up work.
