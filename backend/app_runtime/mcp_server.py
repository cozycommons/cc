"""Vendor-neutral stdio MCP adapter; credentials remain in the client environment."""

import time

from mcp.server.fastmcp import FastMCP

from .client import call, segment

mcp = FastMCP("Cozy Commons apps (local)")


@mcp.tool()
def list_apps() -> list:
    """List apps this person can access and their published services."""
    return call("GET", "/api/apps")


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
def exec_command(app: str, command: str, timeout: int = 120) -> dict:
    """Run a shell command in /workspace and return status, exit_code and output.

    Waits for completion; timeout is 1–300 seconds. Retains the last 64 KiB of
    output with a truncated flag. Use shell commands to read/write files and
    `commons expose PORT --default` / `commons unexpose default` to publish or
    remove HTTP/WebSocket routes. Publishing is private unless --public is set.
    Use supervisor for persistent services; a command timeout terminates the shell.
    """
    base = f"/api/apps/{segment(app)}"
    job = call("POST", base + "/exec", {"command": command, "timeout": timeout})
    # The manager owns execution, timeout enforcement and output bounds. Poll
    # here so agents need only one tool call, without giving containers job access.
    deadline = time.monotonic() + timeout + 15
    while True:
        result = call("GET", base + "/jobs/" + segment(job["id"]))
        if result["status"] != "running":
            return result
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Manager did not finish reporting job {job['id']}; "
                "inspect it through the platform CLI before retrying the command"
            )
        time.sleep(0.2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
