# API outbound destination inventory

The optional Compose deployment in `deploy/api-egress/compose.yaml` confines the
shared `backend/main.py` API. It replaces the current Dockerfile-only topology
only after a separately approved rollout. `hosts.txt` contains exact HTTPS
hostnames, without suffix or wildcard grants. The deployed Supabase project and
database host are configuration inputs because the repository does not identify
the live project. No production configuration or credentials were read to build
this inventory.

## Destinations used by the API

All HTTPS destinations use TCP 443 through Squid. PostgreSQL uses a separate
fixed-target TCP 5432 relay because libpq/psql do not use HTTP proxies.

| Destination | Runtime caller and evidence |
| --- | --- |
| Exact `SUPABASE_URL` hostname, configured as `EGRESS_SUPABASE_HOST` | `backend/main.py:43`, `backend/main.py:89` create the supabase-py clients for PostgREST, Auth, Storage and Functions on the same project origin. HTTP clients inherit proxy settings. No API caller subscribes to Realtime. |
| Exact shared session pooler hostname, configured as `EGRESS_DB_HOST` | `backend/release.py:15`, `backend/migration_runner.py:163` start psql migrations; `backend/admin/query.py:94` and `backend/admin/query.py:122` use `ANALYTICS_DATABASE_URL` through psycopg; `backend/admin/routes.py:78` tests that connection. Both DB URLs must target this same host and port 5432. |
| `backoffice-service-t57o3dxfca-nn.a.run.app` | `backend/ig_logger/sinks/beli/beli_client.py:32`, `backend/ig_logger/sinks/beli/beli_client.py:155` use urllib for Beli operations. |
| `backoffice-service-onboarding-t57o3dxfca-nn.a.run.app` | `backend/ig_logger/sinks/beli/beli_client.py:33`, same urllib transport. |
| `api.resy.com` | `backend/resy/resy_client.py:39`, `backend/resy/resy_client.py:146`. `resy.com` is only an Origin/Referer header, not a destination. |
| `lm-api-reads.fantasy.espn.com`, `lm-api-writes.fantasy.espn.com` | `backend/espn/espn_client.py:89`, `backend/espn/espn_client.py:90`, urllib at lines 366 and 431. |
| `registerdisney.go.com`, `fan.api.espn.com` | `backend/espn/disney_login.py:60`, `backend/espn/disney_login.py:62`, urllib at line 110. These are the MyDisney login and ESPN cookie bootstrap hosts used by this implementation. No other Disney login origin is called. |
| `site.api.espn.com` | `backend/espn/scoreboard.py:50`, `backend/espn/scoreboard.py:210`, public NBA scoreboard. |
| `apps.cozycommons.dev` | `backend/app_runtime/agent_tools.py` forwards the authenticated Commons OAuth caller to the separate Apps manager. No wildcard app destinations are allowed. |
| `gist.githubusercontent.com` | `backend/espn/team_claims.py:31`, `backend/espn/team_claims.py:56`, public predictions fallback. Overriding `ESPN_PUBLIC_PREDICTIONS_FALLBACK_URL` requires explicitly reviewing and adding its exact hostname. |
| `api.open-meteo.com` | `backend/bikes/conditions.py`: Central Park hourly forecast (no key), cached 30 min, 4 s timeout, 1 MB cap; failure leaves Cozy Bikes rates unadjusted. |
| `gbfs.lyft.com` | `backend/bikes/gbfs.py:15`, `backend/bikes/gbfs.py:30`, Citi Bike's public GBFS station feeds via urllib, cached 60 s (status) and 1 h (locations). |
| `display.safespace.io` | `backend/vital/feed.py`, VITAL Brooklyn's live headcount as plain text (no key) via urllib, cached 60 s, 4 s timeout, 64-byte cap; failure returns 503 from `/vital/now`. `vital.recorder` polls the same URL offline. |
| `api.partiful.com` | `backend/partiful/partiful_client.py:39`, `backend/partiful/partiful_client.py:142`. `partiful.com` is only an Origin/Referer header. |
| `identitytoolkit.googleapis.com`, `securetoken.googleapis.com` | `backend/partiful/partiful_client.py:41`, `backend/partiful/partiful_client.py:45`, Firebase token exchange and refresh via the same urllib transport. |
| `api.twilio.com` | `backend/dice/notifications.py:70` constructs the default `twilio.rest.Client`; `backend/requirements.in:16` locks Twilio through requirements.txt. Twilio 9.6.5 `twilio/rest/api/ApiBase.py:27` constructs `https://api.twilio.com`; `twilio/http/http_client.py:40` creates a Requests Session. No region/edge override is configured. |
| `account.venmo.com` | `backend/venmo/profiles.py:132`, `backend/venmo/venmo_client.py:71`, HTTPX profile lookup without redirects. |
| `pics-v3.venmo.com` | `backend/venmo/profiles.py:20` accepts only this image origin; `backend/venmo/photos.py:34` retrieves thumbnails through the same HTTPX client. |

