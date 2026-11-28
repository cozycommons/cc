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

`ARCADE_STATE_PATH` points to an SQLite database on a persistent server volume.
It contains profiles keyed by authenticated Commons user id, expiring game
sessions, and run summaries plus replay records. Each launch has its own active
run, including two launches by the same account in separate tabs. Browser
storage is not the authority for game settings or records.

Profile and history APIs use existing Commons sign-in. The movie receives a
random six-hour game capability, not the Commons bearer or user id. Its hash
is stored server-side. The capability travels in request bodies, never URLs.
Private responses are no-store. Saved records omit session tokens and IP fields.

Settings start at DAS 200 ms and ARR 35 ms. HHKB extras use J/L for movement and
K for soft drop. Arrows and Z/X/C remain available. In-game custom controls are
preserved by the adapter. Sound and handling apply on the next launch.
`opponent_level` is stored per profile for the later Battle integration, but
does not affect Sprint. Earned ranks and Battle matchmaking are not implemented.

SQLite is deliberately project-owned server storage for this first slice.
It is not the hosted Commons Postgres database. Use one persistent filesystem
for the API process and its workers. Do not use independent ephemeral replicas.
Back up the database using SQLite's backup API, along with the asset package.
Moving state into shared Postgres is a later migration if replicated hosting
requires it.

## Installing a private package

The importer reads an existing archive and never contacts the original service.
It skips website HTML/scripts and opponent recordings. The fixed compatibility
key is supplied from a local file, not embedded in the public repository.

```sh
python3 scripts/import-arcade-package.py /path/to/archive /path/to/arcade-package \
  --wire-key-file /path/to/private-wire-key --ruffle /path/to/self-hosted-player
export ARCADE_PACKAGE_PATH=/path/to/arcade-package
export ARCADE_STATE_PATH=/path/to/persistent-volume/arcade.sqlite
```

The destination must be new. The package is self-contained: `manifest.json`,
content-addressed files and a vendored player. Copying that directory and the
server database moves Arcade without the source archive, Windows, or WSL.
No original game assets, private keys, account records or packages belong in Git.
Original authorship and distribution terms remain applicable after UI changes.
A configured backend serves installed assets to browsers; installing a package
is therefore a publication decision for that deployment.

For containers, mount a read-only package at `ARCADE_PACKAGE_PATH` and a writable,
persistent state directory owned by the backend app user. Existing Commons
`VITE_API_URL`, sign-in, and `CORS_EXTRA_ORIGINS` settings still apply. Set the
frontend origin in `CORS_EXTRA_ORIGINS` so the frame accepts its launch message.

No hosted resources, persistent volumes, or production deployments are created
by this change.

## Verification and remaining work

Focused backend tests cover independent profiles, concurrent tabs, persistence
after reopening storage, authentication, encoded session capabilities, expired
sessions, record redaction, and the frame CSP. Frontend tests cover server
settings and saving before launch.

A local Chromium smoke run loaded the real movie through the neutral routes,
played to top-out, and saved a signed-in record. All observed network requests
stayed on the local API origin. Two unattributed console 404 messages remained;
the movie loaded, played and saved its record successfully. The smoke harness substituted a synthetic Commons
identity and did not exercise a live Google sign-in. Production authentication
still uses the existing Commons dependency.

The focused frontend build passed. A full local build is currently blocked by
the reused checkout's missing `three` package. A clean full dependency install
was blocked by existing Pillow/cffi lockfile hash mismatches. Verification reused
existing environments, including cryptography 44 rather than the lockfile's 50.
No lockfile or hash guard was changed.

Next steps are a deployment with a separately supplied package and persistent
volume, verification with real Commons sign-in on a second device, then Battle
and opponent-level selection. Do not claim those are already supported.
