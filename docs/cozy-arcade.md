# Cozy Arcade

Arcade at `/arcade` is a Commons page around an imported browser game. The
first supported mode is Sprint. The page, settings APIs, session ownership and
run history belong to Commons. The original movie remains the gameplay runtime.

## Runtime boundary

- Shared React frontend, shared FastAPI backend. No separate service.
- `backend/arcade/wire.py` translates the private movie protocol. Original wire
  field names stay in this adapter and the private replay record. JSON run
  summaries use neutral keys such as `elapsed_ms`, `lines`, and `pieces`.
- The installed Ruffle runtime rewrites package origin URLs to local asset and
  API routes. The serving code has no upstream downloader or hostname override.
- The original website HTML, scripts, navigation, advertising and guest header
  are not loaded. Embedded movie artwork and text have not been rewritten.
- A separate player frame permits WebAssembly and same-origin assets. It cannot
  navigate to external pages. Commons credential-page policy is unchanged.
  The general page policy permits only the exact `/arcade/frame` path on the API
  and, when configured, on the player origin below.
- Missing runtime configuration returns 503. Importing the backend does not
  create a database or require game assets.

## Controls

Profiles store bindings per game id in `settings.controls`:
`{"sprint": {"keys": {action: code}, "pad": {action: button}}}`. Keys are DOM
`code` values; buttons are indexes in the standard gamepad layout. A game with
no saved binding uses J/L move and K soft drop plus a d-pad/face-button pad map.
Profiles saved with the older Sprint-only `keys` field are read as Sprint's
binding. Until games carry action metadata, Sprint's action names live in
`backend/arcade/controls.py`, and the game's own keys come from its in-movie
custom controls.

`GET /arcade/controls` returns the actions, the game's own keys and the
effective binding for the settings table (click-to-bind, presets Arrows, HHKB
and WASD). A launch carries `input`, the binding resolved against the game's own
keys. The player frame swallows a bound key in a capture listener and dispatches
a synthetic key for the action's game key to Ruffle's focused element inside its
shadow root, with `key`, `code`, `keyCode` and `which` set. It polls the Gamepad
API each animation frame the same way; the left stick doubles as the d-pad. A
bound key that is already one of the game's own keys is skipped, so the game's
keys always work. Game handling such as Sprint DAS/ARR stays in the adapter.

## Player origin

Uploaded movies will run ActionScript that nobody at Commons reviewed. Ruffle
removes Flash's memory-safety risk; the player origin removes the same-origin
risk. `ARCADE_PLAYER_ORIGIN` (backend) names a host, such as
`https://play.cozycommons.dev`, that serves the same backend but holds no
Commons credentials. Unset, the frame stays on the API origin as before.

When it is set (`backend/arcade/origin.py`):

- The player host answers only the frame, its script and style, the vendored
  player, package assets and the trusted compatibility API
  (`/arcade/compat/api`, authenticated by the per-launch game capability). Every
  other route is 404 there, and those player routes are 404 on the API host.
- Requests on the player host lose `Cookie` and `Authorization` before routing,
  and responses lose `Set-Cookie`. The Commons bearer never reaches the frame.
- The launch response names the frame URL. The Commons page embeds it and
  accepts messages only from that origin and that frame window. The frame
  accepts `arcade-launch` only from the server-supplied Commons origins and
  posts only to its verified parent origin, never `*`. The player origin is
  never its own allowed parent.
- Frame CSP: `default-src 'none'`, scripts and connections `'self'` only
  (WebAssembly allowed, eval not), `frame-ancestors` the Commons frontends.
  Commons page CSP: `frame-src` adds the player frame when the frontend is built
  with `VITE_ARCADE_PLAYER_ORIGIN`.

Packages are trusted (the admin-installed compatibility adapter) or untrusted.
Untrusted games launch only when the player origin is configured. Their Ruffle
config is `allowScriptAccess: false`, `allowNetworking: "internal"`,
`openUrlMode: "deny"`, and they get no page callbacks. The trusted adapter
keeps its legacy config, including the `X-Arcade-Run: finished` end-of-run
acknowledgement. Every current package is admin-installed and trusted unless
its manifest sets `"trusted": false`; owner uploads must be loaded untrusted
regardless of their manifest.

