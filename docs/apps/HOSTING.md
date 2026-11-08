# Hosted synthetic-data pilot

This is a deployment candidate, not a claim that the platform is live. The first
hosted pilot is restricted to synthetic data. Daily snapshots on the VPS are not
off-server backups. Choose durable external storage and complete a fresh-host
restore drill before storing important data or moving an existing app.

The existing shared frontend, backend, Crowdset and Coolify dashboard keep their
resources and domains. Only the backend needs a normal reviewed release to add
the Apps provider to its existing OAuth connector. Docker access stays exclusively
in the new manager, never the shared backend or app containers.

## Authentication

`APPS_MODE=hosted` explicitly selects hosted settings; invalid/missing settings
fail startup. The local Compose and stdio client retain their loopback guards.

- `apps.cozycommons.dev` is the directory and platform API. Browser sign-in uses
  the existing Supabase project's Google provider with PKCE. Only this central
  callback is allowlisted: `https://apps.cozycommons.dev/_commons/callback`.
  No wildcard Supabase redirect URL is needed.
- The manager validates access tokens at the project's Auth `/auth/v1/user`
  endpoint. It rejects anonymous users and unrelated OAuth client IDs. Identity
  comes from the validated UUID, never email or user-editable metadata. The
  official Commons OAuth client ID must match the backend configuration.
- Browser cookies are Secure, HttpOnly, SameSite=Lax, host-only `__Host-` cookies.
  They contain random references, not Supabase tokens. Central sign-in issues a
  60-second one-use ticket bound to the app hostname and a browser nonce. Tickets
  travel in URL fragments, not request URLs; a same-origin POST redeems them.
- Access tokens, PKCE verifiers, sessions and tickets exist only in bounded
  manager memory. Refresh tokens are discarded. Sessions expire within one hour
  or when their upstream access token expires; manager restart signs browsers
  out. No database stores browser credentials. Private requests revalidate Auth
  and current membership. Auth outages fail closed.
- Central Apps logout revokes that browser's session family across app hosts,
  including in-flight ticket issuance. Per-app logout affects only that host.
  This is Apps logout, not global logout from the existing Commons frontend.
- Cookies authorize browser reads only. Shell, membership and lifecycle APIs
  require bearer authentication. Mutating browser requests have an exact Origin
  check. Caddy strips platform Authorization, proxy credentials and platform
  cookies before forwarding, preserving application-owned cookies.
- Private routes admit contributors by default. Viewers reach a route only when
  it is published with `--viewers`, because an app server can return source or
  `.git` contents. App hosts share one site, so `SameSite=Lax` does not stop one
  app's page from sending a member's cookie to another app. Route authorization
  refuses requests whose `Origin` is a different app. Without `Origin`, it
  admits same-origin requests and top-level navigations; cross-origin
  subresources and frames need a `Referer` on the same app. Browsers without
  Fetch Metadata (Safari before 16.4, Firefox before 90) therefore need that
  `Referer` even to navigate. Services of the same app (`trip` and
  `trip--api`) may call each other.
- Bearer requests must also carry `X-Commons-Apps-Caller`, a secret only the
  shared backend and the manager hold. A user's Supabase token alone, such as
  a frontend session token, cannot reach shell or membership APIs. App
  container capabilities do not use this header.
- Login allocation is globally limited to 60/minute. Auth validation is limited
  to 600/minute and four concurrent requests. These protective budgets are global
  behind TCP passthrough, not per-client fairness; overload temporarily rejects
  authentication. No successful identity cache delays membership checks.
- The existing `/mcp` connector adds exactly `list_apps`, `create_app`,
  `set_app_member`, `exec_command`, `transfer_file`, and `app_backups`. Enable the Apps project in the connector.
  Every call passes project enablement and scope checks. Shell requires
  `commons:edit`, even for a read-only command. The bridge forwards the validated
  upstream token over HTTPS; no tool accepts a token argument. Manager app
  permissions and current Commons admin creation permission are checked independently.
- All current Cozy Commons admins can create apps. Every creation calls the
  existing `https://api.cozycommons.dev/admin/session` with the validated user's
  token; its authoritative role check must succeed for the same UUID. Promotion
  and demotion take effect on the next creation; failures deny allocation. No
  admin UUID list or service-role key is copied into the manager. Owner grants
  use exact UUIDs confirmed by the person, not name/email search.
  The directory displays the caller's own UUID. A grant to a nonexistent UUID
  gives no one access; that UUID can never be selected by a user.

Contributors remain trusted with all code/data in their app. Revocation does not
remove backdoors, kill existing WebSockets, or rotate copied app capabilities;
recreation rotates the publication capability. This is not hostile-tenant hosting.

## Coolify preparation

