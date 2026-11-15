# Coco box tools

Coco is agent agnostic: external agents, optional resident harnesses and future
workers use the same authenticated interface. These are development tools for
app owners/contributors. An app's end-user WebMCP interface is separate and grants
no box access.

## Shell jobs

Start with `exec_command(app, command, idempotency_key, cwd?, timeout_seconds?,
wait_ms?, max_output_bytes?)`. Supply a unique key for each intended execution;
retry the **same key and execution parameters** after a disconnected start.
Default cwd is `/workspace`, timeout 120 seconds (maximum 300), wait 1000 ms
(maximum 10000), returned output 4096 UTF-8 bytes (maximum 65536, minimum four).
Each call starts a fresh noninteractive shell; cwd/environment do not persist and
stdin is EOF. Use supervisor for services and `commons expose/unexpose` for routes.

- `job_read(app, job_id, cursor=0, wait_ms=1000, max_output_bytes=4096)` reads state
  and output without starting anything. Resume the returned `next_cursor`.
- `job_cancel(app, job_id)` requests cancellation. Read until terminal; requesting
  cancellation does not mean the process has stopped or earlier effects were undone.

Results retain legacy `id`/`status` alongside `job_id`/`state`. State is `running`,
`cancel_requested`, `completed`, `cancelled`, `failed`, or `interrupted`.
A nonzero exit code is an ordinary completed job. `unknown` with
`start_accepted: true` means the manager accepted a start but its follow-up read
failed; recover using the job ID or original key. A lost start response itself
may have executed: never substitute a fresh key merely because the request failed.

The manager retains the last 64 KiB of normalized UTF-8 output. `available_from`
and `output_gap` identify discarded history; `more_output` means another page is
available. Cursors refer to normalized UTF-8 bytes and must be character boundaries.
Invalid source bytes are replaced by the incremental decoder; use binary file
transfer for exact bytes. Output caps bound content, not the complete escaped MCP
message. Metadata, escaping and compatibility text/structured projections add cost.

Command, timeout and cwd determine retry identity. Wait/output limits do not.
The original cwd/default timeout fingerprint remains compatible with older jobs.
Manager restart marks running jobs interrupted and never silently replays them;
interruption does not prove that an old process stopped. Idempotency prevents
ordinary duplicate dispatch, not arbitrary exactly-once external effects.

During migration, legacy `exec_command` fields `timeout`, `job_id`, `after`,
`cancel`, and keyless starts remain supported. New clients should use the split
job tools and always supply keys. Starts with nonzero `after` reject before effects.

## Precision files

All paths below are workspace-relative, including spaces/Unicode literally;
parent directories must exist. Symlinks, hardlinks and nonregular files are
unsupported. Files and aggregate edit content are bounded at 1 MiB; encoded
requests at 2 MiB. Shell and binary transfer remain available for larger files.

- `read_files(app, files=[{path, start_line?, line_count?}], max_output_bytes?)`:
  line numbers start at one; default 200 lines, maximum 2000 per file. Up to
  32 files share a fair content budget (default/maximum 65536 bytes). Results
  include content, whole-file `sha256`, size, newline style, final-newline flag,
  `whole_file`, `truncated` and `read_status`. A hash does not imply all bytes
  were returned. Read errors are per-file fixed codes. Use targeted shell reads
  for huge/minified lines; no byte-reader is exposed yet.
- `edit_files(app, files=[{path, expected_sha256, edits:[{old_text,new_text}]}])`:
  up to 16 files; each exact old text must match once. The whole batch validates
  hashes/matches before replacement. Unrelated bytes, newline conventions and
  existing permission bits are preserved. Reread conflicts; do not retry blindly.
- `write_file(app, path, content, expected_sha256)`:
  null hash means create-only; replacement requires the current whole-file hash.
  Never replace a whole file from a truncated read.

Structured file operations serialize per app with maintenance/backups, and active
body readers/helpers share bounded per-user/global slots. Arbitrary shell or app
writers do not participate: the preconditions are not a universal filesystem CAS.
Atomic replacement preserves mode bits, not every owner/ACL/xattr/hardlink detail.
Batch edits are not crash-safe multi-file transactions. `PARTIAL_WRITE` explicitly
means a late replacement failed and some files may already have changed: inspect
all affected files. Runtime/transport errors can likewise have unknown effects.

OAuth box reads, edits, job polling and cancellation require `commons:edit` plus
current contributor/owner membership, because even reading box files/logs can
expose app secrets. Read-only tool annotations are hints, not permissions.
No tool accepts platform bearer credentials as arguments. Unknown arguments and
validation errors reject without echoing supplied content or extra field names.

## Existing controls

`list_apps`, `create_app`, `set_app_member`, `transfer_file`, and `app_backups`
remain available. No raw patch, persistent terminal, Code Mode or mandatory native
MCP Tasks capability is introduced. Standard MCP and the local stdio adapter expose
the same working operations; hosted authorization is rechecked on every call.
