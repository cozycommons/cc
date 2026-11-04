# App environment

This container is one Cozy Commons app. /workspace persists across replacement.
You may download files, install dependencies, edit code and run multiple services.
Record reproducible dependency setup in /workspace/setup.sh; changes outside
/workspace survive restart but not replacement. The app's DATABASE_URL gives full
access to its database. Do not put credentials in Git or public files.

Bind web services to 0.0.0.0. Use `commons expose PORT --default` or
`commons expose PORT --name NAME`; add --public only for intentional public access.
`commons unexpose NAME` removes a route; use default for the main route.
Publishing does not start your server. External agents can also use MCP tools.

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