Read-only inventory on 2026-11-06 (America/New_York): Coolify 4.6.0, Production VPS
`8isyiuhtt8pgsi2l2tn47e8y`, Cozy Commons project
`myslnzrcuucdffkthj0tswam`. Backend, frontend and Crowdset were healthy; no Apps
resource, service or database existed. Traefik was v3.6, with `https` on 443,
HTTP-01 ACME, and a watched `/traefik/dynamic/` file provider. No TLS-ALPN challenge
handler was configured. Recheck these facts at rollout time.

1. Complete the independent reviews required by `docs/security.md`. Do not merge
   or expose this security-sensitive change before those reviews pass.
2. Inspect actual host memory/disk and unmanaged Docker resources. Ensure the
   `cc-apps-hosted-*` names and network/volumes are unused. On this 2-CPU/4-GiB VPS,
   build one image at a time and monitor actual headroom. App defaults remain
   512 MiB, 1 CPU cap and 256 PIDs; there is no total-memory allocation gate.
   Manager has a 512-MiB bound; Caddy has a 128-MiB bound. Backups use helpers
   with the existing 256-MiB limit. Disk must hold workspace, three snapshots,
   and staged extraction plus old files during restore.
3. Create a separate candidate Compose resource from the reviewed commit,
   base directory `/`, Compose path `/infra/apps/hosted/compose.yaml`.
   Disable automatic deployments. Coolify invokes Compose with the repository
   root as its project directory; build contexts are consequently `.`.
4. Configure these values on the new resource. All but the last are public:

   ```dotenv
   APPS_DOMAIN=cozycommons.dev
   APPS_SUPABASE_URL=https://dhjnrnhjghsulbevfhno.supabase.co
   APPS_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
   APPS_MCP_OAUTH_CLIENT_ID=cf9b18d4-f3e8-44cb-8d13-0f23e591ce3b
   APPS_RUNTIME_IMAGE=cc-apps-runtime:<reviewed-commit>
   APPS_MANAGER_CALLER_SECRET=<openssl rand -hex 32, generated for Apps only>
   ```

   Use the existing frontend's publishable key. The caller secret is new and
   shared only with the backend (step 8). Do not copy shared backend secrets,
   the service-role key, OAuth client secret or any production dotenv into
   this resource. There are no secret host-file mounts. Coolify can append
   resource environment values to every service: verify no inherited secrets.
5. Build the runtime image on the target daemon **before creating an app**:
   use the `build` profile's `runtime-image` service, or build the runtime
   Dockerfile with the exact configured image tag. Normal Compose startup does
   not build a profiled-out service. Record manager, proxy and runtime image
   digests. Do not rely on the helper leaving its checkout on the host.
6. Inspect Coolify's generated Compose before starting: exact manager/proxy
   container names and state/workspace naming are required. Preserve
   `cc-apps-hosted-state`, `cc-apps-hosted-proxy-config`, Caddy certificate volumes,
   and the manager's `manager` DNS alias. Run one manager worker. Keep
   `--no-access-log` to prevent callback codes appearing in request logs.
   Manager must not be attached to the existing proxy network. Attach **only
   Caddy** to that network with stable alias `cc-apps-hosted-proxy`. There must
   be no published host ports or generated HTTP/TLS router labels for this stack.
7. Add the central callback above to the Supabase Auth redirect allowlist,
   retaining all existing entries. Google sign-in must already be enabled.
   Confirm no wildcard app callback is added and no production auth secrets change.
8. Set backend runtime `APPS_MANAGER_URL=https://apps.cozycommons.dev` and the
   same `APPS_MANAGER_CALLER_SECRET`, then deploy the reviewed backend through
   its existing workflow. Without the secret, Apps tools report that hosting is
   not configured. Set it on the backend before restarting a manager that
   requires it. The exact Apps
   host is included in `deploy/api-egress/hosts.txt` for the egress topology;
   do not weaken its policy or independently migrate the backend topology.

The new manager writes its route config before reporting healthy; Caddy waits
for that healthcheck on initial startup. Backups and app workspaces use separate
hosted names. Local `scripts/apps-dev.sh stop` skips hosted instance labels.

## DNS and TLS

DNS currently uses Namecheap's `registrar-servers.com` nameservers. At inspection,
`apps.cozycommons.dev` and a synthetic app hostname returned NXDOMAIN. Add A
records `apps` and `*` pointing to the VPS (`15.204.237.98` at inspection).
Preserve all explicit existing DNS records. Do not add AAAA unless IPv6 reaches
this VPS and its ingress. Re-inventory custom subdomains before adding wildcard
routing; an unrelated custom subdomain must be excluded and reserved first.

The hosted Compose supplies additive Traefik TCP labels on Caddy and attaches
only Caddy to the existing `coolify` network (`APPS_PROXY_NETWORK` can select
another inspected network). Enable Coolify raw Compose deployment to preserve
these labels, names and networks. Do not add a separate dynamic router too.
`infra/apps/hosted/traefik-dynamic.yaml` is an alternative template for hosts
without the Docker provider; it is not needed for this VPS. It
matches one subdomain label and explicitly excludes reserved platform hosts.
The apex and `www.api.cozycommons.dev` are not matched. The Docker provider discovers these labels without replacing the existing
proxy configuration or restarting Traefik.

