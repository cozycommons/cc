"""Real Docker + HTTP + MCP + SQLite acceptance test; creates only synthetic app data."""

import asyncio
import json
import os
from pathlib import Path
import sys
import socket
import shlex
import subprocess
import time
import uuid
from websockets.sync.client import connect

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[3]
USERS = json.loads((ROOT / ".apps-dev/users.json").read_text())
NAME = "trip-" + uuid.uuid4().hex[:8]
OTHER = "other-" + uuid.uuid4().hex[:8]
client = httpx.Client(base_url="http://127.0.0.1:8091", timeout=180, trust_env=False)
checks = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    checks.append(message)
    print("PASS " + message, flush=True)


def request(method, path, data=None, user="owner", status=200):
    result = client.request(
        method, path, json=data, headers={"Authorization": "Bearer " + USERS[user]}
    )
    if result.status_code != status:
        raise AssertionError(
            f"{method} {path}: {result.status_code}: {result.text[:1000]}"
        )
    return result.json()


def command(command, user="owner", name=NAME, timeout=120):
    job = request(
        "POST",
        f"/api/apps/{name}/exec",
        {"command": command, "timeout": timeout},
        user=user,
        status=202,
    )
    deadline = time.monotonic() + timeout + 20
    while time.monotonic() < deadline:
        result = request("GET", f"/api/apps/{name}/jobs/{job['id']}", user=user)
        if result["status"] != "running":
            return result
        time.sleep(0.2)
    raise AssertionError("Job did not finish")


def site(name=NAME, service="default", user=None, path="/", method="GET", data=None):
    host = name + ("" if service == "default" else "--" + service) + ".localhost"
    auth = (user, USERS[user]) if user else None
    return httpx.request(
        method,
        "http://127.0.0.1:8090" + path,
        headers={"Host": host},
        auth=auth,
        data=data,
        timeout=10,
        trust_env=False,
    )


def wait_site(service="default", user="owner"):
    for _ in range(60):
        result = site(service=service, user=user)
        if result.status_code == 200:
            return result
        time.sleep(0.25)
    raise AssertionError(
        f"Server did not start: {result.status_code} {result.text[:1000]}"
    )


async def mcp_edit():
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "COMMONS_TOKEN": USERS["friend"],
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app_runtime.mcp_server"], env=env
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            check(
                {tool.name for tool in tools.tools}
                == {"list_apps", "create_app", "set_app_member", "exec_command"},
                "MCP exposes exactly four platform and shell tools",
            )

            async def shell(command):
                result = await session.call_tool(
                    "exec_command", {"app": NAME, "command": command}
                )
                check(not result.isError, "MCP shell call completes")
                job = json.loads(result.content[0].text)
                check(job["exit_code"] == 0, "MCP shell command succeeds")
                return job

            source = (ROOT / "infra/apps/example_trip.py").read_text()
            await shell("printf %s " + shlex.quote(source) + " > /workspace/trip.py")
            check(True, "Second contributor writes app source through MCP shell")
            await shell("printf %s " + shlex.quote("Pack passport\n") + " > /workspace/notes.txt")
            result = await shell("cat /workspace/notes.txt")
            check(result["output"] == "Pack passport\n", "MCP shell reads the saved context")
            await shell("commons expose 3000 --default")
            check(True, "Contributor publishes the default port through MCP shell")
            await shell("commons expose 8080 --name temporary && commons unexpose temporary")
            check("temporary" not in next(a for a in request("GET", "/api/apps") if a["name"] == NAME)["routes"],
                  "MCP shell removes a published route")
            result = await shell("sleep 1; printf mcp-shell")
            check(result["output"] == "mcp-shell", "MCP returns completed command output without polling tools")


async def mcp_provision():
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT / "backend"),
        "COMMONS_TOKEN": USERS["owner"],
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app_runtime.mcp_server"], env=env
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool("create_app", {"name": NAME})
            check(not result.isError, "Agent creates an app through MCP")
            created = json.loads(result.content[0].text)
            check(
                created["repository"]["kind"] == "local",
                "Creation returns local repository metadata",
            )
            for user, role in [("friend", "contributor"), ("viewer", "viewer")]:
                result = await session.call_tool(
                    "set_app_member", {"app": NAME, "user": user, "role": role}
                )
                check(
                    not result.isError,
                    "Owner grants " + role + " membership through MCP",
                )


