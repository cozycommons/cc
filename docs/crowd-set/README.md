# Crowd Set prototype

Crowd Set adds a set catalog at `/crowd-set` alongside Dice. Create a named set, upload videos, and watch its automatically compiled video cut with synchronized audio, or listen when only audio is available. The current mix appears above smaller original recording cards with native playback and downloads. Audio uploads are also supported. New hosted sets are shared with all signed-in members; legacy private sets remain private.

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

1. Use **New set** on the homepage, enter a name and choose **Create set**. The empty set opens immediately; **All sets** returns to the catalog.
2. Choose **Add clips** to upload up to 64 recordings, each at most two hours (eight hours aggregate per set). Audio files are also accepted. There is no reference setup.
3. Uploads and recording changes automatically queue a mix. A three-second debounce coalesces bursts; one global worker processes queued sets. Uploads to the running set wait until it finishes.
4. Watch the current compiled MP4, or use the audio player for audio-only sets. Download the video or 32 kHz mono PCM WAV. The previous successful mix stays playable during updates and failures; a completed mix replaces it atomically. Retry a failed or interrupted update from the set page.
5. Inspect the single color-coded mix timeline: it shows actual selected segments, silent gaps and crossfades, with matching colors on originals. Click or use the keyboard to seek; source labels jump to original cards. There are no timeline editing controls.
6. Play/download every original, including unmatched recordings. Uploaders and the set owner can remove their permitted recordings. Only the owner can delete a hosted set.

The longest usable included ordinary recording establishes internal timing and can contribute audio. Clipping and silence metrics break duration ties only; a stable ID breaks remaining ties. Confident matches can extend before or after that recording. Actual gaps remain silent. Legacy explicit reference files remain playable originals but never contribute to new mixes. Existing private sets are not made shared.

Accepted extensions: WAV, MP3, M4A, MP4, MOV, AAC, FLAC, OGG, WEBM. Common video inputs are MP4 and MOV with H.264 or HEVC/H.265 video and AAC audio, including iPhone MOV/HEVC recordings. Originals retain their bytes; compiled cuts are broadly compatible MP4/H.264/AAC. YouTube imports also select H.264/AAC. Video must contain a supported audio track. Up to 3 GiB per file, 20 sets, one active chunk transfer and one processing job at a time. The UI reports server limits. Uploads use 8 MiB SHA256-checked chunks; retry or reselect the same file to resume within 24 hours. Each media subprocess has a ten-minute deadline; whole jobs have a four-hour deadline.

Local defaults allow 16 GiB originals/pending uploads and 10 GiB working data, retaining a 2 GiB physical free floor. Private Cloudflare R2 can hold originals and finished mixes with a hard 8 GB decimal application quota, while local disk retains staging, cached analyses, metadata and job state. All admission limits are enforced before accepting work. Idle sets can be deleted in the UI to reclaim space; deletion is permanent. No media or credentials are committed.

Metadata uses atomic file replacement and a single inherited storage lock. It survives ordinary restart, but requires independent backup and is not a distributed or power-loss-safe database. Interrupted jobs automatically resume at most twice using cached preparation, then require Retry. Never run multiple writers against the same volume.

Upload batches hold processing until all selected files are attempted, then queue one update. A slow active chunk holds the batch open; an abandoned batch settles after 60 seconds. Lost append/finalize responses are safe to retry. Failed files remain named in the UI; committed originals and the old mix are retained. Only the initiating uploader may resume/finish their uploads.

## Timing and volume limits

A non-anchor recording needs at least 37 seconds for three distinct 12-second windows; shorter clips remain playable originals and may not join the mix. Timing uses 24 spectral energy-change bands and up to nine distributed 12-second windows. It requires at least three matches with similarity >=0.25, a separated-peak margin >=0.08, and offsets within 160 ms of their median. At least 75% of sampled windows predicted to overlap must agree. These are conservative heuristics, not calibrated probabilities. Internal uncertainty summarizes sample spread plus 40 ms resolution, not a statistical confidence bound. Repeated songs, edits, microphone noise, and unsampled drift can still mislead it. Listen to verify; short-excerpt success does not certify a full set.

