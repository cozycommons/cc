# Run the local apps prototype

This runs separate local Docker services. It does not deploy to the VPS, modify
DNS, read production dotenv files, or migrate current Cozy Commons apps.
Docker Engine/Compose and Python 3.12+ are required. Scripts work on macOS and
Ubuntu with Bash 3.2+. Run commands from this checkout's root.

## Start

```bash
scripts/apps-dev.sh setup
scripts/apps-dev.sh start
scripts/apps-dev.sh smoke
```

Setup creates ignored `.apps-dev/` credentials and a Python environment, then
builds the manager and app images. Start launches Caddy, the manager and Postgres;
only `127.0.0.1:8090` (proxy) and `127.0.0.1:8091` (manager) are published.
The local namespace uses `<app>.localhost:8090`, not real cozycommons.dev DNS.
Some clients do not resolve wildcard localhost; use `curl --resolve` or an
explicit Host header to 127.0.0.1 in those clients.

Smoke creates two synthetic apps with unique names. It leaves a trip demo
running and stops the second app. `.apps-dev/smoke-result.json` records its URL
and checks. Re-running creates additional fixtures; it does not overwrite any
existing app. Browser access to the private demo uses username `owner` or
`viewer` and that user's token from `.apps-dev/users.json` as the password.
The local app directory is at `http://admin.localhost:8090` (or the direct
manager URL). It lists apps and published services; provisioning uses the CLI.

## Use an external agent

A local MCP-capable client can launch this stdio server:

```bash
scripts/apps-dev.sh mcp
```

Use the script's absolute path in the client's server configuration. Set
`COMMONS_USER=friend` to connect as the second local identity; the default is
`owner`. The wrapper reads only the generated local credential file. Tools:
`list_apps`, `exec_command`, `read_job`, `read_file`, `write_file`, `expose_port`,
`unexpose_port`. Shell commands return a job ID and retain up to 64 KiB of output.

This is real MCP, tested with a protocol client, but it is **local stdio**, not a
hosted ChatGPT/Claude OAuth connector. Remote agent product connections are a
hosted-pilot milestone, and no product account integration is claimed here.

## Create and share an app

```bash
scripts/apps-dev.sh cli create weekend
scripts/apps-dev.sh cli grant weekend friend contributor
scripts/apps-dev.sh cli grant weekend viewer viewer
scripts/apps-dev.sh cli exec weekend 'ls -la /workspace'
scripts/apps-dev.sh cli job weekend JOB_ID
```

Known local identities are owner, friend, viewer and outsider. Each may own its
own apps. App owners grant contributor/viewer access to other known identities;
`grant APP USER none` revokes membership. Owner transfer is deferred. This local
identity system is a test seam, not a substitute for hosted OAuth.

Contributors have full access to the app's code and data, including its database
password. A contributor who behaves maliciously can modify the app or leave a
backdoor; this prototype is for trusted collaborators, not hostile tenants.
The app's internal publication token is restricted to its own route operations;
it cannot execute commands through the platform or manage membership. Revoking a
person's membership does not invalidate an app capability they previously copied;
recreate rotates that capability. Trusted contributors can also leave processes
behind, so membership revocation alone is not eviction of a hostile contributor.

## Run and publish services

Agents find instructions in `/workspace/AGENTS.md` and can use Git, shell, Python,
Node/npm, curl and Postgres tools. Put persistent content under `/workspace`.
The app's own `DATABASE_URL` is available in its environment.

For services that should restart automatically, write a supervisor definition
under `/workspace/services/` and run `supervisorctl reread && supervisorctl update`.
The generated AGENTS.md includes an example. Bind servers to `0.0.0.0` inside the
container; unpublished ports are not bound on the host.

From inside the app container:

```bash
commons expose 3000 --default
commons expose 8080 --name experiment --public
commons unexpose experiment
```

From the host:

```bash
scripts/apps-dev.sh cli expose weekend 3000
scripts/apps-dev.sh cli expose weekend 8080 --name experiment --public
scripts/apps-dev.sh cli unexpose weekend experiment
```

These produce `weekend.localhost:8090` and
`weekend--experiment.localhost:8090`. Private is the default. Platform names
including admin, api, auth and www are reserved; app/service names cannot include
`--`. There is no designated preview port or special preview behavior.
HTTP and WebSocket routes use Caddy. The proxy strips platform Authorization
headers; app-specific authentication must use a different mechanism, such as
its own cookies. Existing WebSocket connections are not forcibly disconnected
when membership changes; authorization applies when a connection is established.

## Lifecycle and recovery

```bash
scripts/apps-dev.sh cli restart weekend
scripts/apps-dev.sh cli recreate weekend
scripts/apps-dev.sh cli backup weekend
scripts/apps-dev.sh cli restore weekend BACKUP_ID --confirm-replace-data
scripts/apps-dev.sh cli stop weekend
scripts/apps-dev.sh cli start weekend
```

Recreation replaces the container while retaining workspace and database; it
rotates the internal publication token. Ad-hoc packages installed outside the
workspace are lost. Record dependency installation in `/workspace/setup.sh` and
run it after replacement, or use dependencies in a workspace-local environment.
It is not run automatically. Ordinary restart retains the container's writable
layer, while registered services restart in either case.

Backup briefly stops the app to dump its database and archive its workspace.
Restore explicitly replaces both, keeps platform membership/routing, and leaves
the app stopped if restoration fails. Backups cover files/database, not installed
OS packages, process memory or live connections. The local implementation buffers
Postgres dumps in memory and is intended for small synthetic data sets.

Backups live in the manager's Docker volume outside the app's filesystem.
They are not off-server disaster recovery. Production hosting needs durable
external backups, capacity planning, TLS, OAuth and a fresh-host restore drill.
Do not delete the Docker volumes if you want to retain local app data.

```bash
scripts/apps-dev.sh stop
```

This stops the platform and its labelled app containers, retaining volumes.
After starting the platform again, explicitly start any apps you want running.

## Checks

```bash
PYTHONPATH=backend .apps-dev/venv/bin/python -m pytest backend/app_runtime/tests/test_core.py backend/app_runtime/tests/test_api.py -q
scripts/apps-dev.sh smoke
```

The smoke test exercises real Docker, Postgres, Caddy, the MCP protocol, separate
identities, two HTTP ports, WebSockets, isolation, bounded shell execution,
container restart/replacement and file/database recovery.

## Captured example

![Synthetic trip app served through a dynamically published port](images/prototype.png)

[Recorded local acceptance checks](verification.json).
