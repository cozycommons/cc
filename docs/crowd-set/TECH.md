# Crowd Set implementation

## Architecture
Retain the separate FastAPI package and optional Python environment, local loopback port 8010, and `/crowd-set` React route. Hosted mode uses a separate Docker application on the existing HTTPS origin, existing Supabase Auth identity and authenticated shared-set JSON metadata with uploader ownership. No shared backend initialization, database or migration changes.

## Processing and publication
- New sets carry schema version 2; normal uploads use the recording role. Existing crowd roles are compatible ordinary contributions. Legacy reference roles remain excluded, preserving the old explicit timing-only contract without deleting media.
- Decode included ordinary uploads to bounded 32 kHz mono float WAVs. Preserve peaks above full scale until gained PCM quantization. Measure finite samples, energy, clipping fraction, near-silent one-second blocks, and loudness to determine usable sources. Choose longest duration, then fewer clipped samples, fewer silent blocks, stable UUID. Quality has no influence across different durations.
- Analyze the chosen source with the existing spectral-change features. Give it offset zero and match other sources to it with existing conservative multiwindow checks. There is no graph solver. Very short clips cannot match another source but can be the sole usable source.
- Plan union bounds from all included matches; shift offsets by the earliest start, keeping original anchor-relative origin in metadata. Keep all matched clip extents and true gaps. Retain farthest-ending coverage selection and overlap-only 80 ms fades.
- Retain overlap-based static loudness gains, whole-clip fallback and final true-peak verification. Worker writes `pending.wav` and result metadata. It never changes the published mix.
- Store commits a successful pending file under a fresh generated mix filename, then atomically replaces set metadata pointing to it. This pointer is the publication boundary. Prior result remains playable through upload/edit/start/failure/recovery. Keep the preceding audio until the next job cleanup to avoid deleting a file before an already-authorized response opens it. Recovery discards temporary job outputs; it never discards the published pointer. A failed metadata publication leaves the prior mix authoritative.
- Dirty state tracks recordings awaiting an automatic update; failed or interrupted updates expose a retry. A single Store timer debounces pending builds for three seconds and dispatches them through the existing single-worker pool. New changes reset that set's pending deadline. Uploads to a running set are blocked, so in-flight snapshots cannot become stale; queued sets accept further uploads. On restart, queued/running jobs resume from cached preparation, at most twice automatically before requiring explicit Retry. Cache versioned audio analysis and feature arrays beside immutable originals. Keep one upload and one worker globally, block edits to a busy set, retain process-group deadlines and inherited flock across parent crashes.

Upload batches use an explicit begin/finish boundary: processing stays held while all selected files are attempted, then exactly one update is queued for successful additions. Single-file uploads queue automatically. Failed files remain named in the UI error; successful originals and the old mix are retained. An abandoned batch settles after 60 seconds without an active upload; an in-flight chunk holds the batch open and has a two-minute body deadline. Reselecting the same files resumes committed offsets after interruption or restart. Only the initiating signed-in uploader can append to or finish their batch.

## Original media and UI
An authorized `/sets/{set_id}/clips/{clip_id}/media` endpoint streams the immutable original through FileResponse with MIME selected from a fixed extension map, inline playback, byte ranges and optional attachment download. It uses the same shared/private set middleware and secure playback cookie as compiled audio. Never expose storage paths or tokens in URLs. Native video is used for MP4/MOV/WEBM, audio for audio extensions; browser codec compatibility varies, so original downloads remain available.

The UI has a set list/create form, set detail with one compiled video player (audio fallback), direct video upload, and original media cards. Preserve published player identity through edits and processing; change its revision only when a replacement publishes. Status is concise. No reference, gain, alignment or diagnostic controls. Retain original removal as a simple per-recording action; inclusion remains an API compatibility operation. Legacy reference cards say “Original only” and cannot be toggled into ordinary contributions.

## Bounds and operations
Maintain 64 recordings per set, 2 GiB/file, 20 sets, two hours per recording, eight aggregate hours per set, ten-minute decoder/measurement deadlines and a one-hour job deadline. Local defaults reserve 16 GiB for originals, 8 GiB for generated work and a 2 GiB physical free floor. R2 originals, unfinished transfers and retained mixes share a hard 8,000,000,000-byte application quota, independent of the 8 GiB local work budget. The original legacy reference may remain longer but is not newly decoded. Single-worker generated storage is bounded. Atomic JSON and volume persistence handle ordinary restarts, not guaranteed power-loss durability.

