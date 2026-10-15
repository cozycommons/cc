# Crowd Set prototype

Crowd Set adds a listening workspace at `/crowd-set` alongside Dice. Create a performance, upload one timing reference and crowd recordings, then align and reconstruct. The reference is used only for timing. Output contains selected crowd audio and silence wherever it has no coverage.

Basic constant-gain volume matching is included following the first listening experiment. It preserves within-clip dynamics; it does not remove screams, denoise, restore bass, compress, or equalize audio.

## Run locally

Requires Python 3.11+ (3.12 recommended) and Node 22. The optional Python environment is separate from Dice. The imageio-ffmpeg wheel supplies ffmpeg; no system ffprobe is needed.

From the repository root:

```bash
bash scripts/crowd-set-dev.sh setup
bash scripts/crowd-set-dev.sh run
```

In a second terminal, from the repository root:

```bash
cd frontend
npm ci
VITE_API_URL=http://127.0.0.1:8000 \
VITE_SUPABASE_URL=http://127.0.0.1:54321 \
VITE_SUPABASE_ANON_KEY=local-preview-placeholder \
npm run dev -- --host 127.0.0.1 --port 8083 --strictPort
```

Open [Crowd Set](http://127.0.0.1:8083/crowd-set). These placeholder settings only allow the frontend shell to initialize; they do not start or authenticate Dice. Crowd Set independently talks to `http://127.0.0.1:8010`. If a verified Dice frontend from this same checkout is already running locally, visit its `/crowd-set` route instead. Do not modify the shared Dice sandbox configuration.

The API binds loopback and checks peer, Host and Origin. The local launcher remains loopback-only and does not support the private Codespaces gateway or phone access over LAN. A separate hosted configuration uses existing Cozy Commons sign-in; see hosting below. No database or migration is involved. Stop the two task-owned foreground commands with Ctrl-C.

## Use and limits

1. Create a named performance. Add a continuous timing reference from that same performance, up to 2 hours.
2. Add up to eight crowd clips. Each may be up to 20 minutes. Use at least 37 seconds for the three 12-second analysis windows (frame boundaries make exactly 36 seconds insufficient). Trim longer crowd recordings locally for this prototype.
3. Click **Create mix**. Conversion and matching happen in a worker process. Status updates while the page remains usable; uploads/edits to that performance are blocked while it runs.
4. Inspect matched/unmatched sources, sample-window evidence, source selection, and gaps. Exclude a suspect source and rerun. Weak/inconsistent matching abstains. There is no manual timing override yet.
5. Play or download the 32 kHz mono PCM WAV. Leading, internal and trailing gaps remain silent at their original times. Seek to a covered interval before listening. Reference audio never fills gaps.

Accepted extensions: WAV, MP3, M4A, MP4, MOV, AAC, FLAC, OGG, WEBM. Video must contain a supported audio track. Up to 512 MiB per upload, 20 performances, one upload and one processing job at a time. Uploads time out at 5 minutes; each decoder/measurement at 3 minutes; whole jobs at 15 minutes. Storage admission reserves 3 GiB for generated audio within an 8 GiB local budget. Original upload bytes (including any embedded capture metadata) and generated working audio persist under ignored `.crowd-set/`; delete idle performances in the UI to reclaim space. Deletion is permanent. No media is committed.

Local metadata uses atomic file replacement, not a distributed durable queue or a power-loss-safe database. Completed work survives ordinary reload/restart. A worker inherits the storage lock and its own deadline: after an abrupt API crash, restart refuses while that old worker is alive (at most 15 minutes). Once it exits, restart marks the interrupted operation failed for explicit retry. Do not run multiple API workers against one checkout.

## Timing and volume limits

Timing uses 24 spectral energy-change bands and up to nine distributed 12-second windows. It requires at least three matches with similarity >=0.25, a separated-peak margin >=0.08, and offsets within 160 ms of their median. At least 75% of sampled windows predicted to overlap must agree. These are conservative heuristics, not calibrated probabilities. Displayed uncertainty summarizes sample spread plus 40 ms resolution, not a statistical confidence bound. Repeated songs, edits, microphone noise, and unsampled drift can still mislead it. Listen to verify; short-excerpt success does not certify a full set.

Selection favors the source that extends coverage farthest at each boundary; users can exclude clips. It is not an audio-quality ranking. Fades last at most 80 ms and only occur inside actual overlap.

Decoded working files use float32 samples so decoder/downmix peaks above full scale survive until final gained PCM quantization. Volume matching measures BS.1770 integrated loudness and true peak on the working audio. The first selected source anchors around -23 LUFS; this is a prototype default, not a required output loudness. Subsequent sources compare the last up-to-30 seconds of their common passage when they share at least 8 seconds; otherwise each uses a disclosed whole-clip fallback. Whole-clip matching can confuse changes in musical energy or crowd noise with recording level. Provisional gains are capped at -60 to +12 dB, then all gains are attenuated together if needed for 2 dB true-peak headroom. Final output peak is measured and can trigger another common attenuation pass. No gain envelope, compression or limiting is used. PCM rounding and sample-rate conversion remain part of the working format.

## Validation

From the repository root:

```bash
.crowd-set-venv/bin/python -m pip install pytest==8.3.4 httpx==0.28.1
PYTHONPATH=backend .crowd-set-venv/bin/python -m pytest backend/crowd_set/tests -q
```

Frontend checks (from `frontend/`):

```bash
npm test -- --run
npm run lint
VITE_API_URL=http://127.0.0.1:8000 \
VITE_SUPABASE_URL=http://127.0.0.1:54321 \
VITE_SUPABASE_ANON_KEY=local-build-placeholder npm run build:check
```

The added CI job runs the Crowd Set backend tests on Ubuntu and macOS/Python 3.12. Existing frontend checks also collect Crowd Set tests. CI itself has not been run remotely for this uncommitted change.

Local evidence on 2026-10-15:
- Synthetic alignment tests cover positive/negative offsets, tonal change/noise, partial overlap, unrelated/nonoverlapping audio, silence, short clips, edits and repeated passages.
- Assembly checks prove reference exclusion, exact gap silence, duration/bounds and overlap-only fades. API integration covers real worker decoding, upload constraints, conflicts, range/download playback, invalidation, errors and restart. A real parent-crash test verifies the inherited worker lock.
- All 18 backend tests passed locally, including float input above full scale preserved until final gained output.
- Gain tests use identical passages at different levels, check expected relative gain and sample-wise dynamics preservation (within PCM rounding), and measure rendered true-peak headroom.
- Existing frontend suite passed: 53 files / 351 tests before the final copy refinement. The 9 focused Crowd Set and app routing tests passed again after that refinement. Production build passed with loopback placeholder settings. Existing CommonsScene hook warning remains; no new hook warning was reported.
- Known local Niteharts excerpts: five-minute reference; Derek source 84.64–174.64 seconds; Alecinutopia source 85.38–175.38 seconds. Both 90-second clips matched at reference offsets +80.00 and +140.00 seconds, seven of seven windows agreeing. Coverage is 80–230 seconds; gaps are 0–80 and 230–300; fade is 169.92–170.00. This proves a bounded example, not full-set correctness or subjective acoustic quality.
- Ignored smoke artifacts live under `artifacts/crowd-set-smoke/`. Original copyrighted media stays outside Git. Browser upload/processing/playback and reload evidence is saved there. The final float-working-audio rerun measured output true peak at -7.63 dBFS.

See [PRODUCT.md](PRODUCT.md) and [TECH.md](TECH.md). Capture timestamps are preserved inside original files but are not extracted, trusted or used for timing yet. Filename and upload time are never treated as capture time.

Separate future work: capture-time-assisted reference-free alignment; social-link ingestion (Instagram post video items, TikTok, YouTube with provenance and partial/unavailable results); individual cleanup; advanced sonic consistency; reference-free matching/drift/manual placement; video.

## Hosted test configuration

The user authorized deploying on the existing Cozy Commons Coolify server. Deploy this as a separate application from the feature branch, using root context and `backend/crowd_set/Dockerfile`, port 8010. It packages the frontend with `/crowd-set/` asset paths and serves the API from the same origin. Do not redeploy the existing backend or run its release/migration hooks for this application.

Runtime settings:

- `CROWD_SET_ORIGIN=https://cozycommons.dev`
- `CROWD_SET_AUTH_URL`: existing Cozy Commons Supabase project URL.
- `CROWD_SET_AUTH_KEY`: existing public publishable/anon key, never a service-role key.
- `CROWD_SET_DATA_DIR=/data` and `CROWD_SET_STATIC_DIR=/static` are image defaults.

Build settings: existing frontend `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (public values only). Route `Host(cozycommons.dev) && (Path(/crowd-set) || PathPrefix(/crowd-set/))` to this app at higher priority than the existing frontend, without stripping the prefix. Preserve existing Commons/Dice routers. Use HTTPS only. The Supabase OAuth redirect allowlist must permit `https://cozycommons.dev/crowd-set`.

Mount a persistent named volume at `/data`, cap the container at 2 CPUs and 2 GiB memory, and keep one replica. Disable deploy-on-push for the test service; deploy reviewed commits manually. Existing global limits still apply: one upload, one worker, 20 sets, and 8 GiB storage admission across users. Ordinary restarts preserve completed work; interrupted jobs require retry. Back up the volume independently; atomic metadata is not a power-loss-safe database.

API access validates tokens with Supabase Auth and derives ownership from its verified user ID. Owner checks cover listing, metadata, upload, edits, deletion, processing, playback and range downloads. Mutations require a bearer token plus the exact frontend Origin. Native playback uses a Secure, HttpOnly, SameSite=Strict cookie scoped to `/crowd-set`; each audio request validates it. Tokens never appear in URLs. Token refresh updates that cookie; sign-out clears it. Expired/revoked access is subject to existing Supabase session semantics. Ownerless local sets are hidden when hosted. The service does not query or mutate Commons/Dice tables.

Before declaring rollout complete: verify sign-in, upload/processing/playback/download, unauthorized 401 and cross-owner 404, persistent reload/restart, and unchanged Commons/Dice endpoints. Record the Coolify resource, deployed commit and outcome here after deployment.