## Investigated destinations outside this boundary

Instagram is fetched on a separate fetch box, not by the shared API.
`backend/ig_logger/routes.py:92` documents polling and completion;
`backend/ig_logger/routes.py:141` ingests caller-supplied captions.
`backend/requirements.in:10` includes Instaloader 4.15.3 but no backend runtime
imports it. Its dependency implementation uses `www.instagram.com` and
`i.instagram.com` (`instaloader/instaloadercontext.py:387`, `:611`); these are
**not allowed** in the API. Instagram media CDN destinations therefore also do
not belong here. Moving the fetch box into the API requires a new policy review.

The Cozy Bikes ingest (`backend/bikes/ingest.py`) downloads from
`s3.amazonaws.com`, the basemap builder from `download.bbbike.org`, and the model
builder from `archive-api.open-meteo.com`, all as offline commands, not from the
API; they are outside this boundary.

Crowdset and compute have separate entrypoints, not mounted by `main:app`.
Their configurable R2, Supabase, compute/worker transfer URLs and YouTube media
traffic (`backend/crowdset/r2.py:118`, `backend/crowdset/hosting.py:39`,
`backend/crowdset/remote_agent.py:50`, `backend/crowdset/youtube.py:36`,
`backend/compute/client.py:17`) are excluded. The GPU updater's GitHub origins
(`backend/crowdset/gpu_updater.py:213`, `:229`) are also outside this API.
Browser navigation, OAuth callback URLs, image URLs returned to clients, and
Origin/Referer strings are not API egress. Build-time apt/PyPI traffic happens
before credentials exist and is outside the runtime network policy.

## Boundary and residual risk

The API shares only the network namespace of a trusted `netguard` container.
The namespace has an internal Docker network (plus any resource networks
Coolify adds) and default-deny IPv4/IPv6 OUTPUT,
INPUT and FORWARD rules. INPUT 8000 accepts only the internal ingress subnet
172.30.87.0/24 and loopback, not other Coolify network sources. Only new outbound TCP connections to Squid:3128,
DB-relay:5432, loopback API health endpoint:8000 and loopback proof:8001 are allowed. Existing
connections can carry replies. No capability, Docker socket, host namespace,
sidecar filesystem or API credential is shared with a sidecar. The daemon binds
the raw runtime file only into API; a small nonroot entrypoint loads it before
release or a scheduled command. Coolify/helper environments contain public
interpolation values only. This describes container/CLI delivery, not a guarantee
that Coolify never stores the bind content: older v4 parsers register a
LocalFileVolume and can read/write the path through storage jobs. The runbook's
pre-secret Storages gate must pass for the installed version. Privileged Coolify
administrators and its host file-access jobs remain trusted. API processes
cannot change the firewall, including after changing proxy environment variables.
DNS UDP/TCP 53 is dropped before Docker's resolver DNAT; all other new sockets,
including attempts to use the resolver's translated port, are denied by default.
Only trusted sidecars resolve names. HTTPX, urllib, Requests/Twilio and the
supabase-py HTTP clients inherit `HTTPS_PROXY`; the smoke test exercises these
libraries from the hash-locked API image. A client that ignores proxies fails
closed. Supabase Realtime websocket use is not implemented or verified here.

