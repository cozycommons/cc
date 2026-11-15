"""Vendor-neutral stdio MCP adapter; credentials remain in the client environment."""

import httpx

from mcp_sdk_validation import FastMCP

from .client import call, segment
from .text_file_models import TextReadSpec, TextEditSpec, ReadFilesRequest, EditFilesRequest, WriteFileRequest
from .tool_helpers import transfer_request, snapshot_request, validate_exec, execution_request, job_query, uncertain_job, cancellation_result

mcp = FastMCP("Cozy Commons apps (local)")


@mcp.tool()
def list_apps(details: bool = False) -> list:
    """List apps this person can access and their published services."""
    return call("GET", "/api/apps?details=true" if details else "/api/apps")


@mcp.tool()
def create_app(name: str) -> dict:
    """Create an app with persistent workspace storage and local Git repo on main.

    Requires platform creation permission, separate from contributing to an app.
    Does not deploy any website; use the shell to build/start services and expose a port.
    """
    return call("POST", "/api/apps", {"name": name})


@mcp.tool()
def set_app_member(app: str, user: str, role: str) -> dict:
    """As owner, grant a known local user viewer/contributor access, or revoke with none."""
    return call(
        "PUT", f"/api/apps/{segment(app)}/members/{segment(user)}", {"role": role}
    )


@mcp.tool()
def exec_command(app: str, command: str | None = None, timeout: int = 120,
                 idempotency_key: str | None = None, job_id: str | None = None,
                 after: int = 0, wait_ms: int = 1000, cancel: bool = False,
                 cwd: str | None = None, timeout_seconds: int | None = None,
                 max_output_bytes: int = 4096) -> dict:
    """Start a fresh shell job; supply idempotency_key and retry identical execution after disconnect.

    Returns job_id/state/output/next_cursor. Use job_read/job_cancel to continue. cwd defaults
    /workspace; no persistent shell state or interactive stdin. Use supervisor for services.
    Legacy timeout/job_id/after/cancel and keyless starts remain temporarily supported.
    """
    validate_exec(command, job_id, cancel, after, wait_ms)
    query = job_query(after, wait_ms, max_output_bytes, completion=True)
    if job_id is not None and (cwd is not None or timeout_seconds is not None or idempotency_key is not None):
        raise ValueError('Continuation takes app/job_id/cursor/wait/output only; use job_read')
    base = f"/api/apps/{segment(app)}"
    started = command is not None
    if started:
        data = execution_request(command, timeout, idempotency_key, cwd, timeout_seconds)
        job = call('POST', base + '/exec', data)
        job_id = job['id']
    path = base + '/jobs/' + segment(job_id)
    if cancel:
        call('POST', path + '/cancel')
    try:
        return call('GET', path + query)
    except (httpx.HTTPError, ValueError):
        if not started:
            raise
        return uncertain_job(job_id)


@mcp.tool()
def job_read(app: str, job_id: str, cursor: int = 0, wait_ms: int = 1000,
             max_output_bytes: int = 4096) -> dict:
    """Read bounded new output/state without starting work. Resume next_cursor; gaps are explicit.

    Requires contributor access. wait_ms waits briefly for output/completion. UTF-8 byte cursors.
    """
    if not job_id.strip():
        raise ValueError('job_id must be nonblank')
    return call('GET', f'/api/apps/{segment(app)}/jobs/{segment(job_id)}' +
                job_query(cursor, wait_ms, max_output_bytes))


@mcp.tool()
def job_cancel(app: str, job_id: str) -> dict:
    """Request cancellation, then job_read until terminal. Cancellation never rolls back effects."""
    if not job_id.strip():
        raise ValueError('job_id must be nonblank')
    return cancellation_result(call('POST', f'/api/apps/{segment(app)}/jobs/{segment(job_id)}/cancel'))


@mcp.tool()
def read_files(app: str, files: list[TextReadSpec], max_output_bytes: int = 65536) -> dict:
    """Read bounded UTF-8 files with whole-file hashes and completeness/newline metadata.

    Paths are workspace-relative; files at most 1 MiB. Shared content cap at most 64 KiB.
    Contributor required even for reads. Use shell for large/binary files. No symlinks/hardlinks.
    """
    body = ReadFilesRequest(files=files, max_output_bytes=max_output_bytes)
    return call('POST', f'/api/apps/{segment(app)}/text/read', body.model_dump(exclude_none=True))


@mcp.tool()
def edit_files(app: str, files: list[TextEditSpec]) -> dict:
    """Exact unique replacements with whole-file hash preconditions. Reread conflicts.

    Preserve unrelated bytes/newlines/modes. Batch validates first, not a durable transaction.
    Structured operations serialize; arbitrary shell writers bypass the lock. Contributor required.
    """
    body = EditFilesRequest(files=files)
    return call('POST', f'/api/apps/{segment(app)}/text/edit', body.model_dump())


@mcp.tool()
def write_file(app: str, path: str, content: str, expected_sha256: str | None) -> dict:
    """Create/replace UTF-8 text up to 1 MiB. Relative path; existing parent required.

    Null expected_sha256 means create-only; replacement requires current hash. Never overwrite
    using truncated content. Atomic replacement preserves mode, not arbitrary shell writer safety.
    """
    body = WriteFileRequest(path=path, content=content, expected_sha256=expected_sha256)
    return call('POST', f'/api/apps/{segment(app)}/text/write', body.model_dump())


@mcp.tool()
def transfer_file(app: str, path: str, direction: str,
                  content_base64: str | None = None, sha256: str | None = None) -> dict:
    """Transfer one binary file/opaque archive up to 2 MiB over MCP under /workspace.

    Upload requires base64 content and SHA-256; atomically replaces the file. Download returns
    base64 and SHA-256. Use shell to pack/unpack or split directories; HTTP/CLI supports 16 MiB. Contributor access required.
    """
    method, query, content = transfer_request(path, direction, content_base64, sha256)
    return call(method, f'/api/apps/{segment(app)}/transfer' + query, content=content)


@mcp.tool()
def app_backups(app: str, action: str = 'list', idempotency_key: str | None = None,
                backup_id: str | None = None, confirm_replace_data: bool = False) -> dict:
    """Owner-only snapshot list/create/restore. Create/restore require an idempotency key.

    Create briefly stops the app; retains three snapshots. Restore replaces current workspace,
    data and Git history: obtain explicit user approval before confirm_replace_data=true.
    Retry the same request/key after disconnect; inspect unknown outcomes before any new key.
    """
    method, path, data = snapshot_request(action, idempotency_key, backup_id, confirm_replace_data)
    return call(method, f'/api/apps/{segment(app)}' + path, data)


# Match the canonical closed-object contract, including direct SDK dispatch.
for tool in mcp._tool_manager.list_tools():
    tool.fn_metadata.arg_model.model_config['extra'] = 'forbid'
    tool.fn_metadata.arg_model.model_rebuild(force=True)
    tool.parameters['additionalProperties'] = False


if __name__ == "__main__":
    mcp.run(transport="stdio")
