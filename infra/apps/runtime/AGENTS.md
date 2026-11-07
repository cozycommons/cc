# App environment

This container is one Cozy Commons app. /workspace persists across replacement.
You may download files, install dependencies, edit code and run multiple services.
Record reproducible dependency setup in /workspace/setup.sh; changes outside
/workspace survive restart but not replacement. Do not put credentials in Git
or public files.

## Application storage

For a fresh app, prefer SQLite at a path such as /workspace/data/app.sqlite3.
It needs no separate server; Python's sqlite3 module and the sqlite3 CLI are
available. This is a recommendation, not a platform requirement. Choose another
engine when the app needs it, and manage its installation, schema and services
inside this sandbox. The platform does not provision databases or DATABASE_URL.

Keep all persistent data under /workspace and out of Git. Platform backups stop
the container and archive this whole directory, including SQLite journal/WAL
files, then resume it. Keep each SQLite database and its sidecars together.
Supervise any database server you install and configure graceful shutdown.
For other engines, document and test recovery with a compatible engine version.
Data outside /workspace, external databases, and installed OS packages are not
included in workspace backups.

Bind web services to 0.0.0.0. Use `commons expose PORT --default` or
`commons expose PORT --name NAME`; add --public only for intentional public access.
`commons unexpose NAME` removes a route; use default for the main route.
Publishing does not start your server. External agents run these same commands
through MCP exec_command. Long commands return a job ID: reconnect with job_id,
after=next_cursor, or cancel=true. Use a unique idempotency_key on starts so retries
return the original job. A running result is not completion. Use transfer_file for
binary files/opaque archives up to 16 MiB; unpack archives using shell. Platform
snapshots are owner-only through app_backups; restore replaces workspace data.

For persistent processes, write /workspace/services/NAME.conf:

[program:NAME]
command=python /workspace/server.py
directory=/workspace
autostart=true
autorestart=true
stdout_logfile=/workspace/logs/NAME.log
stdout_logfile_maxbytes=5MB
stderr_logfile=/workspace/logs/NAME-error.log
stderr_logfile_maxbytes=5MB

Then run `supervisorctl reread && supervisorctl update`.
Use separate code/data when experimenting; every process shares this environment.
Backups, permissions and routing are controlled outside this container.

## Source history and running services

New apps start with a local Git repository on main in /workspace. No remote is
required. You choose your source layout and can move the repository within the
persistent workspace. Keep credentials, runtime data and logs out of Git; the
starter .gitignore is a starting point, not a secret scanner.

Prefer running the live app from a committed main version. Use your own scripts
to build, deploy and restart services; the platform does not deploy on commit or
enforce branch/directory conventions. Before claiming a change is live, check the
actual website and record the running commit when useful. A commit alone does
not restart a process or undo data changes. Keep a way to return to a known-good
version, and document dependency setup, start and recovery commands in this repo.

The repository, .git history and app data under /workspace are included in
workspace backups. A local Git
repo alone does not protect against losing the host. A remote can be added later
without changing the app's deployment workflow.
