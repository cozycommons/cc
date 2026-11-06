"""Local-only app manager. Hosted identity and deployment are intentionally separate."""

import base64
import hmac
import html
import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .core import Store, allowed, digest, hostname, proxy_config, service_name, slug
from .docker_runtime import Runtime

state = Path(os.environ.get("APPS_STATE", "/state"))
state.mkdir(parents=True, exist_ok=True)
store = Store(state / "registry.sqlite3")
users = json.loads(Path(os.environ.get("APPS_USERS", "/run/users.json")).read_text())
config_path = Path(os.environ.get("APPS_PROXY_CONFIG", "/proxy/Caddyfile"))
creators = set(os.environ.get("APPS_CREATORS", "owner").split(","))
runtime = Runtime()
app = FastAPI(title="Cozy Commons apps — local prototype")
# A restarted manager cannot reliably continue monitoring an old Docker exec.
for old_job in store.all("jobs"):
    if old_job["status"] == "running":
        old_job.update(
            status="interrupted",
            error="Manager restarted; inspect the app before retrying",
        )
        store.put(old_job, "jobs")


@app.middleware("http")
async def reject_cross_origin_mutations(request: Request, call_next):
    origin = request.headers.get("origin")
    if (
        request.method not in {"GET", "HEAD", "OPTIONS"}
        and origin
        and origin not in {"http://admin.localhost:8090", "http://127.0.0.1:8091"}
    ):
        return Response("Cross-origin platform mutation denied", status_code=403)
    return await call_next(request)


def identify(request: Request):
    header = request.headers.get("authorization", "")
    token = ""
    user = None
    if header.startswith("Bearer "):
        token = header[7:]
    elif header.startswith("Basic "):
        try:
            user, token = (
                base64.b64decode(header[6:], validate=True).decode().split(":", 1)
            )
        except (ValueError, UnicodeDecodeError):
            pass
    if token:
        for name, expected in users.items():
            if (user is None or user == name) and hmac.compare_digest(token, expected):
                return name
        if user is None:
            for record in store.all():
                if hmac.compare_digest(digest(token), record["app_token_hash"]):
                    return "app:" + record["name"]
    return None


def identity(request: Request):
    result = identify(request)
    if result is None:
        raise HTTPException(
            401,
            "Sign in with a local username and its token",
            headers={"WWW-Authenticate": 'Basic realm="Cozy Commons local"'},
        )
    if result.startswith("app:"):
        expected = "/api/apps/" + result[4:] + "/routes/"
        if request.method not in {"PUT", "DELETE"} or not request.url.path.startswith(
            expected
        ):
            raise HTTPException(
                403, "Container capability only permits publishing this app's ports"
            )
    return result


def authorized(name, who, required="viewer"):
    record = store.get(name)
    if not record or not allowed(record, who, "viewer"):
        raise HTTPException(404, "App not found")
    if not allowed(record, who, required):
        raise HTTPException(403, "Insufficient app permissions")
    return record


def ready(record):
    if record["status"] != "running" or runtime.status(record["name"]) != "running":
        raise HTTPException(409, "App is not running")


def public_record(record, who):
    return {
        "name": record["name"],
        "repository": record.get("repository"),
        "status": runtime.status(record["name"])
        if record["status"] in {"running", "stopped"}
        else record["status"],
        "role": record["members"].get(who, "contributor"),
        "routes": {
            name: {**route, "url": f"http://{hostname(record['name'], name)}:8090"}
            for name, route in record["routes"].items()
        },
    }


def sync_proxy():
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temp = config_path.with_suffix(".tmp")
    temp.write_text(proxy_config(store.all()))
    temp.replace(config_path)
    runtime.reload_proxy()


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return Response(
        json.dumps({"detail": str(exc)}), status_code=422, media_type="application/json"
    )


@app.get("/health")
def health():
    return {"status": "ok", "mode": "local-prototype"}


@app.get("/", response_class=HTMLResponse)
def index(who=Depends(identity)):
    rows = []
    for record in store.all():
        if not allowed(record, who):
            continue
        view = public_record(record, who)
        links = " · ".join(
            f'<a href="{html.escape(route["url"])}">{html.escape(name)}</a> ({"public" if route["public"] else "private"})'
            for name, route in view["routes"].items()
        )
        rows.append(
            f"<tr><td>{html.escape(view['name'])}</td><td>{view['status']}</td><td>{view['role']}</td><td>{links or 'No published ports'}</td></tr>"
        )
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>Apps</title><style>body{font:16px system-ui;max-width:900px;margin:48px auto;padding:0 24px;color:#292b26;background:#f7f6f1}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:16px 8px;border-bottom:1px solid #ddd}a{color:#375c49}</style></head><body><h1>Apps</h1><table><tr><th>App</th><th>Status</th><th>Role</th><th>Services</th></tr>'
        + "".join(rows)
        + "</table></body></html>"
    )


