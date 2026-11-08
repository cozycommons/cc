# Agent transport

Apps are programmable containers. The six MCP tools cover platform access and
transport; shell still owns builds, databases, logs, previews and release choices.
Both the local stdio adapter and the hosted Cozy Commons connector expose them.

## Inventory

`list_apps()` remains compact. `list_apps(details=true)` adds selected Docker
state, last exit code, OOM flag, timestamps, restart count, CPU/memory/PID limits
and sampled usage. CPU percent is relative to one core (100% = one full core).
Missing/unlimited limits and unavailable usage fields are null. Diagnostics
explain missing samples. Viewers may inspect these same platform metrics. Samples
are cached for up to five seconds; at most two inspections run concurrently.
CPU usage is null when a one-shot sample has no previous counters. Disk usage, process logs and health checks remain shell
operations; this view never executes app code or returns Docker environment or
host mounts. Published routes remain in the normal app inventory.

## Shell jobs

Start with a unique key and bounded wait:

```json
{"app":"weekend","command":"python analyze.py","idempotency_key":"analyze-1","wait_ms":1000,"timeout":120}
```

A running response includes `id`, `status`, `output`, `output_start`,
`next_cursor`, `bytes_seen`, `truncated` and `exit_code`. Reconnect using the same
tool, omitting command:

```json
{"app":"weekend","job_id":"EXACT_RETURNED_ID","after":1234,"wait_ms":1000}
```

Use the returned `next_cursor` as the next `after` value. Cursors count bytes in
UTF-8 output. Polling returns all available output since that cursor, up to the
retained 64 KiB tail. `truncated=true` means the caller missed output; `output_start`
is the earliest retained byte. Calls wait at most 0–10000 milliseconds for
completion, then return a running result. This is polling, not server-pushed logs.

Retry a disconnected start with the **same key, command and timeout** to recover
the original job. Different parameters with the same key conflict. Keys are
scoped to app and caller. Legacy starts without keys remain supported but cannot
be safely resubmitted after an unknown outcome. Commands are never automatically
replayed. Jobs remain in the manager registry; no automatic expiration is imposed.

`exec_command(app, job_id=..., cancel=true)` requests termination of the job's
container process group, including children that remain in that group. Cancellation
is best-effort: a wedged container or exhausted PID limit can prevent the helper
from starting; an owner may need to restart the app. Cancellation can reconnect to an
interrupted job too. Timeout terminates the group and reports exit code 124;
observed cancellation reports cancelled/130. Normal completion also terminates
remaining members of the command's group, including ordinary background jobs.
Use supervisor for persistent services. New-session/double-fork processes escape
that group; redirect their stdio or use supervisor. A manager watchdog closes an
exec stream after the command timeout plus seven seconds, so escaped children
cannot leave a job permanently running. If the root exec still runs, the result
is failed/unknown; closing the stream does not claim to have killed escaped children.
Manager restart marks monitored jobs interrupted: output collection does not
resume, and the container command may still run until its timeout or cancellation.
An interrupted status is not proof that the command stopped or had no effect.
Every poll, retry and cancellation rechecks contributor membership and edit scope.

## File transfer

`transfer_file` takes `app`, an absolute file `path` under `/workspace`, and
`direction=upload|download`. Upload requires `content_base64` and its lowercase
hexadecimal SHA-256; download returns those fields plus `size_bytes`. Upload
writes a temporary file beside the destination and atomically replaces it with
mode 0600. Set executable permissions through shell when needed. Retrying an
identical upload replaces the file with the same bytes; it does not append.

MCP files are limited to **2 MiB**, leaving base64 and JSON overhead below the
existing hosted MCP 4 MiB request-body protection. Binary HTTP/CLI files support
**16 MiB**. Pack directories into an archive and transfer
that file; split larger files using shell. Archives remain opaque and are never
extracted by the platform. Reads and writes require contributor membership and
edit scope. No public or credential-bearing transfer URLs are created. One transfer per caller
and two globally may run concurrently. Upload bodies have a 30-second deadline;
requests fail promptly when the app is locked for maintenance. Helper metadata
has an 8 KiB output cap and a 30-second deadline. Upload acknowledgements are
computed by the manager rather than returned from container-controlled output.

Archive operations require a security-supported, patched Docker Engine. File
paths are resolved inside the container; contributors already control the entire
container as root. Workspace path checks are a file-tool convenience, not a
security boundary against hostile container-root contributors.

For binary clients, use authenticated `GET /api/apps/APP/transfer?path=...` and
`PUT /api/apps/APP/transfer?path=...&sha256=...` with a raw binary request body.
Downloads include `X-Content-SHA256`; optional `max_bytes` rejects files above a
caller-selected limit before returning content. This avoids base64 expansion in JSON MCP
transports. The local CLI handles local files directly:

```bash
scripts/apps-dev.sh cli upload weekend ./source.tgz /workspace/source.tgz
scripts/apps-dev.sh cli download weekend /workspace/results.tgz ./results.tgz
```

## Platform snapshots

`app_backups(app, action=list)` returns owner-only inventory, next scheduled time
and any backup error. Create and restore require ownership and edit scope:

```json
{"app":"weekend","action":"create","idempotency_key":"before-edit-1"}
```

Create briefly stops a running app, archives its workspace including SQLite and
Git history, resumes it and retains the newest three successful snapshots.
Restore needs an exact listed `backup_id`, a new `idempotency_key`, and
`confirm_replace_data=true` after explicit user approval. It replaces all current
workspace data. Membership and platform routes are not restored from app files.

API and CLI snapshot mutations require keys too. Repeat the same request/key to
retrieve the recorded outcome without restoring again. Outcomes live in the
manager registry, outside restored workspaces. A manager interruption or execution
failure can leave an unknown outcome: the same key returns a conflict instead of
repeating the operation. Inspect inventory and actual app state before deciding
whether to issue a new key. Known precondition rejections are also recorded: after resolving the cause, use
a new key. Corrupt manifests reject before any workspace mutation. Only exact,
platform-authored diagnostics cross the hosted OAuth bridge; arbitrary upstream
error bodies are suppressed. These records have no automatic expiration.

Local CLI examples:

```bash
scripts/apps-dev.sh cli backup weekend --idempotency-key before-edit-1
scripts/apps-dev.sh cli backups weekend
scripts/apps-dev.sh cli restore weekend BACKUP_ID --confirm-replace-data --idempotency-key restore-1
```

Snapshots remain subject to the platform's documented retention and off-server
recovery limitations. They do not snapshot external databases or OS packages
outside `/workspace`.
