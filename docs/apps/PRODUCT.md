# Apps prototype

## Summary

One purpose-oriented app has one persistent Docker environment. External agents
can use its shell and files, run arbitrary supporting processes, and publish
selected HTTP ports. People can share stewardship and use the resulting sites.
This first implementation is a local prototype with synthetic data, not a VPS
release or a migration of existing projects.

## Behavior

1. An owner creates an app with a unique lowercase slug. Platform names such as
   admin, api, auth and www are reserved; `--` is reserved for named services.
2. Each app has persistent workspace files, developer tools and a separate
   database. Contributors are trusted with all app files, processes and data.
   They cannot administer the platform or another app through platform tools.
3. External agents can list authorized apps, execute shell commands, poll their
   results, and read/write UTF-8 files through generic MCP tools. Commands have
   bounded duration and retained output. Shell is not a per-file permission model.
4. Owners can add known local users as contributors or viewers. Contributors
   may edit and publish; viewers may only list and use authorized apps. Owners
   manage membership, lifecycle and recovery. Credentials are local prototype
   credentials; hosted OAuth and browser session integration are later work.
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
9. Owners can stop/start an app and take a consistent maintenance-window backup
   of workspace and database. Restore replaces both from a selected backup,
   leaving membership and routing under platform control. Restore is explicitly
   destructive to newer app data; backups are retained outside app access.
10. The local setup binds published host ports only to loopback, uses generated
    credentials and synthetic data, and does not read production dotenv files.
11. App callers cannot grant themselves access, publish another app's hostname,
    inject proxy configuration, or select host paths/Docker options.
12. Invoking an agent from the app, hosted OAuth/TLS, off-server backup retention,
    automated rollback, and simultaneous edit coordination are deferred.