def automatic_backups(name):
    """Advance only this synthetic app's deadline, leaving the daily interval intact."""
    ids = []
    seen = {b["id"] for b in request("GET", f"/api/apps/{name}/backups", user="outsider")["backups"]}
    for _ in range(4):
        subprocess.run(
            ["docker", "exec", "cc-apps-local-manager", "python", "-c",
             "import sqlite3,sys; c=sqlite3.connect('/state/registry.sqlite3'); "
             "c.execute(\"UPDATE apps SET body=json_set(body, '$.next_backup_at', 0) WHERE name=?\", (sys.argv[1],)); "
             "c.commit()", name],
            check=True,
        )
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            inventory = request("GET", f"/api/apps/{name}/backups", user="outsider")
            snapshots = inventory["backups"]
            if snapshots and snapshots[0]["id"] not in seen:
                ids.append(snapshots[0]["id"])
                seen.add(snapshots[0]["id"])
                break
            time.sleep(0.5)
        else:
            raise AssertionError("Daily scheduler did not produce a backup")
    check([b["id"] for b in snapshots] == ids[-3:][::-1],
          "Daily scheduler retains exactly the latest three backups per app")
    check(all(b["kind"] == "automatic" for b in snapshots),
          "Daily snapshots are marked automatic in owner inventory")
    check(inventory["next_backup_at"] == snapshots[0]["created"] + 86400,
          "Successful backup schedules the next one 24 hours later")
    apps = request("GET", "/api/apps", user="outsider")
    check(next(a for a in apps if a["name"] == name)["status"] == "stopped",
          "Automatic backups leave a stopped app stopped")
    removed = subprocess.run(
        ["docker", "exec", "cc-apps-local-manager", "test", "!", "-e", "/state/backups/" + ids[0]],
    )
    check(removed.returncode == 0, "Retention removes expired snapshot files from storage")
    subprocess.run(["docker", "restart", "cc-apps-local-manager"], check=True, capture_output=True)
    for _ in range(60):
        try:
            if client.get("/health").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    restored = request("GET", f"/api/apps/{name}/backups", user="outsider")
    check(restored == inventory, "Manager restart preserves backup history and daily deadline")