Selection favors the source that extends coverage farthest at each boundary; users can exclude clips. It is not an audio-quality ranking. Fades last at most 80 ms and only occur inside actual overlap.

Decoded working files use float32 samples so decoder/downmix peaks above full scale survive until final gained PCM quantization. Volume matching measures BS.1770 integrated loudness and true peak on the working audio. The first selected source anchors around -23 LUFS; this is a prototype default, not a required output loudness. Subsequent sources compare the last up-to-30 seconds of their common passage when they share at least 8 seconds; otherwise each uses a whole-clip fallback. Whole-clip matching can confuse changes in musical energy or crowd noise with recording level. Provisional gains are capped at -60 to +12 dB, then all gains are attenuated together if needed for 2 dB true-peak headroom. Final output peak is measured and can trigger another common attenuation pass. No gain envelope, compression or limiting is used. PCM rounding and sample-rate conversion remain part of the working format.

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

The added CI job runs the Crowd Set backend tests on Ubuntu and macOS/Python 3.12. Existing frontend checks also collect Crowd Set tests. The dedicated container job builds the hosted image and checks startup, unauthorized access, persistent-volume write access, and the bundled decoder.

Local evidence on 2026-10-15:
- All 23 backend tests passed. Backend coverage includes positive/negative offsets, conservative abstention, longest-usable anchor selection, exact union/gap rendering, preserved float peaks, constant-gain matching, automatic queue coalescing, serial builds, cache reuse, atomic publication failures, restart and inherited worker locks.
- Hosted access tests cover shared catalogs, legacy privacy, anonymous rejection, original video MIME/range/download, uploader/owner editing, owner deletion and exact Origin checks.
- The full frontend suite passed 357 tests in 54 files, including new-set discoverability, create/catalog/open/upload, creation failure, partial batch upload failure, and timeline provenance/seek/playhead. Build, lint and bundle budget passed; the existing CommonsScene hook warning remains.
- Real Niteharts excerpts (Derek 180 seconds and Alecinutopia 164.14 seconds) matched at a relative +60 seconds and produced a 224.14-second union. Cold automatic build took 10.2 seconds from final upload completion to ready (6.2 seconds observed processing). Adding an original 41.82-second MP4 took 6.51 seconds to ready (3.46 seconds observed processing), reusing cached audio. The prior mix remained playable throughout. These are local measurements, not hosted performance guarantees.
- In that initial two-source timing experiment, the short MP4 abstained because its matching windows disagreed. Its native media endpoint returned exact original bytes with video MIME and HTTP 206. It remains available to play/download. No claim of subjective acoustic improvement or full-set correctness follows from this bounded check.
- The preview catalog contains one **Niteharts · ISOxo × Skrillex** set. At the user’s explicit request, its preserved five-minute original was migrated from the old timing-only fixture role to an ordinary eligible recording, retaining original bytes and provenance. The updated 304.14-second mix uses that source for 0–300 seconds and Alecinutopia for 299.92–304.14 seconds (80 ms crossfade). Derek matches at +80 seconds and the MP4 now matches at +62.36 seconds, but neither is selected because those intervals already have coverage. The rebuild took 7.14 seconds locally and preserved the previous mix until publication. The earlier preview/timing/browser fixtures are recoverably archived outside the catalog under ignored `artifacts/crowd-set-smoke/archived-preview-fixtures/`, with file hashes and an inventory. Their originals and outputs are preserved. Future smoke checks must use a temporary Store root or separate `CROWD_SET_DATA_DIR`, never the active preview catalog.
- Fresh browser visual QA and hosted deployment are blocked by the browser tool's request-header policy loading failure. HTTP and component checks passed; no new UI screenshot is claimed. Media and evidence stay outside Git.

See [PRODUCT.md](PRODUCT.md) and [TECH.md](TECH.md). Capture timestamps are preserved inside original files but are not extracted, trusted or used for timing yet. Filename and upload time are never treated as capture time.

Separate future work: capture-time assistance; social-link ingestion (Instagram post video items, TikTok, YouTube with provenance and partial/unavailable results); individual cleanup; advanced sonic consistency; transitive alignment, drift/manual placement. Native playback depends on browser codec support; download remains available.

## Hosted test configuration