Traefik passes TLS through to Caddy. Caddy obtains individual certificates for
registered app routes and the portal using TLS-ALPN-01; it does not enable
on-demand issuance for arbitrary hosts. This avoids needing a wildcard
certificate or DNS API credential. The live Traefik must not intercept
`acme-tls/1` using its own TLS challenge handler. Existing HTTP-01 on Traefik
remains intact. Port 443 must reach Caddy through the TCP router, including ACME
handshakes. Certificate state is durable in `cc-apps-hosted-caddy-data`.

Caddy's admin API stays on container loopback. Unpublished app ports have no host
bindings. App-host `/_commons/*` belongs to the platform. Internal app publication
uses only the `http://proxy/api-control` route and its app-scoped capability.
That route forwards only `PUT`/`DELETE` on `/api/apps/<app>/routes/<name>`;
other manager paths are not reachable through it from the proxy's networks.

App bridges are named `ccapp<hash>`. Before admitting contributors you would
not trust with the host, drop app traffic addressed to the host itself (the
Coolify dashboard, SSH and anything else bound on all interfaces):
`iptables -I INPUT -i ccapp+ -j DROP`, persisted with the host's firewall
tooling. Forwarded egress and container-to-container traffic should be
unaffected; confirm DNS, package installs and published routes still work.
Apps created before this naming keep Docker's default bridge names until
recreated with a new network. This rule has not been applied to the VPS yet.

## Acceptance and rollback

Before exposing the router, inspect generated Compose, Docker port bindings,
networks, mounts, labels and image digests without dumping environments. Check
existing backend/frontend/Crowdset and admin HTTPS before and after each change.

Use a new synthetic app. Verify Google/PKCE login, portal directory, two users'
viewer/contributor/owner permissions, current Commons admin creation permission, the OAuth MCP
tools, private/public HTTP and WebSockets, `commons expose/unexpose`, header and
cookie stripping, membership revocation, central logout, shell timeouts and
bounded output. Verify local Git, SQLite persistence, restart/recreate, manual
backup and staged restore. Inspect the daily scheduler and three-snapshot
retention. Obtain/renew a real certificate through the exact production routing
path before calling TLS deployment complete.

Rollback removes only the new additive TCP router, stops the new manager,
stops containers selected by `cc.apps.instance=cc-apps-hosted-`, and stops the
new Caddy. Retain workspace/state/backup/certificate volumes and known-good
images. Unset the backend's Apps URL to make the provider unavailable if needed;
other projects remain independent. Never run `docker compose down -v`, prune
shared resources, or use a blanket `cc.apps` stop command.

The off-server destination and fresh-host recovery drill remain outstanding.
No important or existing application data may enter this pilot until complete.

## Candidate verification

Local verification on 2026-11-06 (America/New_York):

- 275 runtime, shared MCP, tool authorization and egress tests passed; one existing
  test skipped. The tool safety suite also passed with Docker imports blocked,
  matching the shared backend's dependency boundary.
- The existing real-Docker prototype smoke passed all 64 acceptance checks,
  including daily scheduling, three-successful-snapshot retention and restore.
- Hosted Compose rendered with synthetic configuration: root build contexts,
  no published ports, persistent certificate/state volumes, and disabled manager
  access logging verified. The manager image built successfully.
- Caddy 2.10.2 accepted the generated hosted configuration. Real Traefik v3.6
  TCP passthrough to Caddy passed certificate-verified requests using a local CA.
  Forwarding removed platform Authorization/cookies and a spoofed internal
  header while preserving application cookies; denied authorization redirected.
- Chromium exercised the browser ticket completion script with synthetic Auth
  responses: fragment removal, Secure/HttpOnly cookie installation and replay
  rejection passed. Real Google sign-in and public ACME issuance are deployment
  acceptance checks, not claimed by this local test.
- A supplemental independent review passed after fixing logout-family races,
  unrelated OAuth client acceptance, authentication work bounds, input-echoing
  validation, instance-scoped stopping and access-log exposure. The current-admin
  authorization follow-up also passed.

No production resource, DNS record or Supabase configuration was changed during
this verification. A requested local-browser DNS delegation could not proceed:
the cloud execution surface exposed no local-browser or local-agent dispatch tool.

## Coolify 4.6 rollout settings

Use raw Compose (`is_raw_compose_deployment_enabled=true`) with automatic
deployment and predefined-network attachment disabled. The Compose attaches only
Caddy to ingress. Custom build command: `docker compose --parallel 1 build manager proxy
runtime-image`. Explicit targets build the runtime image as well as manager/Caddy,
one build at a time. Start normally with the build profile disabled. The public
interpolation variables must be available at build and runtime. Inspect the
rendered definition before starting.
