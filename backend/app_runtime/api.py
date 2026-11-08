"""App manager with separate loopback and explicitly configured hosted modes."""

import asyncio
import base64
from contextlib import asynccontextmanager, contextmanager

import hmac
import hashlib
import html
import json
import os
import secrets
import threading
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from .backups import BackupRejected, Backups, INTERVAL
from .core import Store, allowed, digest, hostname, proxy_config, service_name, slug
from .docker_runtime import Runtime, TRANSFER_LIMIT
from .settings import Settings
from request_validation import install as install_validation
from .hosted_auth import HostedAuth, BROWSER_HEADERS, clean_cookie
from fastapi.responses import RedirectResponse
from uuid import UUID

settings = Settings.load()

state = Path(os.environ.get("APPS_STATE", "/state"))
state.mkdir(parents=True, exist_ok=True)
store = Store(state / "registry.sqlite3")
users = {} if settings.hosted else json.loads(Path(os.environ.get("APPS_USERS", "/run/users.json")).read_text())
hosted_auth = HostedAuth(settings, store) if settings.hosted else None
config_path = Path(os.environ.get("APPS_PROXY_CONFIG", "/proxy/Caddyfile"))
creators = set(filter(None, os.environ.get("APPS_CREATORS", "" if settings.hosted else "owner").split(",")))
runtime = Runtime()
backups = Backups(store, runtime, state)
proxy_lock = threading.RLock()
transfer_slots = threading.BoundedSemaphore(2)
transfer_users = set()
inspection_slots = threading.BoundedSemaphore(2)
inspection_cache = {}
UPLOAD_BODY_TIMEOUT = 30


@asynccontextmanager
async def lifespan(app):
    if settings.hosted:
        # Proxy waits for manager health on first boot. Never expose a stale
        # public route without the manager's per-request authorization.
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temp = config_path.with_suffix('.tmp')
        temp.write_text(proxy_config(store.all(), settings))
        temp.replace(config_path)
    stop = threading.Event()
    worker = threading.Thread(target=backups.run, args=(stop,), daemon=True)
    worker.start()
    try:
        yield
    finally:
        stop.set()
        await asyncio.to_thread(worker.join)


app = FastAPI(title="Cozy Commons apps", lifespan=lifespan)
install_validation(app)
if hosted_auth:
    hosted_auth.install(app)
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
    if settings.hosted:
        # Cookies only authorize browser reads. Even bearer-authenticated writes
        # from browsers must originate on the central portal, except per-host
        # session/logout endpoints with their own exact Origin check.
        allowed_origins = {settings.url(settings.portal)}
        auth_path = request.url.path in {"/_commons/session", "/_commons/logout"}
    else:
        allowed_origins = {"http://admin.localhost:8090", "http://127.0.0.1:8091"}
        auth_path = False
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in allowed_origins and not auth_path:
        return Response("Cross-origin platform mutation denied", status_code=403)
    response = await call_next(request)
    if settings.hosted:
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('Content-Security-Policy', BROWSER_HEADERS['Content-Security-Policy'] + "; style-src 'unsafe-inline'")
    return response


def identify(request: Request):
    # Only request-local memoization: browser routes consult Auth once while
    # every subsequent HTTP request still revalidates identity and membership.
    if not hasattr(request.state, 'apps_identity'):
        request.state.apps_identity = _identify(request)
    return request.state.apps_identity


def _identify(request: Request):
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
        if user is None:
            for record in store.all():
                if hmac.compare_digest(digest(token), record["app_token_hash"]):
                    return "app:" + record["name"]
        for name, expected in users.items():
            if (user is None or user == name) and hmac.compare_digest(token, expected):
                return name
    if hosted_auth:
        return hosted_auth.identify(request)
    return None


def identity(request: Request):
    result = identify(request)
    if result is None:
        raise HTTPException(
            401,
            "Sign in to Cozy Commons Apps" if settings.hosted else "Sign in with a local username and its token",
            headers={"WWW-Authenticate": "Bearer" if settings.hosted else 'Basic realm="Cozy Commons local"'},
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
            name: {**route, "url": settings.url(hostname(record["name"], name, settings))}
            for name, route in record["routes"].items()
        },
    }


def route_audience(route):
    # Private routes default to contributors: whatever the server returns may
    # include source, so viewers see a route only when it was published for them.
    if route["public"]:
        return "public"
    return "members" if route.get("viewers") else "contributors"