Hosted image uses `/crowd-set/` assets, non-root user, persistent `/data`, 2 CPU/2 GiB cap, one replica and manual deployment. Exact-prefix routing preserves other apps. Browser request-policy errors must be recovered normally, never bypassed. The service was first deployed on 2026-10-16; the capacity/storage extension still requires its own rollout.

## Mix timeline
Show one read-only strip spanning the actual compiled duration, with proportional selected source segments, stable colors shared with original cards, and actual gaps. Mark overlap fades within the same strip. Provide compact contributing-source links and segment time details, a playhead and click/keyboard seeking. No separate source tracks or editing controls. Merely aligned recordings must not appear as contributors.

The user explicitly authorized converting the known local five-minute Niteharts fixture from its superseded timing-only role to an eligible ordinary recording. Preserve that original's provenance and bytes, then rebuild. This narrow local data migration does not change unrelated legacy sets, their privacy or recording roles.

## Checks
Use synthetic alignment/union/gap tests; a real worker/API test for original video, anchor inclusion, publication and restart; two-user shared/private catalog, contribution, deletion and media/range authorization tests; failure injection preserving old audio; and frontend tests proving straightforward browse/upload/play/update behavior and stable current playback. Existing frontend/backend CI and dedicated Ubuntu/macOS/container checks remain required. Preserve research evidence separately from current implementation claims.

## Larger set capacity and recovery

Baseline: `4a235044321f6c612285862659f619207dfd013b`. Existing audio analysis and rendering already use fixed-size blocks and memory-mapped WAV/features. Preserve these algorithms and matching thresholds. Production has a 38 GiB disk with 28 GiB free as observed on 2026-10-18; the 4 GiB host previously exhausted memory during concurrent builds, so keep one build and one processing worker.

- Centralize validated operator settings and expose active upload limits through the authenticated catalog endpoint's `limits` query. Default 64 recordings, 2 GiB/file, 2h/file, 8h/set, 16 GiB originals, 8 GiB generated, 2 GiB physical free floor, 8 MiB chunks, 24h upload expiry, 1h job deadline, 10min media subprocess deadline.
- Introduce a narrow filesystem original-store boundary. New immutable originals live in `originals/<set>/<recording>`, upload parts/manifests in `uploads/<set>/`; legacy original paths remain readable without migration. Working WAV/features and current mix retain the set directory. Optional private R2 and Supabase Storage providers materialize originals into bounded staging and proxies authorized range media responses; it does not change recording IDs. Its private immutable object keys include recording ID and full SHA256. A durable object ledger accounts for uploaded and unpublished revisions; the current and preceding mix generations survive cleanup.
- Reserve declared original bytes across all unfinished sessions. Admission counts originals, parts, reservations and actual generated work, and reserves the unused work quota plus host free floor on the real filesystem. Reject new work before quota/free-space exhaustion. Probe duration using the existing restricted decoder; bound actual decode by the probed duration and reject inconsistent/oversized media. Reserve cumulative expected float WAVs/features and a new worst-case union mix before a job. Enforce actual aggregate duration as decoding completes.
- Persist upload owner, set, file fingerprint, size, committed offset, expiry and completion state in atomic manifests. Every append/finalize checks ownership and batch binding. Verify chunk SHA256, require the expected offset, and make exact retries idempotent. Flush committed bytes before advancing offset; truncate uncommitted tails on restart. Complete via immutable rename and idempotent catalog insertion.
- Persist batch IDs/owner/expiry alongside each set and persist pending job state in existing metadata. Reconstruct timers on startup, retain unfinished resumable sessions, and requeue interrupted jobs at most twice; independent parent/child job deadlines remain coordinated. Preserve inherited directory flock and process-group termination.
- Cache alignment by immutable source ID, anchor ID and analysis version; changing anchor invalidates matches. Add per-recording progress. Keep native media `preload=none` for the catalog's recording cards.
- Preserve all host/origin/owner guards. Local legacy direct PUT uploads retain compatibility; cloud mode rejects old clients with a reload instruction, so all cloud originals use the checked resumable finalizer. No database or production credentials are added.

### Verification

