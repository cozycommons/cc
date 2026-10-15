# Crowd Set — timing MVP

## Summary
Create a performance, add recordings from that same performance, and listen to a reconstruction assembled only from crowd recordings. The approved milestone order is **3 timing → 1 individual cleanup → 2 sonic consistency**. This slice implements timing plus basic constant-gain volume matching, added after the user listened to the first experiment.

Figma: none provided; use a small accessible Commons-adjacent workspace. Keep visible copy to useful labels, actions, status, and input constraints. No slogans or audio-engineering explainer blocks; optional diagnostics contain concise measurements.

## Behavior
1. `/crowd-set` lets a user create/select a named performance. Empty, loading, upload, processing, ready, and failure states are explicit. Existing Commons and Dice routes remain stable.
2. Users may upload one timing reference and multiple crowd clips, with clear role labels. Adding recordings without a reference is allowed, but reconstruction requires a reference in this MVP. Reference-free alignment is deferred.
3. Reference audio is never included in the output, including where crowd coverage is absent. Output time zero and duration correspond to the reference; gaps remain audible silence and are listed on the timeline.
4. Inputs are local audio/video files. The prototype reports supported extensions, upload/duration/count limits, decode failures, and missing decoder dependencies. Only files with decodable audio are accepted for processing. It does not claim decoding improves audio.
5. Processing runs asynchronously and exposes stage/status/errors. Edits and duplicate processing are blocked during active work. Reload preserves completed state; interrupted jobs become failed with a retry path. Local mode is single-user; hosted mode requires Cozy Commons sign-in and restricts each set to its owner. Shared collaboration is deferred.
6. Each successfully decoded crowd clip is matched or unmatched, with an explanation, similarity score (not a probability), window agreement, and timing uncertainty. Weak, ambiguous, inconsistent, too-short, or nonoverlapping evidence abstains rather than forcing a placement. Approximate matching is not phase alignment or a guarantee against repeated-song false matches.
7. A matched clip is placed on the common timeline, trimmed to reference bounds. Coverage uses a deterministic source selection favoring longer continuous coverage. Users can exclude individual crowd clips before rerunning. No acoustic-quality claim is attached to automatic selection.
8. Source changes use short linear crossfades only inside real overlapping coverage. Gaps are never compressed, crossfaded across, or filled with reference. Basic measured constant-gain volume matching reduces avoidable source-level jumps. Prefer the same overlapping passage, with a disclosed whole-clip fallback when overlap is too short. Preserve within-clip dynamics and true-peak headroom. No compression, limiting, EQ, or noise matching is performed; static attenuation is not noise removal.
9. If no clips match, the result explicitly has no crowd coverage and no playable reconstruction. A completed reconstruction offers native audio controls and WAV download, with selected source intervals and gaps. Keyboard-accessible labels, status text, and textual timeline intervals accompany visual coverage.
10. Uploading, removing, or excluding inputs invalidates the old reconstruction. Failures remain visible and can be corrected/retried. No uploads can change while work is active. Stored performances can be deleted when idle.
11. The local launcher remains loopback-only. Hosted testing is authorized on the existing Cozy Commons Coolify server, with existing sign-in, owner isolation, bounded resources, and persistent storage. It must preserve Commons/Dice routing and the old Dice deployment. No new account system or database migrations are included. Media is never committed.

## Deferred
Denoising, bass restoration, learned enhancement, drift correction, manual timing edits, reference-free alignment, video editing, and advanced sonic consistency. Full-set matches require listening review; sampled timing checks cannot certify every moment.

## Separate work pieces
- Social-link ingestion: paste/forward Instagram posts (all video items), TikTok, or YouTube links into the eventual clip pipeline without downloading on the phone. Preserve source provenance and separate post items, surface partial/unavailable imports, and do not promise universal downloadability. This is a distinct future workstream, not part of the upload/timing MVP.