def sync_proxy():
    with proxy_lock:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        temp = config_path.with_suffix(".tmp")
        temp.write_text(proxy_config(store.all(), settings))
        temp.replace(config_path)
        runtime.reload_proxy()


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return Response(
        json.dumps({"detail": str(exc)}), status_code=422, media_type="application/json"
    )


@app.get("/health")
def health():
    return {"status": "ok", "mode": "hosted" if settings.hosted else "local-prototype"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if hosted_auth and not identify(request):
        return RedirectResponse("/_commons/login", headers=BROWSER_HEADERS)
    who = identity(request)
    rows = []
    for record in store.all():
        if not allowed(record, who):
            continue
        view = public_record(record, who)
        links = " · ".join(
            f'<a href="{html.escape(route["url"])}">{html.escape(name)}</a> ({route_audience(route)})'
            for name, route in view["routes"].items()
        )
        rows.append(
            f"<tr><td>{html.escape(view['name'])}</td><td>{view['status']}</td><td>{view['role']}</td><td>{links or 'No published ports'}</td></tr>"
        )
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>Apps</title><style>body{font:16px system-ui;max-width:900px;margin:48px auto;padding:0 24px;color:#292b26;background:#f7f6f1}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:16px 8px;border-bottom:1px solid #ddd}a{color:#375c49}</style></head><body><h1>Apps</h1><table><tr><th>App</th><th>Status</th><th>Role</th><th>Services</th></tr>'
        + "".join(rows)
        + "</table>"
        + (f'<p>Your Commons user ID: <code>{html.escape(who)}</code></p><p>Synthetic-data pilot. Agent tools are on the Cozy Commons connector.</p><form action="/_commons/logout" method="post"><button>Sign out of Apps</button></form>' if settings.hosted else "")
        + "</body></html>"
    )


def runtime_details(name):
    with store.lock:
        cached = inspection_cache.get(name)
        if cached and time.monotonic() - cached[0] < 5:
            return cached[1]
    if not inspection_slots.acquire(blocking=False):
        return {"usage": None, "diagnostic": "Runtime inspection busy; retry shortly"}
    try:
        details = runtime.inspect(name)
        with store.lock:
            if len(inspection_cache) >= 128 and name not in inspection_cache:
                inspection_cache.pop(next(iter(inspection_cache)))
            inspection_cache[name] = (time.monotonic(), details)
        return details
    except Exception:
        return {"usage": None, "diagnostic": "Runtime inspection unavailable"}
    finally:
        inspection_slots.release()


@app.get("/api/apps")
def list_apps(details: bool = False, who=Depends(identity)):
    result = []
    for record in store.all():
        if allowed(record, who):
            view = public_record(record, who)
            if details:
                view["runtime"] = runtime_details(record["name"])
            result.append(view)
    return result


class Create(BaseModel):
    name: str = Field(max_length=30)


@app.post("/api/apps", status_code=201)
def create(body: Create, request: Request, who=Depends(identity)):
    if who.startswith("app:"):
        raise HTTPException(403, "An app cannot create other apps")
    can_create = hosted_auth.can_create(request.headers.get('authorization', '')[7:], who) if hosted_auth else who in creators
    if not can_create:
        raise HTTPException(403, "Only Commons admins may create hosted apps" if hosted_auth else "App creation is not enabled for this identity")
    name = slug(body.name)
    with store.app_lock(name):
        if store.get(name):
            raise HTTPException(409, "App name already allocated")
        token = secrets.token_urlsafe(32)
        record = {
            "name": name,
            "members": {who: "owner"},
            "routes": {},
            "status": "creating",
            "next_backup_at": time.time() + INTERVAL,
            "repository": {
                "kind": "local",
                "initial_path": "/workspace",
                "default_branch": "main",
            },
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
    with store.app_lock(name):
        record = authorized(name, who, "owner")
        try:
            known = str(UUID(user)) == user if settings.hosted else user in users
        except ValueError:
            known = False
        if not known or body.role not in {"viewer", "contributor", "none"}:
            raise HTTPException(
                422, "Choose a user UUID and viewer, contributor, or none" if settings.hosted else "Choose a known local user and viewer, contributor, or none"
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
    viewers: bool = False


@app.put("/api/apps/{name}/routes/{service}")
def expose(name: str, service: str, body: Route, who=Depends(identity)):
    service_name(service)
    with store.app_lock(name), proxy_lock:
        record = authorized(name, who, "contributor")
        previous = dict(record["routes"])
        record["routes"][service] = body.model_dump()
        store.put(record)
        try:
            sync_proxy()
        except Exception:
            record["routes"] = previous
            store.put(record)
            config_path.write_text(proxy_config(store.all(), settings))
            raise HTTPException(503, "Proxy reload failed; route change was not saved")
    return public_record(record, who)


@app.delete("/api/apps/{name}/routes/{service}")
def unexpose(name: str, service: str, who=Depends(identity)):
    with store.app_lock(name), proxy_lock:
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
    if hosted_auth:
        if hosted_auth.host(request) != hostname(name, service, settings):
            raise HTTPException(400, "Route host mismatch")
    if not route["public"]:
        if hosted_auth:
            if not hosted_auth.same_app(request, name):
                raise HTTPException(403, "Requests from another app cannot use this app's sign-in")
            if not identify(request):
                return RedirectResponse("/_commons/login", status_code=303, headers=BROWSER_HEADERS)
        authorized(name, identity(request), "viewer" if route.get("viewers") else "contributor")
    headers = {"X-Commons-App-Cookie": clean_cookie(request.headers.get("cookie", ""))} if hosted_auth else {}
    return Response(status_code=204, headers=headers)


class Command(BaseModel):
    command: str = Field(min_length=1, max_length=16000)
    timeout: int = Field(default=120, ge=1, le=300)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


def execute_job(job, command, timeout):
    def output(chunk):
        with store.lock:
            current = store.get(job["id"], "jobs")
            size = len(chunk.encode())
            current["output"] = (current["output"] + chunk).encode()[-65536:].decode(errors="ignore")
            current["truncated"] = current["truncated"] or current["bytes_seen"] + size > 65536
            current["bytes_seen"] += size
            store.put(current, "jobs")
    try:
        code = runtime.run(job["app"], command, timeout, output, job_id=job["id"])
        changes = {"status": "finished", "exit_code": code}
    except Exception:
        changes = {"status": "failed", "error": "Command execution failed; inspect app state before retrying"}
    with store.lock:
        current = store.get(job["id"], "jobs")
        if current.get("cancel_requested") and changes.get("exit_code") == 130:
            changes["status"] = "cancelled"
        current.update(changes, finished_at=time.time())
        store.put(current, "jobs")


def job_view(job, after=None):
    result = {key: value for key, value in job.items()
              if key not in {"request_hash", "caller", "idempotency_key"}}
    end = job["bytes_seen"]
    raw = job["output"].encode()
    start = end - len(raw)
    result.update(output_start=start, next_cursor=end)
    if after is not None:
        if after > end:
            raise HTTPException(422, "Output cursor is ahead of this job")
        result["output"] = raw[max(0, after-start):].decode(errors="ignore")
        result["truncated"] = after < start
    return result


@app.post("/api/apps/{name}/exec", status_code=202)
def execute(name: str, body: Command, who=Depends(identity)):
    with store.app_lock(name):
        record = authorized(name, who, "contributor")
        job_id = digest(json.dumps([name, who, body.idempotency_key]))[:32] if body.idempotency_key else uuid.uuid4().hex
        request_hash = digest(json.dumps([body.command, body.timeout]))
        previous = store.get(job_id, "jobs")
        if previous:
            if previous.get("request_hash") != request_hash:
                raise HTTPException(409, "Idempotency key already used for a different command")
            return job_view(previous)
        ready(record)
        if sum(j["status"] == "running" and j["app"] == name for j in store.all("jobs")) >= 4:
            raise HTTPException(429, "Four commands are already running")
        job = {"id": job_id, "app": name, "status": "running", "output": "",
               "bytes_seen": 0, "truncated": False, "exit_code": None,
               "request_hash": request_hash, "caller": who, "created_at": time.time()}
        store.put(job, "jobs")
        threading.Thread(target=execute_job, args=(job, body.command, body.timeout), daemon=True).start()
    return job_view(job)


def owned_job(name, job_id, who):
    authorized(name, who, "contributor")
    job = store.get(job_id, "jobs")
    if not job or job["app"] != name:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/apps/{name}/jobs/{job_id}")
def job_result(name: str, job_id: str, after: int | None = Query(default=None, ge=0), who=Depends(identity)):
    return job_view(owned_job(name, job_id, who), after)


@app.post("/api/apps/{name}/jobs/{job_id}/cancel")
def cancel_job(name: str, job_id: str, who=Depends(identity)):
    with store.app_lock(name):
        job = owned_job(name, job_id, who)
        if job["status"] in {"running", "interrupted"}:
            ready(authorized(name, who, "contributor"))
            with store.lock:
                job = owned_job(name, job_id, who)
                if job["status"] not in {"running", "interrupted"}:
                    return job_view(job)
                job["cancel_requested"] = True
                store.put(job, "jobs")
            runtime.cancel(name, job_id)
        return job_view(store.get(job_id, "jobs"))


@contextmanager
def transfer_slot(who):
    with store.lock:
        if who in transfer_users:
            raise HTTPException(429, "A file transfer is already active for this caller; retry shortly")
        transfer_users.add(who)
    acquired = transfer_slots.acquire(blocking=False)
    try:
        if not acquired:
            raise HTTPException(429, "Two file transfers are already active; retry shortly")
        yield
    finally:
        if acquired:
            transfer_slots.release()
        with store.lock:
            transfer_users.remove(who)


@contextmanager
def transfer_app(name, who):
    with transfer_slot(who):
        lock = store.app_lock(name)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "App is busy; retry this transfer after maintenance")
        try:
            yield
        finally:
            lock.release()


@app.get("/api/apps/{name}/transfer")
def download_file(name: str, path: str = Query(max_length=2000),
                  max_bytes: int = Query(default=TRANSFER_LIMIT, ge=1, le=TRANSFER_LIMIT), who=Depends(identity)):
    authorized(name, who, "contributor")
    with transfer_app(name, who):
        ready(authorized(name, who, "contributor"))
        result = runtime.transfer(name, path, max_bytes=max_bytes)
    return Response(result["content"], media_type="application/octet-stream",
                    headers={"X-Content-SHA256": result["sha256"], "Cache-Control": "no-store"})


@app.put("/api/apps/{name}/transfer")
async def upload_file(name: str, request: Request, path: str = Query(max_length=2000),
                      sha256: str = Query(pattern="^[a-f0-9]{64}$"), who=Depends(identity)):
    # Bound bytes before buffering a potentially untrusted request body.
    authorized(name, who, "contributor")
    with transfer_slot(who):
        content = bytearray()
        try:
            async with asyncio.timeout(UPLOAD_BODY_TIMEOUT):
                async for chunk in request.stream():
                    if len(content) + len(chunk) > TRANSFER_LIMIT:
                        raise HTTPException(413, "Transfer exceeds 16 MiB; split using shell")
                    content.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Upload body timed out; file was not changed") from None
        if hashlib.sha256(content).hexdigest() != sha256:
            raise HTTPException(422, "SHA-256 mismatch; file was not changed")
        def write():
            lock = store.app_lock(name)
            if not lock.acquire(blocking=False):
                raise HTTPException(409, "App is busy; retry this transfer after maintenance")
            try:
                ready(authorized(name, who, "contributor"))
                return runtime.transfer(name, path, bytes(content))
            finally:
                lock.release()
        task = asyncio.create_task(asyncio.to_thread(write))
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(task)
                break
            except asyncio.CancelledError:
                cancelled = True
                if task.cancelled():
                    raise
        if cancelled:
            raise asyncio.CancelledError
        return result


class FileWrite(BaseModel):
    path: str = Field(max_length=2000)
    content: str = Field(max_length=65536)


@app.get("/api/apps/{name}/file")
def read_file(name: str, path: str, who=Depends(identity)):
    with store.app_lock(name):
        record = authorized(name, who, "contributor")
        ready(record)
        return {"content": runtime.file(name, path)}


@app.put("/api/apps/{name}/file")
def write_file(name: str, body: FileWrite, who=Depends(identity)):
    with store.app_lock(name):
        record = authorized(name, who, "contributor")
        ready(record)
        runtime.file(name, body.path, body.content)
        return {"written": body.path}


@app.post("/api/apps/{name}/lifecycle/{action}")
def lifecycle(name: str, action: str, who=Depends(identity)):
    if action not in {"start", "stop", "restart", "recreate"}:
        raise HTTPException(422, "Choose start, stop, restart or recreate")
    with store.app_lock(name):
        record = authorized(name, who, "owner")
        if action == "recreate":
            if "db_password" in record:
                raise HTTPException(409, "Export the legacy managed database into a new sandbox before recreation")
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


@app.get("/api/apps/{name}/backups")
def list_backups(name: str, who=Depends(identity)):
    with store.app_lock(name):
        record = authorized(name, who, "owner")
        return {
            "backups": backups.list(name),
            "next_backup_at": record.get("next_backup_at"),
            "error": record.get("backup_error"),
        }


class SnapshotRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=128)


def once(name, who, action, key, payload, perform):
    operation_id = digest(json.dumps([name, who, action, key]))
    signature = digest(json.dumps(payload, sort_keys=True))
    previous = store.get(operation_id, "operations")
    if previous:
        if previous["request_hash"] != signature:
            raise HTTPException(409, "Idempotency key already used for different parameters")
        if previous["status"] == "rejected":
            raise HTTPException(previous["error_status"], previous["error_detail"])
        if previous["status"] != "finished":
            raise HTTPException(409, "Operation outcome is unknown; inspect snapshots and app before a new request")
        return previous["result"]
    operation = {"id": operation_id, "request_hash": signature, "status": "started"}
    store.put(operation, "operations")
    try:
        result = perform()
    except (HTTPException, BackupRejected) as exc:
        status = exc.status_code if isinstance(exc, HTTPException) else 422
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        operation.update(status="rejected", error_status=status, error_detail=detail)
        store.put(operation, "operations")
        raise HTTPException(status, detail) from None
    operation.update(status="finished", result=result)
    store.put(operation, "operations")
    return result


@app.post("/api/apps/{name}/backups", status_code=201)
def backup(name: str, body: SnapshotRequest, who=Depends(identity)):
    with store.app_lock(name):
        record = authorized(name, who, "owner")
        return once(name, who, "backup", body.idempotency_key, {}, lambda: backups.create(record))


class Restore(SnapshotRequest):
    confirm_replace_data: bool = False


@app.post("/api/apps/{name}/backups/{backup_id}/restore")
def restore(name: str, backup_id: str, body: Restore, who=Depends(identity)):
    if not body.confirm_replace_data:
        raise HTTPException(
            422,
            "Restore replaces the current workspace, including app-managed data; confirm_replace_data is required",
        )
    if not len(backup_id) == 32 or any(c not in "0123456789abcdef" for c in backup_id):
        raise HTTPException(404, "Backup not found")
    with store.app_lock(name):
        record = authorized(name, who, "owner")
        return once(name, who, "restore", body.idempotency_key, {"backup_id": backup_id},
                    lambda: restore_workspace(name, backup_id, record, who))


def restore_workspace(name, backup_id, record, who):
    # Select a manager-owned directory rather than constructing a filesystem
    # path from request input. Never follow a substituted backup symlink.
    folder = next(
        (candidate for candidate in (state / "backups").iterdir()
         if candidate.name == backup_id and candidate.is_dir() and not candidate.is_symlink()),
        None,
    ) if (state / "backups").is_dir() else None
    if folder is None or not (folder / "manifest.json").is_file() or (folder / "manifest.json").is_symlink():
        raise HTTPException(404, "Backup not found")
    try:
        manifest = json.loads((folder / "manifest.json").read_text())
        if not isinstance(manifest, dict) or not isinstance(manifest.get("app"), str):
            raise ValueError("Invalid snapshot manifest")
    except (OSError, ValueError):
        raise HTTPException(422, "Snapshot manifest is invalid; no workspace data was changed") from None
    if manifest["app"] != name:
        raise HTTPException(404, "Backup not found")
    if "db_password" in record or manifest.get("format") != "workspace-v1":
        raise HTTPException(409, "Legacy database backups require explicit migration; no data was replaced")
    record["status"] = "maintenance"
    store.put(record)
    runtime.container(name).stop(timeout=10)
    try:
        runtime.archive(record["name"], folder.name, restore=True)
        runtime.container(name).start()
        record["status"] = "running"
    except Exception:
        # Keep the app stopped when restore is incomplete.
        record["status"] = "error"
        raise
    finally:
        store.put(record)
    return public_record(record, who)
