"""Real Docker + HTTP + MCP acceptance test; creates only synthetic app data."""

import asyncio
import json
import os
from pathlib import Path
import sys
import socket
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
                "exec_command" in [tool.name for tool in tools.tools],
                "MCP handshake and generic shell tool discovery",
            )
            result = await session.call_tool(
                "write_file",
                {
                    "app": NAME,
                    "path": "/workspace/trip.py",
                    "content": (ROOT / "infra/apps/example_trip.py").read_text(),
                },
            )
            check(
                not result.isError, "Second contributor writes app source through MCP"
            )
            result = await session.call_tool(
                "write_file",
                {
                    "app": NAME,
                    "path": "/workspace/notes.txt",
                    "content": "Pack passport\n",
                },
            )
            check(not result.isError, "MCP persists a context file")
            result = await session.call_tool(
                "read_file", {"app": NAME, "path": "/workspace/notes.txt"}
            )
            check(
                not result.isError and "Pack passport" in str(result.content),
                "MCP reads the same context back",
            )
            result = await session.call_tool("expose_port", {"app": NAME, "port": 3000})
            check(
                not result.isError, "Contributor publishes the default port through MCP"
            )
            result = await session.call_tool(
                "exec_command", {"app": NAME, "command": "printf mcp-shell"}
            )
            check(not result.isError, "MCP starts a shell command")
            job_id = json.loads(result.content[0].text)["id"]
            for _ in range(40):
                result = await session.call_tool(
                    "read_job", {"app": NAME, "job_id": job_id}
                )
                job = json.loads(result.content[0].text)
                if job["status"] != "running":
                    break
                await asyncio.sleep(0.1)
            check(
                job["exit_code"] == 0 and job["output"] == "mcp-shell",
                "MCP polls command output",
            )


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
        "python - <<'PY'\nimport os, psycopg\nurl=os.environ['DATABASE_URL'].rsplit('/',1)[0]+'/app_"
        + OTHER.replace("-", "_")
        + "'\ntry: psycopg.connect(url)\nexcept psycopg.OperationalError: print('denied')\nPY"
    )
    check(
        result["output"].strip() == "denied",
        "App database role cannot connect to another app database",
    )
    result = command(
        "pip install --disable-pip-version-check websockets==15.0.1", user="friend"
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
        command("python -c " + __import__("shlex").quote(readiness))["exit_code"] == 0,
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
    request(
        "POST",
        f"/api/apps/{NAME}/backups/{backup['id']}/restore",
        {"confirm_replace_data": True},
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