Exercise 51 inputs, count/byte/duration/quota boundaries, concurrent original reservations, low physical disk, wrong owner/batch/offset/checksum, lost append/finalize responses, partial chunk crash recovery, expired sessions, resumed batch and job recovery limits, previous mix publication, legacy original reads, and anchor-cache invalidation. Run a cold synthetic full-length-anchor/many-clip worker test with measured wall time and peak RSS; record actual results without claiming full-set musical alignment accuracy. Run existing backend/frontend suites, build/lint/container checks and a signed-in production upload/restart/download smoke test.

### Growth boundary

Private R2 is the selected provider for independent original/media durability; the Supabase adapter remains optional. A transactional leased database queue is the next step when direct concurrent uploads or multiple processing hosts are needed. Use immutable private object keys, authorized short-lived transfers, per-user quotas, job leases/fencing, and idempotent publication. That requires explicit provider capacity, backups and production schema rollout; do not simulate it by adding more JSON writers or sharing the flocked directory across hosts.


### Supabase Storage deployment

Configure `CROWD_SET_STORAGE_KEY` as a server-only Supabase secret/service-role key and `CROWD_SET_STORAGE_BUCKET=crowd-set-media`; never prefix the secret with VITE or include it in build arguments. Reuse `CROWD_SET_AUTH_URL`. The bucket must be private with an explicit file limit at least `CROWD_SET_MAX_FILE_BYTES`, and the project's global upload limit must also permit that size. Startup validates the bucket before opening the catalog. Cloud bytes transfer with TUS in 6 MiB chunks, durable server transfer offsets, immutable keys and size verification. Downloads are streamed with server authorization; no public URLs or credentials reach the browser.

`CROWD_SET_ORIGINAL_BYTES` defaults to 80 GiB with cloud storage, 16 GiB otherwise. Both include pending reservations; cloud output publication reserves its bytes before upload. After the new pointer commits, garbage collection retains the current and preceding mix objects and deletes older/unpublished revisions. Failed cleanup retains its ledger reservation and retries with the next job. Local staging and caches remain on `/data`, which still needs independent backup for set ownership, metadata, manifests and job state. Supabase object durability alone does not back up this metadata or provide multi-writer coordination.

As checked on 2026-10-19, Cozy Commons is on Supabase Free (50 MB maximum file size). Enabling 2 GiB cloud uploads requires an approved plan upgrade and global/bucket limit change. Pro starts at $25/month, includes 100 GB storage and 250 GB egress, with usage charges above allowances. No plan, bucket, production credentials or existing originals have been changed by this implementation. Legacy filesystem originals remain readable, so no automatic bulk migration is needed for rollout.


### R2 free-tier deployment (selected provider)