The user authorized deploying on the existing Cozy Commons Coolify server. Deploy this as a separate application from reviewed commits on `main`, using root context and `backend/crowd_set/Dockerfile`, port 8010. It packages the frontend with `/crowd-set/` asset paths and serves the API from the same origin. Do not redeploy the existing backend or run its release/migration hooks for this application.

Runtime settings:

- `CROWD_SET_ORIGIN=https://cozycommons.dev`
- `CROWD_SET_AUTH_URL`: existing Cozy Commons Supabase project URL.
- `CROWD_SET_AUTH_KEY`: existing public publishable/anon key, never a service-role key.
- `CROWD_SET_DATA_DIR=/data` and `CROWD_SET_STATIC_DIR=/static` are image defaults.

Build settings: existing frontend `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (public values only). Route `Host(cozycommons.dev) && (Path(/crowd-set) || PathPrefix(/crowd-set/))` to this app at higher priority than the existing frontend, without stripping the prefix. Preserve existing Commons/Dice routers. Use HTTPS only. The Supabase OAuth redirect allowlist must permit `https://cozycommons.dev/crowd-set`.

Mount a persistent named volume at `/data`, cap the container at 2 CPUs and 2 GiB memory, and keep one replica. Use Coolify's consistent container name (no rolling updates): the old instance must release the data-directory lock before its replacement starts. Disable deploy-on-push for the test service; deploy reviewed commits manually. Global limits apply across users: one active chunk, one worker, 20 sets, separate original/work quotas and a physical free floor. Ordinary restarts preserve completed work and resumable offsets; interrupted jobs have bounded automatic retries. Back up the volume independently; atomic metadata is not a power-loss-safe database.

API access validates tokens with Supabase Auth and derives ownership from its verified user ID. All signed-in users can list, open, contribute to and play new shared sets. Legacy private sets remain owner-only. Only the uploader or set owner can change/remove a clip, and only the owner can delete the set. Every metadata and media route enforces visibility, including original video and range downloads. Mutations require a bearer token plus the exact frontend Origin. Native playback uses a Secure, HttpOnly, SameSite=Strict cookie scoped to `/crowd-set`; each media request validates it. Tokens never appear in URLs. Token refresh updates that cookie; sign-out clears it. Expired/revoked access is subject to existing Supabase session semantics. Ownerless local sets are hidden when hosted. The service does not query or mutate Commons/Dice tables.

Before declaring rollout complete: verify sign-in, upload/processing/playback/download, anonymous 401, shared-member access, forbidden edits/deletions and legacy cross-owner 404, persistent reload/restart, and unchanged Commons/Dice endpoints. Record the Coolify resource, deployed commit and outcome here after deployment.

Production service: Coolify resource `e5h6wpbgxucsenwle88girmk` (Crowd Set), first deployed from `42e96283c5bb0036d588f726a1b235e0dfcfd586` on 2026-10-16. Persistent volume: `e5h6wpbgxucsenwle88girmk-crowd-set-data`. Manual Traefik labels preserve the exact `/crowd-set` prefix with priority 100. Public health returns JSON and anonymous catalog access returns 401. Commons/Dice resources were not redeployed. Browser API requests bypass caches, including the previously cached HTML fallback from before this service existed. Complete the authenticated rollout checks above when deploying changes.


## Capacity/storage extension (2026-10-19)

A cold isolated macOS test with a two-hour synthetic anchor and 50 five-minute excerpts completed in 276.41 seconds. All 50 excerpts matched with zero measured offset error; the playable mix spans 7200 seconds. The conservative peak memory bound (Python peak plus largest decoder child peak) was 1,189,625,856 bytes, below the 2 GiB target. This is synthetic capacity evidence, not a hosted timing guarantee or certification of real full-set alignment. Reproduce without touching the preview catalog:

```bash
.crowd-set-venv/bin/python scripts/crowd-set-capacity-check.py --report /tmp/crowd-set-capacity.json
```

