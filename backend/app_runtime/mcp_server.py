"""Vendor-neutral stdio MCP adapter; credentials remain in the client environment."""

import time

from mcp.server.fastmcp import FastMCP

from .client import call, segment
from .tool_helpers import transfer_request, snapshot_request, validate_exec

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
                 after: int = 0, wait_ms: int = 1000, cancel: bool = False) -> dict:
    """Start shell or reconnect to job_id. Use a unique idempotency_key for safe start retries.

    Returns within wait_ms (0–10000) with job ID, incremental output and next_cursor.
    Reconnect with after=next_cursor. Retains 64 KiB and explicitly reports dropped output.
    cancel stops the command process group. Jobs continue after disconnect; manager restart
    marks them interrupted without rerunning. Timeout is 1–300 seconds. Requires contributor.
    Use supervisor for services; commons expose/unexpose publishes ports, private by default.
    """
    validate_exec(command, job_id, cancel, after, wait_ms)
    base = f"/api/apps/{segment(app)}"
    if command is not None:
        data = {"command": command, "timeout": timeout}
        if idempotency_key is not None:
            data['idempotency_key'] = idempotency_key
        job = call("POST", base + "/exec", data)
        job_id = job['id']
    path = base + '/jobs/' + segment(job_id)
    if cancel:
        call('POST', path + '/cancel')
    deadline = time.monotonic() + wait_ms / 1000
    while True:
        result = call('GET', path + '?after=' + str(after))
        if result['status'] != 'running' or time.monotonic() >= deadline:
            return result
        time.sleep(.2)


@mcp.tool()
def transfer_file(app: str, path: str, direction: str,
                  content_base64: str | None = None, sha256: str | None = None) -> dict:
    """Transfer one binary file/opaque archive up to 16 MiB under /workspace.

    Upload requires base64 content and SHA-256; atomically replaces the file. Download returns
    base64 and SHA-256. Use shell to pack/unpack directories. Contributor access required.
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
