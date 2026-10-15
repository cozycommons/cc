from contextlib import asynccontextmanager
import asyncio
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .hosting import COOKIE, HostedAccess
from pydantic import BaseModel, Field, field_validator

from .store import MAX_BYTES, Store


class Performance(BaseModel):
    name: str = Field(min_length=1, max_length=120)

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Enter a performance name')
        return value.strip()


class Selection(BaseModel):
    included: bool


def create_app(root=None):
    hosted = HostedAccess()
    root = root or hosted.root
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(root) if root else Store()
        yield
        await asyncio.to_thread(app.state.store.close)

    app = FastAPI(title='Crowd Set', lifespan=lifespan, docs_url=None, redoc_url=None)
    if not hosted.origin:
        app.add_middleware(CORSMiddleware, allow_origin_regex=r'http://(localhost|127\.0\.0\.1)(:\d+)?',
                           allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], allow_headers=['Content-Type'])

    @app.middleware('http')
    async def access(request, call_next):
        host = request.url.hostname
        origin = request.headers.get('origin')
        peer = request.client.host if request.client else None
        request.state.owner = None
        token = None
        if hosted.origin:
            if request.url.path == '/crowd-set/health' and host in ('localhost', '127.0.0.1') and peer in ('127.0.0.1', '::1', 'testclient'):
                return JSONResponse({'status': 'ok'})
            if request.headers.get('host') != urlsplit(hosted.origin).netloc:
                return JSONResponse({'detail': 'Invalid host.'}, status_code=403)
            if (origin and origin != hosted.origin) or (request.method not in ('GET', 'HEAD') and origin != hosted.origin):
                return JSONResponse({'detail': 'Use the Crowd Set website.'}, status_code=403)
            if request.url.path.startswith('/crowd-set/sets'):
                bearer = request.headers.get('authorization', '')
                token = bearer[7:] if bearer.startswith('Bearer ') else None
                if request.method in ('GET', 'HEAD') and not bearer:
                    token = request.cookies.get(COOKIE)
                try:
                    request.state.owner = await hosted.user(token)
                    parts = request.url.path.strip('/').split('/')
                    if len(parts) >= 3:
                        data = await asyncio.to_thread(request.app.state.store.get, parts[2])
                        if data.get('owner') != request.state.owner:
                            raise HTTPException(404, 'Performance not found')
                except HTTPException as exc:
                    return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        else:
            if host not in ('localhost', '127.0.0.1', '::1') or peer not in ('127.0.0.1', '::1', 'testclient'):
                return JSONResponse({'detail': 'Crowd Set is available on loopback only.'}, status_code=403)
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1'):
                    return JSONResponse({'detail': 'Only a local frontend may use Crowd Set.'}, status_code=403)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if hosted.origin and token and request.headers.get('authorization', '').startswith('Bearer '):
            response.set_cookie(COOKIE, token, secure=True, httponly=True, samesite='strict', path='/crowd-set', max_age=3600)
        return response

    @app.get('/crowd-set/health')
    def health():
        return {'status': 'ok'}

    @app.delete('/crowd-set/session', status_code=204)
    def logout():
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path='/crowd-set', secure=True, httponly=True, samesite='strict')
        return response

    @app.get('/crowd-set/sets')
    def list_sets(request: Request):
        return [item for item in request.app.state.store.list() if item.get('owner') == request.state.owner]

    @app.post('/crowd-set/sets', status_code=201)
    def create_set(body: Performance, request: Request):
        return request.app.state.store.create(body.name, owner=request.state.owner)

    @app.get('/crowd-set/sets/{set_id}')
    def get_set(set_id: str, request: Request):
        return request.app.state.store.get(set_id)

    @app.delete('/crowd-set/sets/{set_id}', status_code=204)
    def delete_set(set_id: str, request: Request):
        request.app.state.store.delete(set_id)

    @app.put('/crowd-set/sets/{set_id}/clips', status_code=201)
    async def upload(set_id: str, request: Request, role: Literal['reference', 'crowd'], name: str = Query(min_length=1, max_length=180)):
        length = request.headers.get('content-length')
        if length and (not length.isdigit() or int(length) > MAX_BYTES):
            raise HTTPException(413, 'Each upload must be at most 512 MiB.')
        store = request.app.state.store
        clip, path = await asyncio.to_thread(store.begin_upload, set_id, name, role)
        success = False
        try:
            size = 0
            async with await anyio.open_file(path, 'wb') as output:
                async with asyncio.timeout(300):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise HTTPException(413, 'Each upload must be at most 512 MiB.')
                        await output.write(chunk)
            if size == 0:
                raise HTTPException(400, 'The uploaded file is empty.')
            clip['bytes'] = size
            success = True
        except TimeoutError:
            raise HTTPException(408, 'Upload exceeded 5 minutes. Retry a smaller file.')
        finally:
            data = store.finish_upload(set_id, clip, path, success)
        return data

    @app.patch('/crowd-set/sets/{set_id}/clips/{clip_id}')
    def select_clip(set_id: str, clip_id: str, body: Selection, request: Request):
        return request.app.state.store.edit_clip(set_id, clip_id, included=body.included)

    @app.delete('/crowd-set/sets/{set_id}/clips/{clip_id}')
    def remove_clip(set_id: str, clip_id: str, request: Request):
        return request.app.state.store.edit_clip(set_id, clip_id, delete=True)

    @app.post('/crowd-set/sets/{set_id}/process', status_code=202)
    def process(set_id: str, request: Request):
        return request.app.state.store.start(set_id)

    @app.get('/crowd-set/sets/{set_id}/audio')
    def audio(set_id: str, request: Request, download: bool = False):
        store = request.app.state.store
        data = store.get(set_id)
        if data['status'] != 'ready' or not data['playable']:
            raise HTTPException(404, 'No reconstruction is available. Process matching crowd clips first.')
        return FileResponse(store.directory(set_id) / 'reconstruction.wav', media_type='audio/wav',
                            filename='crowd-set.wav' if download else None, headers={'Cache-Control': 'no-store'})

    static = os.environ.get('CROWD_SET_STATIC_DIR')
    if static:
        directory = Path(static)
        app.mount('/crowd-set/assets', StaticFiles(directory=directory / 'assets'), name='assets')

        @app.get('/crowd-set')
        @app.get('/crowd-set/')
        def index():
            return FileResponse(directory / 'index.html')

    return app


app = create_app()