def main():
    asyncio.run(mcp_provision())
    request("POST", "/api/apps", {"name": "forbidden-app"}, user="friend", status=403)
    request("POST", "/api/apps", {"name": OTHER}, user="outsider", status=201)
    request("PUT", f"/api/apps/{NAME}/members/friend", {"role": "contributor"})
    request("PUT", f"/api/apps/{NAME}/members/viewer", {"role": "viewer"})
    check(True, "Two isolated app environments and shared membership created")
    initialized = command(
        'test "$(git symbolic-ref --short HEAD)" = main && test "$(git rev-list --count HEAD)" = 1 && test -z "$(git status --porcelain)" && test -z "$(git remote)"'
    )
    check(
        initialized["exit_code"] == 0,
        "New app has a clean local main repository and initial commit, with no remote",
    )
    ignored = command(
        "git check-ignore home/credentials logs/output.log data/runtime.db .env"
    )
    check(
        ignored["exit_code"] == 0 and len(ignored["output"].splitlines()) == 4,
        "Starter Git ignores credentials, logs and runtime data",
    )
    asyncio.run(mcp_edit())
    for service, port in [("trip", 3000), ("experiment", 8080)]:
        conf = f"[program:{service}]\ncommand=python /workspace/trip.py {port}\ndirectory=/workspace\nautostart=true\nautorestart=true\nstdout_logfile=/workspace/logs/{service}.log\nstderr_logfile=/workspace/logs/{service}-error.log\n"
        if service == "experiment":
            conf += 'environment=PUBLIC_DEMO="1"\n'
        request(
            "PUT",
            f"/api/apps/{NAME}/file",
            {"path": f"/workspace/services/{service}.conf", "content": conf},
            user="friend",
        )
    committed = command(
        "git add trip.py notes.txt services && git commit -m 'Build trip app' && git rev-parse HEAD",
        user="friend",
    )
    check(
        committed["exit_code"] == 0,
        "Contributor commits app source and service configuration to local main",
    )
    main_commit = committed["output"].strip().splitlines()[-1]
    result = command("supervisorctl reread && supervisorctl update", user="friend")
    check(
        result["exit_code"] == 0,
        "Agent starts two supervised web services in one container",
    )
    wait_site()
    check(site().status_code == 401, "Default route is private")
    check(site(user="viewer").status_code == 200, "Viewer can use private website")
    check(
        site(user="outsider").status_code == 404, "Nonmember cannot use private website"
    )
    check(
        site(user="owner", path="/headers").json()["authorization"] is None,
        "Proxy strips platform credentials before forwarding",
    )
    request(
        "POST", f"/api/apps/{NAME}/exec", {"command": "id"}, user="viewer", status=403
    )
    request(
        "PUT",
        f"/api/apps/{OTHER}/routes/default",
        {"port": 3000},
        user="friend",
        status=404,
    )
    check(True, "Viewer shell and cross-app publishing denied")
    result = command("commons expose 8080 --name experiment --public", user="friend")
    check(
        result["exit_code"] == 0,
        "Agent publishes a named public port from inside the container",
    )
    check(
        wait_site("experiment", None).status_code == 200,
        "Named public website is reachable without credentials",
    )
    result = command(
        "test ! -S /var/run/docker.sock && test ! -e /run/users.json && test ! -e /state/registry.sqlite3"
    )
    check(
        result["exit_code"] == 0,
        "Platform socket, registry and user credentials absent from app",
    )
    result = command(
        "python - <<'PY'\nimport socket\ntry: socket.gethostbyname('cc-apps-local-"
        + OTHER
        + "')\nexcept socket.gaierror: print('isolated')\nPY"
    )
    check(
        result["output"].strip() == "isolated",
        "Other app is absent from this app network",
    )
    result = command(
        "test -z \"${DATABASE_URL+x}\" && sqlite3 /workspace/data/trip.sqlite3 'PRAGMA integrity_check;'"
    )
    check(result["exit_code"] == 0 and result["output"].strip() == "ok",
          "App owns a valid SQLite database in its workspace without platform database credentials")
    check("SQLite" in request("GET", f"/api/apps/{NAME}/file?path=/workspace/AGENTS.md")["content"],
          "Starter guidance recommends SQLite without requiring a database engine")
    request(
        "PUT", f"/api/apps/{NAME}/file",
        {"path": "/workspace/websocket-requirements.txt",
         "content": (ROOT / "backend/app_runtime/tests/requirements.txt").read_text()},
    )
    # Stage a hash-verified, platform-independent wheel from setup. The agent
    # still installs it itself, without requiring registry access from the app.
    wheel = next((ROOT / ".apps-dev/wheels").glob("websockets-*-py3-none-any.whl"))
    subprocess.run(
        ["docker", "cp", str(wheel), f"cc-apps-local-{NAME}:/workspace/{wheel.name}"],
        check=True,
    )
    result = command(
        "pip install --disable-pip-version-check --require-hashes --only-binary=:all: "
        "--no-index --find-links=/workspace -r /workspace/websocket-requirements.txt",
        user="friend",
    )
    check(
        result["exit_code"] == 0,
        "Agent installs an additional package inside its container",
    )
    websocket_source = "from websockets.sync.server import serve\nwith serve(lambda ws: ws.send(ws.recv()), '0.0.0.0', 8081) as server: server.serve_forever()\n"
    request(
        "PUT",
        f"/api/apps/{NAME}/file",
        {"path": "/workspace/websocket_demo.py", "content": websocket_source},
    )
    request(
        "PUT",
        f"/api/apps/{NAME}/file",
        {
            "path": "/workspace/services/socket.conf",
            "content": "[program:socket]\ncommand=python /workspace/websocket_demo.py\nautostart=true\nautorestart=true\n",
        },
    )
    check(
        command("supervisorctl reread && supervisorctl update")["exit_code"] == 0,
        "Agent starts a WebSocket service",
    )
    readiness = "import socket,time\nfor _ in range(50):\n try:\n  socket.create_connection(('127.0.0.1',8081),timeout=1).close();break\n except OSError: time.sleep(.1)\nelse: raise RuntimeError('WebSocket server not ready')"
    check(
        command("python -c " + shlex.quote(readiness))["exit_code"] == 0,
        "WebSocket service is listening",
    )
    request("PUT", f"/api/apps/{NAME}/routes/socket", {"port": 8081, "public": True})
    with connect(
        f"ws://{NAME}--socket.localhost:8090",
        sock=socket.create_connection(("127.0.0.1", 8090)),
        proxy=None,
        open_timeout=10,
    ) as ws:
        ws.send("hello commons")
        check(
            ws.recv() == "hello commons", "Published route supports WebSocket upgrades"
        )
    request("DELETE", f"/api/apps/{NAME}/routes/socket")
    check(
        command(
            "supervisorctl stop socket && rm /workspace/services/socket.conf && supervisorctl reread && supervisorctl update"
        )["exit_code"]
        == 0,
        "Agent removes its experimental service",
    )
    result = command("sleep 10", timeout=1)
    check(result["exit_code"] == 124, "Shell timeout terminates a long-running command")
    result = command("python -c 'print(\"x\"*100000)'")
    check(
        result["truncated"] and len(result["output"]) <= 65536,
        "Shell output retention is bounded",
    )
    check(
        site(
            user="viewer", method="POST", data={"note": "Bring hiking shoes"}
        ).status_code
        == 303,
        "Viewer adds synthetic app data through its browser interface",
    )
    request("POST", f"/api/apps/{NAME}/lifecycle/restart")
    check(
        "Bring hiking shoes" in wait_site().text,
        "Registered services and database survive container restart",
    )
    request("POST", f"/api/apps/{NAME}/lifecycle/recreate")
    check(
        "Bring hiking shoes" in wait_site().text,
        "Workspace, services and database survive container replacement",
    )
    check(
        command("commons expose 8080 --name experiment --public")["exit_code"] == 0,
        "Container publication capability works after replacement",
    )
    check(
        command("git rev-parse HEAD")["output"].strip() == main_commit,
        "Local Git history survives container replacement",
    )
    backup = request("POST", f"/api/apps/{NAME}/backups", status=201)
    check(backup["format"] == "workspace-v1" and subprocess.run(
        ["docker", "exec", "cc-apps-local-manager", "test", "!", "-e",
         "/state/backups/" + backup["id"] + "/database.dump"]
    ).returncode == 0, "Backup contains workspace storage without a separate managed database dump")
    request(
        "PUT",
        f"/api/apps/{NAME}/file",
        {"path": "/workspace/notes.txt", "content": "Changed after backup"},
    )
    later = command("git add notes.txt && git commit -m 'Change after backup'")
    check(
        later["exit_code"] == 0, "Agent can create a later local commit after a backup"
    )
    wait_site()
    site(user="viewer", method="POST", data={"note": "This should be undone"})
    check(
        command("python -c " + shlex.quote(
            "import sqlite3; c=sqlite3.connect('/workspace/data/trip.sqlite3'); "
            "c.execute('CREATE TABLE after_backup (note text)'); c.commit()"
        ))["exit_code"] == 0,
        "App can add a database table after backup",
    )
    request(
        "POST",
        f"/api/apps/{NAME}/backups/{backup['id']}/restore",
        {"confirm_replace_data": True},
    )
    check(
        command("python -c " + shlex.quote(
            "import sqlite3; c=sqlite3.connect('/workspace/data/trip.sqlite3'); "
            "assert c.execute(\"SELECT name FROM sqlite_master WHERE name='after_backup'\").fetchone() is None"
        ))["exit_code"] == 0,
        "Restore removes database objects created after the backup",
    )
    page = wait_site().text
    check(
        "Bring hiking shoes" in page and "This should be undone" not in page,
        "Restore recovers the database to its backup",
    )
    check(
        request("GET", f"/api/apps/{NAME}/file?path=/workspace/notes.txt")["content"]
        == "Pack passport\n",
        "Restore recovers workspace files to the same backup",
    )
    check(
        command("git rev-parse HEAD")["output"].strip() == main_commit,
        "Workspace restore recovers .git history and the backed-up main commit",
    )
    request("DELETE", f"/api/apps/{NAME}/routes/experiment")
    check(
        site(service="experiment").status_code == 404,
        "Unpublishing removes public access",
    )
    # Retain the useful demonstration app; stop the extra isolation fixture.
    request("POST", f"/api/apps/{OTHER}/lifecycle/stop", user="outsider")
    automatic_backups(OTHER)
    result = {
        "app": NAME,
        "other_app": OTHER,
        "url": f"http://{NAME}.localhost:8090",
        "checks": checks,
    }
    (ROOT / ".apps-dev/smoke-result.json").write_text(json.dumps(result, indent=2))
    print(
        json.dumps({"app": NAME, "url": result["url"], "checks": len(checks)}),
        flush=True,
    )


if __name__ == "__main__":
    main()