Squid accepts CONNECT on port 443 only, checks the exact CONNECT name without
DNS lookups, rejects private/reserved destination addresses, peeks the TLS
ClientHello and rejects unlisted SNI before splicing. It never decrypts permitted
traffic or installs a CA in the API. Squid's access-denied responses may present
an ephemeral self-signed TLS error certificate, so rejection can surface as a
certificate error instead of HTTP 403. Do not trust that certificate. No suffix
grants allow `secret.api.resy.com` or another Supabase HTTPS project hostname.
The hostname rule does not restrict Firebase tenant/account operations in TLS.
Logs record CONNECT authorities and SNI, never HTTPS paths, bodies or auth headers.
Restrict log access: an attacker can encode secrets in a rejected hostname.

This is destination confinement, **not a promise that a hostile package cannot
leak secrets anywhere**. A compromised API can still send secrets to an allowed
host (including an attacker-controlled account on that host), write through its
Supabase service key, use the permitted database, or put secrets in an inbound
HTTP response. TLS domain fronting on shared infrastructure and encrypted
application payloads are not filtered. SNI-less TLS falls back to the CONNECT
name in Squid; encrypted ClientHello is not inspected. Stronger guarantees need
credential isolation and narrowly scoped operations outside the compromised
process, or provider/path/account-aware mediation with TLS termination. The API
and its privileged Supabase key remain one trust boundary in this change.

The allowed shared `*.pooler.supabase.com` endpoint is a **cross-project drop
channel**: a rogue package can connect with its own credentials and write to
**any Supabase project served by that pooler**, because the tenant is selected
by the PostgreSQL username inside opaque TLS. Restricting the pooler hostname
or preserving the application's username in its URL does not prevent this.
Closing this database channel requires a project-dedicated database host, such
as a paid dedicated pooler or IPv4 add-on, with a separately reviewed relay
policy. This implementation accepts only shared session pooler hostnames and
explicitly rejects `db.<ref>.supabase.co`; it does not claim tenant isolation.

`identitytoolkit.googleapis.com` (including Firebase `signUp`) and
`api.twilio.com` are also open drop channels. A rogue process can use its own
project/account and put secrets in accepted request data or messages. These
requests are permitted even in enforce mode. **Same-zone domain fronting on
supabase.co is unverified**. The proxy inspects CONNECT/SNI, not encrypted HTTP
Host headers, paths, bodies or database usernames. None of these channels is
closed by the passing direct-egress and DNS tests.

Audit mode deliberately allows unlisted public HTTPS names and their DNS
lookups, while logging `policy=unlisted`. It is **not** a containment guarantee.
Audit is hostname-only: the API firewall and raw DNS denial are active in both
modes. Watch `iptables -nvL OUTPUT` DROP policy/rule counters as well as proxy
logs to detect blocked direct, DNS and non-443 client traffic. Enforce mode denies
unlisted CONNECT names before any destination DNS resolution. The fixed DB relay
is identical in both modes. The Docker host, trusted sidecars, image build,
Coolify administrators and kernel are trusted; host/container escape is outside
this threat model.

## Verification and policy maintenance

Run `backend/.venv/bin/python -m pytest -q backend/tests/test_api_egress.py` for
the source inventory tripwire. New literal HTTP(S) origins in the shared API fail
unless listed or explicitly classified in a file-scoped non-egress exception.
The test ignores docstrings and the separate Crowdset/compute runtimes, plus
`backend/app_runtime`, the loopback-only local Docker manager. It cannot
prove dynamic string construction or future dependency behavior; runtime denial
is the security boundary. Review changed HTTP clients and dependencies too.