Use a dedicated private Standard-class bucket. Disable public `r2.dev` access, leave custom domains unset, and configure a one-day abort lifecycle for incomplete multipart uploads. Do not enable Infrequent Access, replication, event consumers or other paid features. Inspect account-wide current and month-to-date storage/operation usage before activation; this app cannot limit unrelated clients. R2 has no hard free-tier billing cutoff. Standard includes 10 GB-month, 1 million Class A and 10 million Class B requests monthly, with free direct egress ([official pricing](https://developers.cloudflare.com/r2/pricing/)). Budget alerts do not stop charges ([billing alerts](https://developers.cloudflare.com/billing/manage/budget-alerts/)).

Configure these Coolify **runtime-only** variables:

```text
CROWD_SET_STORAGE_PROVIDER=r2
CROWD_SET_STORAGE_BUCKET=cozycommons-crowd-set
CROWD_SET_R2_ACCOUNT_ID=<Cloudflare account ID>
CROWD_SET_R2_ACCESS_KEY_ID=<bucket-scoped Object Read & Write access key>
CROWD_SET_R2_SECRET_ACCESS_KEY=<secret access key>
CROWD_SET_ORIGINAL_BYTES=8000000000
```

Keep credentials out of VITE variables, build arguments, logs and Git. Before enabling the provider on the existing persistent volume, initialize the request budget **once** for the new empty bucket using the new image with provider unset and the R2 variables available:

```bash
python -m crowd_set.r2 --initialize-budget
```

Then enable `CROWD_SET_STORAGE_PROVIDER=r2` and restart through Coolify. Initialization refuses to overwrite an existing ledger. Back up `/data/r2-requests.sqlite`, `/data/objects/` and `/data/r2-transfers/` alongside the complete metadata volume. Never restore an older request ledger or reset counters to regain allowance; reconcile any recovery against actual account usage first. Switching buckets/accounts requires explicit usage reconciliation, not deletion of the ledger.

Every HTTP attempt consumes a durable SQLite budget before network access: 100,000 Class A and 1,000,000 Class B over the latest 35 UTC days. Missing/corrupt counters, account mismatch or a clock rollback pause requests. Cleanup DELETE/Abort requests are free and remain available for known upload IDs; an interrupted creation must first be reconciled with a budgeted listing. HTTP retries and redirects are disabled. SigV4 credentials are restricted to the configured HTTPS account host. Startup reconciles every remote object and unfinished multipart transfer against the persistent local ledger; unknown objects, uploads or non-Standard storage block startup.

Each original or mix has one immutable key and a full-size reservation before any part transfer. Sequential 8 MiB multipart uploads persist creation intent before the request and the upload ID before sending bytes, resume existing parts after validating their size/MD5, and verify completed size and SHA256 metadata. Lost completion responses are recovered by HEAD. Aborting/deleting must be acknowledged before releasing reservations. Current and previous mixes, pending originals and orphaned transfers all consume the 8 GB cap. Local staging still needs the existing work/free-space quotas. The 2 GiB per-file ceiling also remains enforced. No transcoding or automatic original migration is performed.

Rollout must verify a small authenticated upload, playback and byte-range download against the real bucket, followed by a service restart and replay. Inspect provider usage after the smoke test. Code/mock tests alone do not confirm a live R2 connection or account-level $0 billing.

### Event metadata API (frontend handoff)

`GET /crowd-set/sets?limits=true` advertises `event_metadata: true`. `POST /crowd-set/sets` still requires `name` (1–120 characters); legacy `{name}` creation remains valid. Structured creation additionally supplies all five top-level fields together: `artist` (1–120), `venue` (1–160), `starts_at`, `ends_at`, and `timezone` (valid IANA zone). Blank strings and partial event objects return 422 without creating a set.

Datetime strings use ISO format with `T`. Native `datetime-local` values without an offset are resolved in `timezone` on the server. Nonexistent or ambiguous daylight-saving wall times return 422; the API accepts an explicit offset to disambiguate. Offset-aware inputs represent their stated instant (including `Z`); timezone remains the event's display zone. End must be strictly later than start. A midnight crossing supplies the next calendar date explicitly. Stored/returned start and end are UTC ISO strings with `+00:00`; artist/venue are trimmed. All five fields persist and appear unchanged in authorized list/detail responses across restart. Old sets may omit every field. Event metadata does not establish clip timing, affect audio alignment, or change permissions.

The frontend can search and surface likely duplicates from this authorized catalog; the server does not claim a duplicate-prevention guarantee. No guessed contributor display names or compiled-video endpoint are added. Existing uploader IDs remain internal identifiers, not display attribution.


## Canonical video publication

`video.py` probes the first decoded audio and moving-video timestamps (excluding attached cover art), then bounds picture coverage using the final packet PTS plus duration from a copy-only, 128 MiB-limited packet scan. Analysis cache version 2 retains their relationship. A separate deterministic visual planner uses all confident ordinary videos, the existing audio union origin, and a single 24 fps global frame grid. It chooses farthest-ending active coverage with stable ID ties and represents gaps explicitly. Audio selection, alignment and fades remain unchanged.

Render segments sequentially to an 854×480 square-pixel H.264 canvas with aspect-preserving padding, auto rotation, one encoder thread, 600 kbps VBV ceiling and a neutral background after early video EOF. Seek using the decoded audio origin rather than assuming container/video zero. Concatenate verified frame counts and mux 96 kbps AAC from the finished WAV into one faststart MP4. Each output has a conservative byte bound; reserve local space for both intermediate segments and final output, plus one materialized original. Existing process-group, worker and subprocess deadlines apply. Failed/restarted work removes only abandoned render/cache copies, preserving immutable originals and published media.

Reserve combined cloud audio/video bytes before either upload. Both private objects must finish before the single durable set metadata replacement commits their shared revision and timelines. The current and preceding manifests/files/objects survive cleanup; uncommitted generations retain their quota reservation until remote cleanup succeeds. Audio and video endpoints honor `v` and serve only current/previous revision pointers with the existing authentication and byte-range path. No public object URL or credential enters the browser.

The video player replaces the audio player only when `video_playable` is true. Its source is revision-pinned, and polling/upload states preserve its identity until successful publication. Audio-only/legacy results continue using the audio player. Event timestamps do not influence rendering.
