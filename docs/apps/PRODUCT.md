# Apps prototype

Hosted candidate configuration and its separate rollout gates are documented in [HOSTING.md](HOSTING.md). The local workflow below remains unchanged.

## Summary

One purpose-oriented app has one persistent Docker environment. External agents
can use its shell and files, run arbitrary supporting processes, and publish
selected HTTP ports. People can share stewardship and use the resulting sites.
This first implementation is a local prototype with synthetic data, not a VPS
release or a migration of existing projects.

## Behavior

1. A person with platform creation permission creates an app with a unique
   lowercase slug. Platform names such as admin, api, auth and www are reserved;
   `--` is reserved for named services.
2. Each app has persistent workspace files and developer tools. Storage engines
   and schemas belong to the app; starter guidance recommends SQLite under
   /workspace/data, without requiring it. No database is provisioned by the platform. New apps start with a local Git repository on main, a starter
   AGENTS.md, a .gitignore and an initial commit. No remote Git service is needed.
   The agent chooses its layout within persistent storage. Contributors are
   trusted with all app files, processes and data.
   They cannot administer the platform or another app through platform tools.
3. External agents use four MCP tools: list_apps, create_app, set_app_member,
   and exec_command. Execution waits and returns a bounded result; agents use
   shell commands for file operations and `commons expose/unexpose` for routing.
   Shell is not a per-file permission model.
4. Owners can add known local users as contributors or viewers. Contributors
   may edit and publish; viewers may only list and use authorized apps. Owners
   manage membership, lifecycle and recovery. Credentials are local prototype
   credentials; hosted OAuth and browser session integration are later work.
   App creation permission is separate from membership in an existing app and
   is granted through platform configuration, not by app contributors.
5. An agent publishes a port as default or with a service name. The default
   address is `<app>.localhost`; named addresses are `<app>--<service>.localhost`.
   All use the prototype proxy port. Hosted addresses will use cozycommons.dev.
6. Published routes are private unless explicitly made public. Private routes
   require app membership; public routes need no sign-in. Platform credentials
   are removed before forwarding requests to app servers. HTTP and WebSockets
   are supported. Unpublished ports have no host port bindings.
7. Publishing updates or removes a route without imposing live/preview semantics.
   A stopped or unavailable server returns a gateway error. A route can be
   registered before the server starts. No automatic database promotion occurs.
8. Contributors can install dependencies and run multiple processes in one
   container. Registered services restart with the container. Persistent files
   survive restart and recreation; ad-hoc OS installs require reconstruction.
9. The manager backs up each app's workspace (including app-owned data) every 24 hours and
   retains its three newest successful backups. Owners may also back up manually;
   these snapshots share the limit and reset the daily interval. Failed backups
   preserve good snapshots and retry. Running apps pause briefly; stopped apps
   stay stopped. Owners list retained backups and choose a restore point.
   Restore replaces the workspace from a selected backup,
   including the local repository and .git history, leaving membership and
   routing under platform control. Restore is explicitly destructive to newer
   app data; backups are retained outside app access.
10. The local setup binds published host ports only to loopback, uses generated
    credentials and synthetic data, and does not read production dotenv files.
11. App callers cannot grant themselves access, publish another app's hostname,
    inject proxy configuration, or select host paths/Docker options.
12. Invoking an agent from the app, hosted OAuth/TLS, off-server backup retention,
    automated rollback, and simultaneous edit coordination are deferred.
13. Starter guidance recommends operating the live service from committed main.
    The agent owns deployment, builds, process management, checks and restarts.
    Commits do not trigger platform deployments. There are no required dev/release
    directories or automatic Git checkpoints. Remote Git can be added later.
14. Existing CC projects stay in place. The prototype hosts newly created apps;
    a consolidated shared app may hold several simpler projects when appropriate.