Run `bash scripts/test-api-egress.sh` with a local Unix-socket Docker context and
Compose v2 with `--project-directory` set to the repository root, exactly like
Coolify. nginx configuration is baked into its image; build contexts are rooted
at the repository. A daemon-only absolute secret bind needs no helper-visible
file and cannot be silently created as a directory. It builds the actual API Dockerfile and sidecars, uses an isolated
synthetic PostgreSQL container, tests proxy inheritance, valid TLS to public
credential-free endpoints, direct IPv4/IPv6 and proxy bypass denial, unlisted
CONNECT/SNI/subdomain/port denial, DNS drops and host-side packet capture, DB relay,
ingress, audit logging, helper-invisible secret loading, scheduled-command
loading, extra Coolify networks and netguard restart/recovery. It cleans up only its own project. It does not start
`release` or run application migrations, and never touches the shared Supabase.
The API entrypoint polls a namespace-local `127.0.0.1:8001` listener for at most
30 seconds, then requires a failed raw connection to 1.1.1.1:443 (a guard against an
extra routable network; the listener is the real gate) before loading
runtime settings or starting application code. `firewall.sh` execs that listener
only after applying all rules; loopback-only rules cover the proof port. PID 1
forks the child in a new process group, checks proof every five seconds, and
terminates the child/group and exits if proof disappears. `unless-stopped` then
rejoins netguard's current namespace. This replaces the old manual-recovery-only
API policy. Ingress has static 172.30.87.5 to prevent restore-time IP collisions.

Run `bash scripts/test-api-egress-reboot.sh` for three actual daemon restarts.
It uses a **disposable privileged Docker-in-Docker container** with only source
and synthetic runtime settings mounted. It requires every service to return
without manual recovery, API application timestamps after the proof, and working
ingress/proxy/DB plus confinement after every reboot. It never restarts the shared
Docker/Colima host or a production VM. Planned deploys and mode changes still use
full stop-start with task ownership checks; automatic reboot recovery is separate.

On Colima, keep the checkout under `$HOME` for bind mounts. If Compose is missing
from the host CLI, `API_EGRESS_COMPOSE` can name an executable wrapper around
Compose running in a CLI container with `/var/run/docker.sock` and `$HOME` mounted.
Do not expose a daemon TCP port. The script prints the evidence directory.

Current local verification on 2026-11-04 used Colima arm64 with `$HOME` mounts.
All 15 public hosts completed certificate-validated TLS (3xx/4xx and image-host
502 root responses prove transport, not authenticated features). The complete
confinement smoke passed CONNECT/SNI/direct/DNS tests, packet capture, synthetic
PostgreSQL, ingress, audit, helper-invisible secret loading, scheduled-command
loading, extra-network restrictions, and automatic netguard watchdog recovery.
The nested-daemon test passed three reboots with every service restored without
manual recovery and every new application start after namespace proof (minimum observed delay
10.7 ms across the three reboots). Backend: 2,058
passed, 317 skipped; frontend: 813 passed; placeholder build passed. CI selection:
20 passed; Compose rendering and shell/workflow syntax checks passed.
No installed Coolify/OVH operation, real credential flow, hosted migration or
production audit soak was exercised. Supabase same-zone fronting remains unverified.

Mechanism references: [Docker DNS/network namespaces](https://docs.docker.com/engine/network/),
[Squid ACL name sources](https://www.squid-cache.org/Doc/config/acl/),
[Squid peek/splice](https://www.squid-cache.org/Doc/config/ssl_bump/),
and [Coolify Compose build pack](https://coolify.io/docs/applications/builds/docker-compose).

Coolify bind-file source inspection compared the [v4.3.23 parser](https://github.com/coollabsio/coolify/blob/v4.3.23/bootstrap/helpers/parsers.php#L827),
[storage read/write model](https://github.com/coollabsio/coolify/blob/v4.3.23/app/Models/LocalFileVolume.php#L106),
and [newer create-host-path-aware parser](https://github.com/coollabsio/coolify/blob/1e71d0d7a42e0a45971d61391d39a0f07b8984b2/bootstrap/helpers/parsers.php#L175).
The older parser's managed storage can capture secrets in encrypted DB content
and expose them through its storage UI, or create a directory despite the Docker
option. The newer parser skips this record for a no-content, create-false bind.
Neither source snapshot establishes the version or storage state on the OVH VM;
the rollout now checks source and Storages with an absent path before file creation.
