"""Small standalone control plane. Producers use project-scoped bearer tokens."""
import hmac
import json
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .jobs import Registry, Resources
from .queue import Conflict, Queue


class Submit(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: str
    payload: dict
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)


class Claim(BaseModel):
    worker: str = Field(min_length=1, max_length=100)
    types: list[str] = Field(max_length=1000)
    capacity: Resources


class Update(BaseModel):
    job: str = Field(pattern=r'^[a-f0-9]{32}$')
    claim: str = Field(pattern=r'^[a-f0-9]{32}$')
    progress: dict = Field(default_factory=dict)
    result: dict = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=1000)


def create_app(queue, project_tokens, worker_token):
    if not worker_token or not project_tokens or any(not token for token in project_tokens.values()):
        raise ValueError('Configure worker and project tokens')
    if len(set([worker_token, *project_tokens.values()])) != len(project_tokens) + 1:
        raise ValueError('Worker and project tokens must be distinct')
    app = FastAPI(title='Cozy Commons compute', docs_url=None, redoc_url=None)

    @app.middleware('http')
    async def bounded_body(request: Request, call_next):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 300 * 1024:
                return JSONResponse({'detail': 'Request too large'}, status_code=413)
        request._body = bytes(body)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=409 if isinstance(exc, Conflict) else 422)

    def producer(authorization: str = Header(default='')):
        for project, token in project_tokens.items():
            if hmac.compare_digest(authorization, 'Bearer ' + token):
                return project
        raise HTTPException(401, 'Invalid project token')

    def worker(authorization: str = Header(default='')):
        if not hmac.compare_digest(authorization, 'Bearer ' + worker_token):
            raise HTTPException(401, 'Invalid worker token')

    @app.get('/compute/health')
    def health():
        with queue.transaction() as db:
            db.execute('SELECT 1')
        return {'ok': True}

    @app.post('/compute/jobs')
    def submit(body: Submit, project=Depends(producer)):
        try:
            return queue.submit(project, body.type, body.payload, body.idempotency_key)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.get('/compute/jobs/{identifier}')
    def status(identifier: str, project=Depends(producer)):
        try:
            return queue.status(project, identifier)
        except KeyError:
            raise HTTPException(404, 'Job not found') from None

    @app.post('/compute/worker/claim', dependencies=[Depends(worker)])
    def claim(body: Claim):
        return queue.claim(body.worker, body.types, body.capacity)

    @app.post('/compute/worker/heartbeat', dependencies=[Depends(worker)])
    def heartbeat(body: Update):
        return queue.heartbeat(body.job, body.claim, body.progress)

    @app.post('/compute/worker/finish', dependencies=[Depends(worker)])
    def finish(body: Update):
        return queue.finish(body.job, body.claim, body.result, body.error)

    return app


def configured_app():
    registry = Registry.load(os.environ['CC_JOB_MODULES'].split(','))
    queue = Queue(os.environ.get('CC_COMPUTE_DB', '/data/jobs.sqlite3'), registry)
    return create_app(queue, json.loads(os.environ['CC_COMPUTE_PROJECT_TOKENS']), os.environ['CC_COMPUTE_WORKER_TOKEN'])