What the pinned Ruffle (nightly-2026-11-13, checked against its source) blocks:

| Setting | Blocks | Still allowed |
| --- | --- | --- |
| `allowNetworking: "internal"` | `navigateToURL`, AVM1 `getURL` (all navigator opens), `fscommand`, and ExternalInterface in both directions: Ruffle installs the page interface only with script access and `"all"` networking | `URLLoader`, `Loader`, `Socket`/`XMLSocket`, `LoadVars`/`loadVariables`, `loadMovie`, `SharedObject`, `LocalConnection` |
| `allowNetworking: "none"` | The above, plus AVM2 `URLLoader`, `Loader`, `Socket`, `Sound.load`, `SharedObject`, `LocalConnection` and AVM1 asset imports | AVM1 `LoadVars`, `loadVariables`, `loadMovie` and `XMLSocket` are not checked |
| `allowScriptAccess: false` | ExternalInterface, `javascript:` URLs, and navigation of the current tab | |

`"none"` is therefore no complete fence, and it would break games that load
their own assets. The frame's `connect-src 'self'` is the network boundary:
an untrusted movie can reach only the player origin, which serves nothing but
assets and the game API. Multiplayer stays possible on that boundary: a relay
WebSocket on the player origin (Ruffle's socket proxy) is `'self'`, and any
other service must be added to the frame's `connect-src` explicitly.

Untrusted games share one player origin, so they share its storage (Ruffle
keeps `SharedObject` data in `localStorage`). Per-game isolation is a separate
follow-up.

The local proof (`backend/tests/arcade_hostile_movie.py` generates the
synthetic movie and package) ran the Commons page and API on
`127.0.0.1:8877` and the player on `localhost:8877`. Sprint played on the
player origin to top-out, recorded its run and focused **Play again**. The
hostile movie ran (its two permitted same-origin loads reached the server),
its ExternalInterface and `javascript:` attempts had no effect, the top page
title and URL did not change, its Commons API read was refused by the frame
CSP before leaving the browser, and its Commons route on the player host got
404. In the legacy control (no player origin, trusted config) the same read
reached the API and returned 200.

### Enabling it (deployment steps)

Order matters: the frontend must allow the new frame before the backend moves
it. Each step is safe to stop after, but until step 4 the new host serves the
whole API like `api.cozycommons.dev`, so do steps 2 to 4 together.

1. DNS (Cloudflare): add `play.cozycommons.dev` pointing at the same target as
   `api.cozycommons.dev` (same record type and proxy status). Add no Workers,
   page rules or cookies for it.
2. Coolify, backend resource: add `https://play.cozycommons.dev` to its domains
   (the same ingress service and port as the API domain) and let Coolify issue
   the certificate. Do not set `ARCADE_PLAYER_ORIGIN` yet. Check
   `curl -sI https://play.cozycommons.dev/arcade/frame` returns 200.
3. Coolify, frontend resource: add the build variable
   `VITE_ARCADE_PLAYER_ORIGIN=https://play.cozycommons.dev` and redeploy. The
   page CSP now allows both frames; play still uses the API frame.
4. Coolify, backend resource: add the runtime variable
   `ARCADE_PLAYER_ORIGIN=https://play.cozycommons.dev` and redeploy. Check
   `/arcade/frame` is 404 on `api.cozycommons.dev`, `/health` is 404 on
   `play.cozycommons.dev`, and Sprint plays to its finished-run overlay.

Rollback is removing `ARCADE_PLAYER_ORIGIN` from the backend. A sibling
subdomain is same-site with Commons; Commons cookies are host-only today, so
none reach it, and the server strips any that do. A separate registrable
domain would also remove same-site treatment; consider it before opening
uploads to the public.

## Server state and ownership

Arcade uses the existing Commons Supabase/Postgres database and uncached server
client. Migration `0095_dice_arcade.sql` creates `arcade_profiles`,
`arcade_sessions`, `arcade_runs`, and the atomic start/save functions.
It follows the existing Commons-profile migrations in the shared release family.
The ordinary `python -m release` startup applies it before serving the new code.
There is no SQLite file, local database creation, new database credential, or
`ARCADE_STATE_PATH` requirement.

Profile and history APIs use existing Commons sign-in. Each database query
filters by the caller's Commons id. Tables have RLS enabled and are revoked
from public, anon and authenticated; only the backend service role may access
them. The two run functions are security invoker and service-role only.
The migration adds Arcade's schema attestation to release readiness.

Each game launch has its own six-hour capability and active run. Its hash is
stored in the database. The movie does not receive the Commons bearer or real
user id. Start/save functions lock the owning session and merge callback metrics
atomically, including overlapping callbacks. Private responses are no-store.
Saved records omit session tokens and IP fields.

Settings start at DAS 200 ms, ARR 35 ms and 60 fps. Profiles may choose native
rate (0), 60, 100, 144 or 240 fps. In-game custom controls are preserved. Sound
and handling apply on the next launch. `opponent_level` is stored for later Battle integration but does
not affect Sprint. Earned ranks and Battle matchmaking are not implemented.

When a run ends, the server marks its successful record response with `X-Arcade-Run: finished`. The isolated frame observes that acknowledgement and notifies Commons. This avoids Ruffle’s eval-based ExternalInterface callback, which the frame CSP blocks. A finished-run overlay keeps **Play again** beside the board and focuses it for keyboard activation. Restarting preserves profile settings, creates a fresh session and player frame, and prevents duplicate launch requests. A failed restart leaves the retry action available.

The earlier SQLite store was never configured on the deployed backend. Local
proof databases contain synthetic runs and are not production state. The local
classic client's accounts and recordings are untouched.

## Installing a private package

The importer reads an existing archive and never contacts the original service.
It skips website HTML/scripts and opponent recordings. The fixed compatibility
key is supplied from a local file, not embedded in the public repository.

```sh
python3 scripts/import-arcade-package.py /path/to/archive /path/to/arcade-package \
  --wire-key-file /path/to/private-wire-key --ruffle /path/to/self-hosted-player \
  --overrides /path/to/locally-patched-files
export ARCADE_PACKAGE_PATH=/path/to/arcade-package
```

The destination must be new. The optional override directory uses the archive's
host/path layout. Its replacement movie is copied into the content-addressed
package. Packages without a replacement movie advertise only the native frame
rate; the server rejects faster choices instead of speeding up the countdown.
Use the existing timing-corrected local builds for the 60 fps default. The package is self-contained: `manifest.json`,
content-addressed files and a vendored player. The package can move independently of the source archive, Windows or WSL.
Player state stays in the Commons database.
No original game assets, private keys, account records or packages belong in Git.
Original authorship and distribution terms remain applicable after UI changes.
A configured backend serves installed assets to browsers; installing a package
is therefore a publication decision for that deployment.

The code and database schema deploy through the existing merge webhook and
release migrations. Migration `0096_dice_arcade_package.sql` creates the private
`arcade-packages` Storage bucket and the active-package metadata table. Browser
roles cannot directly access either.

A verified Commons admin can use **Install game package** on `/arcade` to import
the prepared `.tar.gz`. The server checks archive paths, expanded size, entry
movie, player files and asset hashes before uploading it to private Storage.
Only then does it activate the new package. Failed validation leaves the
previous active package intact. Importing is an explicit admin action, not an
automatic download from the original service.

Package data survives redeploys in Supabase Storage. A worker downloads it into
an owned temporary playback cache as needed, so no persistent host mount,
Coolify variable, SSH access or new hosting credential is needed. The existing
Commons service role and Storage client are reused. The active package is
refreshed within five seconds. Each imported archive is limited to 40 MB
compressed and 160 MB expanded.

`ARCADE_PACKAGE_PATH` remains an optional local-development override, not a
hosting requirement. With neither an imported package nor a local override,
the page shows an installation message and disables Play. Administrators see
the import control; other users do not.

The earlier "Arcade storage is not configured" error came from the removed
SQLite configuration dependency. Game package installation is now available
inside Commons rather than requiring server administration.

## Rooms and relay

`backend/arcade/rooms.py` is the first Arcade service games use for live play:
small rooms joined by a challenge link and a bounded WebSocket relay between
their members. The relay forwards opaque game bytes. It does not interpret
moves, decide winners or record results; results and ratings are a separate
contract that must not trust a single client's report.

It is off by default. The socket refuses the handshake (HTTP 403) unless the API
process starts with `ARCADE_ROOMS=on`. No migration, table or credential is
involved: rooms are in-memory and end when their last member leaves or the
process restarts.

### Connection and identity

Connect to `wss://<api>/arcade/rooms/socket`. The first text frame must be
`{"t": "hello", "session": "<launch capability>"}` within 5 seconds. The
capability is the six-hour per-launch token from `POST /arcade/sessions`, looked
up by hash as the game API does. The movie never receives the Commons bearer,
and room messages never carry user ids. A wrong or expired capability closes
with 4401. The server replies `{"t": "hello", "limits": {...}}`.

Room membership belongs to the launch session, not the socket. A new socket
with the same capability that joins the same room resumes the membership.

### Envelope

Every frame is a JSON text object with a type `t`. Requests may carry an
operation id `id` (a string of up to 64 characters), echoed on the reply and on
any `error`. Game bytes travel base64-encoded in `data`.

| Client sends | Effect |
| --- | --- |
| `room.create` `{capacity?: 2..4}` | Creates a room and joins it. |
| `room.join` `{room, invite}` | Joins, or resumes an existing membership. |
| `room.ready` `{ready?: bool}` | Marks ready (default `true`). |
| `room.leave` | Leaves now. Pending messages for you are discarded. |
| `room.state` | Asks for the current `room.state`. |
| `room.send` `{seq, data}` | Reliable, ordered message to the other members. |
| `room.send` `{snapshot, data}` | Replaceable state under a key such as `board`. |
| `ack` `{from, seq}` | Cumulatively acknowledges reliable messages from `from`. |
| `ping` | Keepalive; the reply is `pong`. |

| Server sends | Meaning |
| --- | --- |
| `room.joined` `{room, invite, you, sent}` | Joined. `invite` is the challenge secret; `sent` is your last accepted `seq`. |
| `room.state` `{room, capacity, match, you, members}` | Members with `id`, `ready`, `connected`, after every change. |
| `room.start` `{match, seed}` | Every member was ready and connected. Same seed for all; ready flags reset. |
| `room.message` `{from, seq, data}` | Reliable message from member `from`. |
| `room.message` `{from, snapshot, data}` | Latest snapshot of `from` under that key. |
| `ack` `{seq}` | The server accepted your reliable messages up to `seq`. |
| `room.left`, `pong`, `error` `{code}` | Replies. Error codes include `not_found`, `room_full`, `not_member`, `already_in_room`, `seq_gap` (with `expected`), `payload_too_large`, `too_many_rooms`, `busy` and `bad_request`. |

A challenge link carries the room id and invite. A wrong invite and a missing
room return the same `not_found`. A socket is in at most one room, and only
members can send, ready or read state, so traffic never crosses rooms.

### Reliability

Reliable messages use per-sender sequence numbers starting at 1. The server
accepts only the next number. It acknowledges a duplicate (`seq` at or below
the last accepted) again without relaying it twice, and answers a gap with
`seq_gap`. A sender keeps unacknowledged messages and resends them after a
reconnect, starting after the `sent` value in `room.joined`.

The server keeps each reliable message for each recipient until that recipient
acknowledges it. On resume, it replays all of them in order, so a recipient
deduplicates by `(from, seq)`. Snapshots do not queue or retry: the server
keeps only the latest per member and key (at most 8 keys), sends it to members
online now and to a member that resumes. A game's move stream belongs in
reliable messages; a periodic board preview would be a snapshot.

### Reconnects and limits

A dropped socket keeps its membership for 30 seconds with `connected: false`
and `ready: false`; then the member leaves. A newer socket for the same
membership closes the older one with 4409. A match starts only when the room is
full and every member is ready and connected.

| Limit | Value | When exceeded |
| --- | --- | --- |
| Frame | 8 KiB text, no binary frames | Close 4413 / 4400 |
| Payload | 4 KiB decoded | `payload_too_large` |
| Rate | 60 frames/s, burst 120, per socket | Close 4429 |
| Idle | 120 s without a frame (send `ping` every 30 s) | Close 4408 |
| Outgoing queue | 256 frames | Close 4503; messages stay pending for resume |
| Unacknowledged messages | 1024 per recipient | The recipient leaves the room (4503) |
| Sockets / memberships | 8 sockets and 4 rooms per user; 500 rooms per process | 4429 / `too_many_rooms` / `busy` |
| Malformed or unknown frame | | Close 4400 |

The capability is checked when the socket says hello, not again during a match.

### Deployment path and scaling

The API runs as one uvicorn process (`backend/release.py`), and the relay is
correct only there: rooms, timers and queues live in that process's memory, so
mutations need no locks. Horizontal scaling would need routing by room to one
process, or room state and fan-out in a shared broker, plus resume across
processes. A restart ends every room; clients see a closed socket and their room
no longer exists.

The repository's ingress (`deploy/api-egress/nginx.conf`) already forwards
`Upgrade`/`Connection` over HTTP/1.1 with a one-hour read timeout, and the
locked `uvicorn[standard]` includes WebSocket support. Not verified here: the
Coolify proxy and the public CDN path to the API domain in production. Both
usually pass WebSockets but may close idle connections, which the 30-second
`ping` covers. The frame does not open sockets yet. Without
`ARCADE_PLAYER_ORIGIN`, its `connect-src 'self'` covers a same-origin `wss:`
connection. With a player origin configured, the socket answers only on the API
host (the player-origin path policy is unchanged), so a frame-side bridge must
either connect from the Commons page or have the socket path added to that
policy deliberately.

Bridges are separate work. The first is a small client in our own built games;
unmodified games would later reach a relay channel through Ruffle's socket
proxy.

## Verification and remaining work

Focused backend tests cover route authentication, encoded movie sessions,
record redaction and frame policy. Real PostgreSQL/PostgREST tests exercise
migration-created tables, profile persistence without a storage-path variable, per-user and per-tab isolation,
overlapping callbacks, expired capabilities and denied cross-owner writes.
The same database tests verify service-role access, blocked browser roles,
private bucket creation and package metadata persistence. Package object
upload/download calls use an in-memory Storage test double locally; the live
Storage HTTP service is not part of the local harness.

The local browser smoke run uses a synthetic Commons identity with the real
database adapter. It loads the corrected Sprint package, plays to top-out and
persists the neutral run record through PostgREST. All observed game requests
stay on the local API origin. A live Google sign-in is not part of that harness.

The focused frontend build passes. A full local application build is blocked
by the reused environment's missing `three` dependency. A clean dependency
install encountered existing lockfile hash mismatches, which were not bypassed.

The prepared private package was imported through a real Commons admin account on 2026-11-28. Hosted Sprint playback was observed in Chrome. Hosted run saving remains unverified. Battle and opponent-level selection remain unimplemented.

Rooms and relay tests (`backend/tests/test_arcade_rooms.py`) run two or more clients per room through the real socket route: matches start together, reliable messages are ordered, acknowledged and deduplicated, snapshots replace, rooms are isolated, and frame, payload and rate limits, grace expiry, replacement and resume replay are enforced. Launch capabilities come from a test double; their database lookup is the existing `Store.session`.

Restart verification: a local Chromium run played the original Sprint movie to top-out, observed the server acknowledgement, focused Play again, restarted with Enter and loaded a new player session. This flow used synthetic authentication and an in-memory run store; database persistence is covered separately. The existing blocked blob-worker warning and two console 404 messages remain. No CSP permission was added.
