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
| Exact session pooler or direct DB hostname, configured as `EGRESS_DB_HOST` | `backend/release.py:15`, `backend/migration_runner.py:163` start psql migrations; `backend/admin/query.py:94` and `backend/admin/query.py:122` use `ANALYTICS_DATABASE_URL` through psycopg; `backend/admin/routes.py:78` tests that connection. Both DB URLs must target this same host and port 5432. |
| `backoffice-service-t57o3dxfca-nn.a.run.app` | `backend/ig_logger/sinks/beli/beli_client.py:32`, `backend/ig_logger/sinks/beli/beli_client.py:155` use urllib for Beli operations. |
| `backoffice-service-onboarding-t57o3dxfca-nn.a.run.app` | `backend/ig_logger/sinks/beli/beli_client.py:33`, same urllib transport. |
| `api.resy.com` | `backend/resy/resy_client.py:39`, `backend/resy/resy_client.py:146`. `resy.com` is only an Origin/Referer header, not a destination. |
| `lm-api-reads.fantasy.espn.com`, `lm-api-writes.fantasy.espn.com` | `backend/espn/espn_client.py:89`, `backend/espn/espn_client.py:90`, urllib at lines 366 and 431. |
| `registerdisney.go.com`, `fan.api.espn.com` | `backend/espn/disney_login.py:60`, `backend/espn/disney_login.py:62`, urllib at line 110. These are the MyDisney login and ESPN cookie bootstrap hosts used by this implementation. No other Disney login origin is called. |
| `site.api.espn.com` | `backend/espn/scoreboard.py:50`, `backend/espn/scoreboard.py:210`, public NBA scoreboard. |
| `gist.githubusercontent.com` | `backend/espn/team_claims.py:31`, `backend/espn/team_claims.py:56`, public predictions fallback. Overriding `ESPN_PUBLIC_PREDICTIONS_FALLBACK_URL` requires explicitly reviewing and adding its exact hostname. |
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
The namespace has an internal Docker network and default-deny IPv4/IPv6 OUTPUT,
INPUT and FORWARD rules. Only new outbound TCP connections to Squid:3128,
DB-relay:5432 and the loopback API health endpoint:8000 are allowed. Existing
connections can carry replies. No capability, Docker socket, host namespace,
sidecar filesystem or API credential is shared with a sidecar. API processes
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
grants allow `secret.api.resy.com` or arbitrary Supabase/Firebase projects.
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

Audit mode deliberately allows unlisted public HTTPS names and their DNS
lookups, while logging `policy=unlisted`. It is **not** a containment guarantee.
The API firewall and raw DNS denial are active in both modes. Enforce mode denies
unlisted CONNECT names before any destination DNS resolution. The fixed DB relay
is identical in both modes. The Docker host, trusted sidecars, image build,
Coolify administrators and kernel are trusted; host/container escape is outside
this threat model.

## Verification and policy maintenance

Run `backend/.venv/bin/python -m pytest -q backend/tests/test_api_egress.py` for
the source inventory tripwire. New literal HTTP(S) origins in the shared API fail
unless listed or explicitly classified in a file-scoped non-egress exception.
The test ignores docstrings and the separate Crowdset/compute runtimes. It cannot
prove dynamic string construction or future dependency behavior; runtime denial
is the security boundary. Review changed HTTP clients and dependencies too.

Run `bash scripts/test-api-egress.sh` with a local Unix-socket Docker context and
Compose v2. It builds the actual API Dockerfile and sidecars, uses an isolated
synthetic PostgreSQL container, tests proxy inheritance, valid TLS to public
credential-free endpoints, direct IPv4/IPv6 and proxy bypass denial, unlisted
CONNECT/SNI/subdomain/port denial, DNS drops and host-side packet capture, DB relay,
ingress, and audit logging. It cleans up only its own project. It does not start
`release` or run application migrations, and never touches the shared Supabase.
On Colima, keep the checkout under `$HOME` for bind mounts. If Compose is missing
from the host CLI, `API_EGRESS_COMPOSE` can name an executable wrapper around
Compose running in a CLI container with `/var/run/docker.sock` and `$HOME` mounted.
Do not expose a daemon TCP port. The script prints the evidence directory.

Local verification on 2026-11-04 used the existing Colima arm64 Docker daemon
and `$HOME` mounts. All 15 public allowlisted hosts completed certificate-validated
TLS (root-path responses included 3xx, 4xx and Venmo image-host 502; these prove
transport, not authenticated feature behavior). All denial, DNS packet-capture,
PostgreSQL relay, ingress and audit checks passed. The real read-only API image
also imported `main:app` and served `/health` with synthetic configuration and no
network. Backend: 2,049 passed, 317 skipped; frontend: 813 passed; placeholder
production frontend build passed. No real Supabase project query, release
migration, third-party credential flow or Coolify/OVH deployment was exercised.

Mechanism references: [Docker DNS/network namespaces](https://docs.docker.com/engine/network/),
[Squid ACL name sources](https://www.squid-cache.org/Doc/config/acl/),
[Squid peek/splice](https://www.squid-cache.org/Doc/config/ssl_bump/),
and [Coolify Compose build pack](https://coolify.io/docs/applications/builds/docker-compose).