Cloudflare R2 is active in production through Coolify. The private Standard bucket has public access disabled, a bucket-only Object Read & Write credential stored in server runtime, and a one-day incomplete multipart abort rule. Free-tier mode caps retained originals, unfinished transfers and published mixes at **8 GB total**, and caps request attempts at 100,000 Class A / 1,000,000 Class B per rolling 35 days. It blocks new work before those limits and preserves cleanup. These caps leave headroom below [R2's Standard free allowance](https://developers.cloudflare.com/r2/pricing/); other account usage must be checked separately. Fifty large videos may exceed 8 GB even though the recording count is supported. See TECH.md for exact runtime variables, one-time durable budget initialization and rollout checks. Supabase Auth is unchanged; no plan upgrade or database migration is needed.

Local extension checks: all 44 existing Crowd Set backend tests plus 12 R2 cases and all 361 frontend tests pass. Lint has no errors (one existing Commons hook warning); production build and bundle budget pass. Cloud tests use an isolated HTTP transport to verify resumable transfers, private-bucket validation, range streaming, quota reservations, lost responses and orphan cleanup. R2 cases additionally cover durable atomic request caps, lost creation/part/completion responses, pending-byte reconciliation and read-budget exhaustion. Production verification uploaded three synthetic originals, completed a compiled mix, played the full result and downloaded it; a downloaded MP4 original matched the source SHA256. The persistent ledger reported four objects / 10,394,700 reserved bytes and 14 Class A / 26 Class B attempts at that checkpoint. The separate 51-recording production audio trial also completed before R2 enablement; original legacy local files remain readable.


## Canonical video verification

The new renderer creates one 1920×1080, 24 fps H.264/AAC MP4 using the finalized audio soundtrack. Local tests verify aligned landscape-to-portrait switching, delayed audio/video timestamps, rotation, preserved aspect, neutral gaps and early picture EOF, waveform correspondence, and bounded output. Paired cloud upload/metadata-save failures preserve the complete preceding revision. Both media routes require the existing authorization and honor current/previous revision range requests. The UI offers Watch only for actual published video and retains legacy/audio-only playback.

New cuts render at 1080p; existing published cuts keep their original resolution until reprocessed. The encoder caps video at 3 Mbps and reserves up to 420,000 bytes per second plus container overhead for each rendition. Higher resolution uses more storage and processing time; originals, current and previous revisions still share the enforced 8 GB allowance. Lower-resolution sources retain their original detail.

Run the long motion-video check separately from audio alignment capacity:

```bash
.crowd-set-venv/bin/python scripts/crowd-set-video-check.py --seconds 7200 --report /tmp/crowd-set-video-capacity.json
```

A five-minute 1080p synthetic motion trial on macOS rendered in 66.04 seconds, produced 113,042,335 bytes, and peaked at 254,967,808 bytes of child RSS with one encoder thread. This does not establish two-hour performance on the production host.

The script uses temporary synthetic media and never opens the preview or production catalog. It reports render time, bytes and largest child RSS; host-specific measurements do not certify real concert footage or alignment quality.

### Import from YouTube

Open a set, paste a single public YouTube URL under **Or add from YouTube**, then choose **Add video**. The server imports the whole video at up to 1080p and automatically updates the same audio/video cut used for uploaded clips. Watch download and processing status without keeping the browser open. Originals stay private and retain their YouTube source link.

The same 64-recording, two-hour-per-recording, 3 GiB-per-file and aggregate storage limits apply. One server import runs at a time and reserves a full file slot before downloading. Playlists, active/upcoming livestreams and restricted videos are unsupported. YouTube can reject a server IP; the app reports that without using account cookies or proxies, and file upload remains available. Interrupted downloads can be retried from their source link; partial media is never published.

Local imports require Node.js 22+ on PATH in addition to `bash scripts/crowd-set-dev.sh setup`. The production image includes Node, pinned yt-dlp/EJS and the existing ffmpeg runtime. No extra provider credentials or R2 allowance changes are needed.

Compatible complete single recordings skip video re-encoding and combine the original video with the processed audio. On the full 91-minute ISOKNOCK source, this step took 18.74 seconds locally and preserved every encoded video packet. A 60-second sample using production processed audio took 1.25 seconds on the production host. These timings exclude preparation and cloud transfers. The 126-test backend suite covers packet preservation, processed audio and trailing audio, incompatible timing/rotation/codec fallback, and storage bounds. Copied video can be larger than the ordinary 3 Mbps rendition; admission accounts for its original size and retains the 8 GB cloud cap.
