from contextlib import asynccontextmanager
import asyncio
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from urllib.parse import quote

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
import httpx
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


class Upload(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    size: int = Field(gt=0)
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    batch_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


def visible(data, owner, hosted):
    return not hosted or bool(data.get('owner') and (data['owner'] == owner or data.get('visibility') == 'shared'))


def present(data, owner):
    data.pop('batch', None)
    data.pop('completed_batch', None)
    data.pop('recovery_attempts', None)
    data['can_manage'] = data.get('owner') == owner
    for clip in data['clips']:
        clip['can_edit'] = data['can_manage'] or clip.get('uploader', data.get('owner')) == owner
        clip.setdefault('kind', 'video' if Path(clip['name']).suffix.lower() in ('.mp4', '.mov', '.webm') else 'audio')
    return data


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
                        if not visible(data, request.state.owner, True):
                            raise HTTPException(404, 'Performance not found')
                        if request.method == 'DELETE' and len(parts) == 3 and data['owner'] != request.state.owner:
                            raise HTTPException(403, 'Only the set owner can delete this set.')
                        if request.method in ('PATCH', 'DELETE') and len(parts) >= 5 and parts[3] == 'clips':
                            clip = next((c for c in data['clips'] if c['id'] == parts[4]), None)
                            if clip and request.state.owner not in (data['owner'], clip.get('uploader', data['owner'])):
                                raise HTTPException(403, 'Only the uploader or set owner can change this recording.')
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
    def list_sets(request: Request, limits: bool = False):
        if limits:
            return request.app.state.store.limits.public()
        return [present(item, request.state.owner) for item in request.app.state.store.list()
                if visible(item, request.state.owner, hosted.origin)]

    @app.post('/crowd-set/sets', status_code=201)
    def create_set(body: Performance, request: Request):
        return present(request.app.state.store.create(body.name, owner=request.state.owner), request.state.owner)

    @app.get('/crowd-set/sets/{set_id}')
    def get_set(set_id: str, request: Request):
        return present(request.app.state.store.get(set_id), request.state.owner)

    @app.delete('/crowd-set/sets/{set_id}', status_code=204)
    def delete_set(set_id: str, request: Request):
        request.app.state.store.delete(set_id)

    @app.post('/crowd-set/sets/{set_id}/batches', status_code=201)
    def begin_batch(set_id: str, request: Request):
        return request.app.state.store.begin_batch(set_id, request.state.owner)

    @app.post('/crowd-set/sets/{set_id}/batches/{batch_id}/finish')
    def finish_batch(set_id: str, batch_id: str, request: Request):
        return present(request.app.state.store.finish_batch(set_id, batch_id, request.state.owner), request.state.owner)

    @app.post('/crowd-set/sets/{set_id}/uploads', status_code=201)
    def prepare_upload(set_id: str, body: Upload, request: Request):
        return request.app.state.store.prepare_session(set_id, body.name, body.size, body.fingerprint, request.state.owner, body.batch_id)

    @app.get('/crowd-set/sets/{set_id}/uploads/{upload_id}')
    def upload_status(set_id: str, upload_id: str, request: Request):
        store = request.app.state.store
        return store.public_session(store.session(set_id, upload_id, request.state.owner))

    @app.delete('/crowd-set/sets/{set_id}/uploads/{upload_id}', status_code=204)
    def cancel_upload(set_id: str, upload_id: str, request: Request):
        request.app.state.store.cancel_session(set_id, upload_id, request.state.owner)

    @app.patch('/crowd-set/sets/{set_id}/uploads/{upload_id}')
    async def upload_chunk(set_id: str, upload_id: str, request: Request, offset: int = Query(ge=0), checksum: str = Query(pattern=r'^[a-f0-9]{64}$')):
        store = request.app.state.store
        await asyncio.to_thread(store.begin_chunk, set_id, upload_id, request.state.owner)
        chunk = bytearray()
        try:
            async with asyncio.timeout(120):
                async for part in request.stream():
                    if len(chunk) + len(part) > store.limits.chunk_bytes:
                        raise HTTPException(413, 'Upload chunk is too large.')
                    chunk.extend(part)
            return await asyncio.to_thread(store.append_session, set_id, upload_id, request.state.owner, offset, chunk, checksum)
        except TimeoutError as exc:
            raise HTTPException(408, 'Upload chunk timed out. Resume from the saved offset.') from exc
        finally:
            await asyncio.to_thread(store.end_chunk, set_id, upload_id)

    @app.post('/crowd-set/sets/{set_id}/uploads/{upload_id}/finish')
    def complete_upload(set_id: str, upload_id: str, request: Request):
        return present(request.app.state.store.complete_session(set_id, upload_id, request.state.owner), request.state.owner)

    @app.put('/crowd-set/sets/{set_id}/clips', status_code=201)
    async def upload(set_id: str, request: Request, name: str = Query(min_length=1, max_length=180), role: Literal['reference', 'crowd', 'recording'] = 'recording', batch_id: str | None = Query(default=None, max_length=32)):
        length = request.headers.get('content-length')
        store = request.app.state.store
        maximum = min(MAX_BYTES, store.limits.file_bytes)
        if length and (not length.isdigit() or int(length) > maximum):
            raise HTTPException(413, f'Each upload must be at most {maximum // 1024 ** 2} MiB.')
        clip, path = await asyncio.to_thread(store.begin_upload, set_id, name, role, request.state.owner, batch_id)
        success = False
        try:
            size = 0
            async with await anyio.open_file(path, 'wb') as output:
                async with asyncio.timeout(300):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > maximum:
                            raise HTTPException(413, f'Each upload must be at most {maximum // 1024 ** 2} MiB.')
                        await output.write(chunk)
            if size == 0:
                raise HTTPException(400, 'The uploaded file is empty.')
            clip['bytes'] = size
            success = True
        except TimeoutError:
            raise HTTPException(408, 'Upload exceeded 5 minutes. Retry a smaller file.')
        finally:
            data = store.finish_upload(set_id, clip, path, success)
        return present(data, request.state.owner)

    @app.patch('/crowd-set/sets/{set_id}/clips/{clip_id}')
    def select_clip(set_id: str, clip_id: str, body: Selection, request: Request):
        return present(request.app.state.store.edit_clip(set_id, clip_id, included=body.included), request.state.owner)

    @app.delete('/crowd-set/sets/{set_id}/clips/{clip_id}')
    def remove_clip(set_id: str, clip_id: str, request: Request):
        return present(request.app.state.store.edit_clip(set_id, clip_id, delete=True), request.state.owner)

    @app.post('/crowd-set/sets/{set_id}/process', status_code=202)
    def process(set_id: str, request: Request):
        return present(request.app.state.store.start(set_id), request.state.owner)

    @app.get('/crowd-set/sets/{set_id}/clips/{clip_id}/media')
    def original(set_id: str, clip_id: str, request: Request, download: bool = False):
        store = request.app.state.store
        clip = next((c for c in store.get(set_id)['clips'] if c['id'] == clip_id), None)
        if not clip:
            raise HTTPException(404, 'Recording not found')
        types = {'.mp4': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm', '.wav': 'audio/wav',
                 '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.flac': 'audio/flac', '.ogg': 'audio/ogg'}
        if clip.get('object_key'):
            return stored_media(store, clip['object_key'], request, clip['name'], download, types[Path(clip['name']).suffix.lower()])
        return FileResponse(store.originals.path(set_id, clip), media_type=types[Path(clip['name']).suffix.lower()],
                            filename=clip['name'], content_disposition_type='attachment' if download else 'inline')

    @app.get('/crowd-set/sets/{set_id}/audio')
    def audio(set_id: str, request: Request, download: bool = False):
        store = request.app.state.store
        data = store.get(set_id)
        if not data['playable']:
            raise HTTPException(404, 'No mix is available. Add a recording first.')
        if data.get('mix_object'):
            return stored_media(store, data['mix_object'], request, 'crowd-set.wav', download, 'audio/wav')
        return FileResponse(store.directory(set_id) / data.get('mix_file', 'reconstruction.wav'), media_type='audio/wav',
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


def stored_media(store, key, request, filename, download, media_type):
    if not store.blobs:
        raise HTTPException(503, 'Private media storage is not configured.')
    client = store.blobs.client()
    try:
        headers = {'Accept-Encoding': 'identity'}
        if 'range' in request.headers:
            headers['Range'] = request.headers['range']
        response = client.send(client.build_request('GET', store.blobs.object_url(key), headers=headers), stream=True)
    except httpx.HTTPError as exc:
        client.close()
        raise HTTPException(503, 'Media storage is unavailable. Try again shortly.') from exc
    if response.status_code not in (200, 206, 416):
        response.close()
        client.close()
        raise HTTPException(503, 'Media storage could not serve this recording. Try again shortly.')
    headers = {name: response.headers[name] for name in ('content-length', 'content-range', 'accept-ranges') if name in response.headers}
    headers['Content-Disposition'] = f'{"attachment" if download else "inline"}; filename*=UTF-8\'\'{quote(filename)}'

    def close():
        response.close()
        client.close()

    def chunks():
        try:
            yield from response.iter_bytes(65536)
        finally:
            close()

    return StreamingResponse(chunks(), status_code=response.status_code, media_type=media_type, headers=headers, background=BackgroundTask(close))


app = create_app()
