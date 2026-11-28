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
  The general page policy permits only the API's exact `/arcade/frame` path.
- Missing runtime configuration returns 503. Importing the backend does not
  create a database or require game assets.

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
rate (0), 60, 100, 144 or 240 fps. HHKB extras use J/L for movement and K for soft
drop. In-game custom controls are preserved. Sound and handling apply on the
next launch. `opponent_level` is stored for later Battle integration but does
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

Restart verification: a local Chromium run played the original Sprint movie to top-out, observed the server acknowledgement, focused Play again, restarted with Enter and loaded a new player session. This flow used synthetic authentication and an in-memory run store; database persistence is covered separately. The existing blocked blob-worker warning and two console 404 messages remain. No CSP permission was added.
