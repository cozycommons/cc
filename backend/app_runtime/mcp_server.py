"""Vendor-neutral stdio MCP adapter; credentials remain in the client environment."""

from mcp.server.fastmcp import FastMCP

from .client import call, segment

mcp = FastMCP("Cozy Commons apps (local)")


@mcp.tool()
def list_apps() -> list:
    """List apps this person can access and their published services."""
    return call("GET", "/api/apps")


@mcp.tool()
def create_app(name: str) -> dict:
    """Create an app with persistent storage, database and local Git repo on main.

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
    """Start a shell command in /workspace; poll its job ID for output. Maximum 300 seconds."""
    return call(
        "POST",
        f"/api/apps/{segment(app)}/exec",
        {"command": command, "timeout": timeout},
    )


@mcp.tool()
def read_job(app: str, job_id: str) -> dict:
    """Read a command's status, exit code and up to 64 KiB of retained output."""
    return call("GET", f"/api/apps/{segment(app)}/jobs/{segment(job_id)}")


@mcp.tool()
def read_file(app: str, path: str) -> dict:
    """Read a UTF-8 file under /workspace (up to 64 KiB)."""
    return call("GET", f"/api/apps/{segment(app)}/file?path={segment(path)}")


@mcp.tool()
def write_file(app: str, path: str, content: str) -> dict:
    """Write a UTF-8 file under /workspace. Contributors can change all app data."""
    return call(
        "PUT", f"/api/apps/{segment(app)}/file", {"path": path, "content": content}
    )


@mcp.tool()
def expose_port(
    app: str, port: int, name: str = "default", public: bool = False
) -> dict:
    """Publish a running HTTP service. Private by default; public permits anonymous visitors."""
    return call(
        "PUT",
        f"/api/apps/{segment(app)}/routes/{segment(name)}",
        {"port": port, "public": public},
    )


@mcp.tool()
def unexpose_port(app: str, name: str = "default") -> dict:
    """Remove a published route; the underlying process continues running."""
    return call("DELETE", f"/api/apps/{segment(app)}/routes/{segment(name)}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