@app.get("/api/apps")
def list_apps(who=Depends(identity)):
    return [
        public_record(record, who) for record in store.all() if allowed(record, who)
    ]


class Create(BaseModel):
    name: str = Field(max_length=30)


@app.post("/api/apps", status_code=201)
def create(body: Create, who=Depends(identity)):
    if who.startswith("app:"):
        raise HTTPException(403, "An app cannot create other apps")
    if who not in creators:
        raise HTTPException(403, "App creation is not enabled for this identity")
    name = slug(body.name)
    with store.lock:
        if store.get(name):
            raise HTTPException(409, "App name already allocated")
        token = secrets.token_urlsafe(32)
        record = {
            "name": name,
            "members": {who: "owner"},
            "routes": {},
            "status": "creating",
            "repository": {
                "kind": "local",
                "initial_path": "/workspace",
                "default_branch": "main",
            },
            "db_password": secrets.token_hex(24),
            "app_token_hash": digest(token),
        }
        store.put(record)
        try:
            runtime.create(record, token)
            record["status"] = "running"
            store.put(record)
            sync_proxy()
        except Exception:
            record["status"] = "error"
            store.put(record)
            raise
    return public_record(record, who)


class Member(BaseModel):
    role: str


@app.put("/api/apps/{name}/members/{user}")
def member(name: str, user: str, body: Member, who=Depends(identity)):
    with store.lock:
        record = authorized(name, who, "owner")
        if user not in users or body.role not in {"viewer", "contributor", "none"}:
            raise HTTPException(
                422, "Choose a known local user and viewer, contributor, or none"
            )
        if record["members"].get(user) == "owner":
            raise HTTPException(409, "Owner transfer is not supported in the prototype")
        if body.role == "none":
            record["members"].pop(user, None)
        else:
            record["members"][user] = body.role
        store.put(record)
    return {"members": record["members"]}


class Route(BaseModel):
    port: int = Field(ge=1024, le=65535)
    public: bool = False


@app.put("/api/apps/{name}/routes/{service}")
def expose(name: str, service: str, body: Route, who=Depends(identity)):
    service_name(service)
    with store.lock:
        record = authorized(name, who, "contributor")
        previous = dict(record["routes"])
        record["routes"][service] = body.model_dump()
        store.put(record)
        try:
            sync_proxy()
        except Exception:
            record["routes"] = previous
            store.put(record)
            config_path.write_text(proxy_config(store.all()))
            raise HTTPException(503, "Proxy reload failed; route change was not saved")
    return public_record(record, who)


@app.delete("/api/apps/{name}/routes/{service}")
def unexpose(name: str, service: str, who=Depends(identity)):
    with store.lock:
        record = authorized(name, who, "contributor")
        record["routes"].pop(service, None)
        store.put(record)
        # Authorization also denies missing routes if the proxy cannot reload.
        sync_proxy()
    return public_record(record, who)


@app.get("/authorize/{name}/{service}")
def authorize_route(name: str, service: str, request: Request):
    record = store.get(name)
    route = record and record["routes"].get(service)
    if not route:
        raise HTTPException(404, "Route not found")
    if record["status"] != "running":
        raise HTTPException(503, "App is unavailable")
    if not route["public"]:
        authorized(name, identity(request))
    return Response(status_code=204)


class Command(BaseModel):
    command: str = Field(min_length=1, max_length=16000)
    timeout: int = Field(default=120, ge=1, le=300)


def execute_job(job, command, timeout):
    def output(chunk):
        with store.lock:
            size = len(chunk.encode())
            job["output"] = (
                (job["output"] + chunk).encode()[-65536:].decode(errors="ignore")
            )
            job["truncated"] = job["truncated"] or job["bytes_seen"] + size > 65536
            job["bytes_seen"] += size
            store.put(job, "jobs")

    try:
        code = runtime.run(job["app"], command, timeout, output)
        job.update(status="finished", exit_code=code)
    except Exception as exc:
        job.update(status="failed", error=str(exc)[:1000])
    with store.lock:
        store.put(job, "jobs")


@app.post("/api/apps/{name}/exec", status_code=202)
def execute(name: str, body: Command, who=Depends(identity)):
    with store.lock:
        record = authorized(name, who, "contributor")
        ready(record)
        if (
            sum(
                j["status"] == "running" and j["app"] == name for j in store.all("jobs")
            )
            >= 4
        ):
            raise HTTPException(429, "Four commands are already running")
        job = {
            "id": uuid.uuid4().hex,
            "app": name,
            "status": "running",
            "output": "",
            "bytes_seen": 0,
            "truncated": False,
            "exit_code": None,
        }
        store.put(job, "jobs")
        threading.Thread(
            target=execute_job, args=(job, body.command, body.timeout), daemon=True
        ).start()
    return {"id": job["id"], "status": "running"}


@app.get("/api/apps/{name}/jobs/{job_id}")
def job_result(name: str, job_id: str, who=Depends(identity)):
    authorized(name, who, "contributor")
    job = store.get(job_id, "jobs")
    if not job or job["app"] != name:
        raise HTTPException(404, "Job not found")
    return job


class FileWrite(BaseModel):
    path: str = Field(max_length=2000)
    content: str = Field(max_length=65536)


@app.get("/api/apps/{name}/file")
def read_file(name: str, path: str, who=Depends(identity)):
    record = authorized(name, who, "contributor")
    ready(record)
    return {"content": runtime.file(name, path)}


@app.put("/api/apps/{name}/file")
def write_file(name: str, body: FileWrite, who=Depends(identity)):
    record = authorized(name, who, "contributor")
    ready(record)
    runtime.file(name, body.path, body.content)
    return {"written": body.path}


@app.post("/api/apps/{name}/lifecycle/{action}")
def lifecycle(name: str, action: str, who=Depends(identity)):
    if action not in {"start", "stop", "restart", "recreate"}:
        raise HTTPException(422, "Choose start, stop, restart or recreate")
    with store.lock:
        record = authorized(name, who, "owner")
        if action == "recreate":
            record["status"] = "maintenance"
            store.put(record)
            token = secrets.token_urlsafe(32)
            try:
                runtime.container(name).stop(timeout=10)
                runtime.container(name).remove()
                runtime.create_container(record, token)
                record["app_token_hash"] = digest(token)
            except Exception:
                record["status"] = "error"
                store.put(record)
                raise
        else:
            getattr(runtime.container(name), action)()
        record["status"] = "stopped" if action == "stop" else "running"
        store.put(record)
    return public_record(record, who)


@app.post("/api/apps/{name}/backups", status_code=201)
def backup(name: str, who=Depends(identity)):
    with store.lock:
        record = authorized(name, who, "owner")
        ready(record)
        backup_id = uuid.uuid4().hex
        folder = state / "backups" / backup_id
        folder.mkdir(parents=True)
        record["status"] = "maintenance"
        store.put(record)
        runtime.container(name).stop(timeout=10)
        try:
            runtime.dump(name, folder / "database.dump")
            runtime.archive(name, backup_id)
            (folder / "manifest.json").write_text(
                json.dumps({"app": name, "id": backup_id, "created": time.time()})
            )
        finally:
            runtime.container(name).start()
            record["status"] = "running"
            store.put(record)
    return {"id": backup_id, "app": name}


class Restore(BaseModel):
    confirm_replace_data: bool = False


@app.post("/api/apps/{name}/backups/{backup_id}/restore")
def restore(name: str, backup_id: str, body: Restore, who=Depends(identity)):
    if not body.confirm_replace_data:
        raise HTTPException(
            422,
            "Restore replaces current workspace and database; confirm_replace_data is required",
        )
    if not len(backup_id) == 32 or any(c not in "0123456789abcdef" for c in backup_id):
        raise HTTPException(404, "Backup not found")
    with store.lock:
        record = authorized(name, who, "owner")
        folder = state / "backups" / backup_id
        if (
            not (folder / "manifest.json").exists()
            or json.loads((folder / "manifest.json").read_text())["app"] != name
        ):
            raise HTTPException(404, "Backup not found")
        record["status"] = "maintenance"
        store.put(record)
        runtime.container(name).stop(timeout=10)
        try:
            runtime.restore_db(name, folder / "database.dump")
            runtime.archive(name, backup_id, restore=True)
            runtime.container(name).start()
            record["status"] = "running"
        except Exception:
            # Keep the app stopped when restore is incomplete.
            record["status"] = "error"
            raise
        finally:
            store.put(record)
    return public_record(record, who)
