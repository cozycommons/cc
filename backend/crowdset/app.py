from contextlib import asynccontextmanager
from datetime import datetime, timezone
import asyncio
import hmac
import json
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
import httpx
from fastapi.staticfiles import StaticFiles

from .config import env
from .hosting import COOKIE, HostedAccess
from .blobs import BlobError
from pydantic import BaseModel, Field, field_validator, model_validator

from .store import MAX_BYTES, Store


class Performance(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    artist: str | None = Field(default=None, min_length=1, max_length=120)
    venue: str | None = Field(default=None, min_length=1, max_length=160)
    starts_at: str | None = Field(default=None, max_length=40)
    ends_at: str | None = Field(default=None, max_length=40)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator('name', 'artist', 'venue', 'timezone')
    @classmethod
    def nonblank(cls, value):
        if value is None:
            return value
        if not value.strip():
            raise ValueError('Enter a nonblank value')
        return value.strip()

    @model_validator(mode='after')
    def event_range(self):
        values = [self.artist, self.venue, self.starts_at, self.ends_at, self.timezone]
        if all(value is None for value in values):
            return self
        if any(value is None for value in values):
            raise ValueError('Provide artist, venue, start, end and timezone together')
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Use a valid IANA timezone') from exc
        instants = []
        try:
            for value in (self.starts_at, self.ends_at):
                if 'T' not in value:
                    raise ValueError('Use an ISO datetime with date and time')
                instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if instant.tzinfo is None:
                    candidates = {instant.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc) for fold in (0, 1)
                                  if instant.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == instant}
                    if len(candidates) != 1:
                        raise ValueError('This local time is missing or ambiguous because of daylight saving time; choose another time or supply an explicit UTC offset')
                    instant = candidates.pop()
                instants.append(instant.astimezone(timezone.utc))
        except OverflowError as exc:
            raise ValueError('Event datetime is out of range') from exc
        if instants[1] <= instants[0]:
            raise ValueError('End must be after start; include the next date for a performance crossing midnight')
        self.starts_at, self.ends_at = (instant.isoformat() for instant in instants)
        return self


class Selection(BaseModel):
    included: bool


class Soundtrack(BaseModel):
    clip_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


class YouTubeImport(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class Upload(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    size: int = Field(gt=0)
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    batch_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{32}$')


def visible(data, owner, hosted, is_admin=False):
    return not hosted or bool(data.get('owner') and (is_admin or data['owner'] == owner or data.get('visibility') == 'shared'))


def present(data, owner, uploaders=None, is_admin=False):
    if not is_admin:
        data.pop('processing_events', None)
    data.pop('deleted_clips', None)
    data.pop('batch', None)
    data.pop('completed_batch', None)
    data.pop('recovery_attempts', None)
    if data.get('youtube_import'):
        data['youtube_import'].pop('owner', None)
        data['youtube_import'].pop('session_id', None)
    data['can_manage'] = data.get('owner') == owner
    data['can_delete'] = is_admin
    for clip in data['clips']:
        clip['uploader_name'] = (uploaders or {}).get(clip.get('uploader', data.get('owner'))) or clip.get('uploader_name')
        clip['can_edit'] = data['can_manage'] or clip.get('uploader', data.get('owner')) == owner
        clip['can_delete'] = is_admin or (owner is not None and clip.get('uploader') == owner)
        clip.setdefault('kind', 'video' if Path(clip['name']).suffix.lower() in ('.mp4', '.mov', '.webm') else 'audio')
    return data


def create_app(root=None):
    hosted = HostedAccess()
    root = root or hosted.root
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(root) if root else Store()
        try:
            yield
        finally:
            await hosted.close()
            await asyncio.to_thread(app.state.store.close)

    app = FastAPI(title='Crowdset', lifespan=lifespan, docs_url=None, redoc_url=None)
    if not hosted.origin:
        app.add_middleware(CORSMiddleware, allow_origin_regex=r'http://(localhost|127\.0\.0\.1)(:\d+)?',
                           allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'], allow_headers=['Content-Type'])

    @app.middleware('http')
    async def access(request, call_next):
        old_path = request.scope['path']
        legacy = old_path == '/crowd-set' or old_path.startswith('/crowd-set/')
        if legacy:
            request.scope['path'] = '/crowdset' + old_path[len('/crowd-set'):]
            request.scope['raw_path'] = request.scope['path'].encode()
        host = request.url.hostname
        origin = request.headers.get('origin')
        peer = request.client.host if request.client else None
        request.state.owner = None
        request.state.is_admin = not hosted.origin
        token = None
        if hosted.origin:
            if request.url.path == '/crowdset/health' and host in ('localhost', '127.0.0.1') and peer in ('127.0.0.1', '::1', 'testclient'):
                return JSONResponse({'status': 'ok'})
            if request.headers.get('host') != urlsplit(hosted.origin).netloc:
                return JSONResponse({'detail': 'Invalid host.'}, status_code=403)
            if request.url.path.startswith('/crowdset/worker/'):
                expected = env('CROWDSET_WORKER_TOKEN', '')
                supplied = request.headers.get('authorization', '').removeprefix('Bearer ')
                if not expected or not hmac.compare_digest(expected, supplied) or not request.app.state.store.remote:
                    return JSONResponse({'detail': 'Invalid worker credential.'}, status_code=403)
                response = await call_next(request)
                response.headers['Cache-Control'] = 'no-store'
                return response
            if (origin and origin != hosted.origin) or (request.method not in ('GET', 'HEAD') and origin != hosted.origin):
                return JSONResponse({'detail': 'Use the Crowdset website.'}, status_code=403)
            if request.url.path == '/crowdset/sets' or request.url.path.startswith('/crowdset/sets/'):
                bearer = request.headers.get('authorization', '')
                token = bearer[7:] if bearer.startswith('Bearer ') else None
                if request.method in ('GET', 'HEAD') and not bearer:
                    token = request.cookies.get(COOKIE) or (request.cookies.get('__Secure-crowd-set') if legacy else None)
                try:
                    request.state.owner, uploader_name, request.state.is_admin = await hosted.user(token)
                    await asyncio.to_thread(request.app.state.store.remember_uploader, request.state.owner, uploader_name)
                    parts = request.url.path.strip('/').split('/')
                    if len(parts) >= 3:
                        data = await asyncio.to_thread(request.app.state.store.get, parts[2])
                        if not visible(data, request.state.owner, True, request.state.is_admin):
                            raise HTTPException(404, 'Performance not found')
                        if request.method == 'DELETE' and len(parts) == 3 and not request.state.is_admin:
                            raise HTTPException(403, 'Only admins can delete sets.')
                        if request.method in ('PATCH', 'DELETE') and len(parts) >= 5 and parts[3] == 'clips':
                            clip = next((c for c in data['clips'] if c['id'] == parts[4]), None)
                            if clip and request.method == 'DELETE':
                                if not request.state.is_admin and clip.get('uploader') != request.state.owner:
                                    raise HTTPException(403, 'Only the uploader or an admin can remove this recording.')
                            elif clip and request.state.owner not in (data['owner'], clip.get('uploader', data['owner'])):
                                raise HTTPException(403, 'Only the uploader or set owner can change this recording.')
                except HTTPException as exc:
                    return JSONResponse({'detail': exc.detail}, status_code=exc.status_code)
        else:
            if host not in ('localhost', '127.0.0.1', '::1') or peer not in ('127.0.0.1', '::1', 'testclient'):
                return JSONResponse({'detail': 'Crowdset is available on loopback only.'}, status_code=403)
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1'):
                    return JSONResponse({'detail': 'Only a local frontend may use Crowdset.'}, status_code=403)
        if legacy and old_path.rstrip('/') == '/crowd-set' and request.method in ('GET', 'HEAD'):
            response = RedirectResponse('/crowdset' + ('?' + request.url.query if request.url.query else ''), status_code=308)
        else:
            response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        if hosted.origin and token and request.headers.get('authorization', '').startswith('Bearer '):
            response.set_cookie(COOKIE, token, secure=True, httponly=True, samesite='strict', path='/crowdset', max_age=3600)
            if legacy:
                response.set_cookie('__Secure-crowd-set', token, secure=True, httponly=True, samesite='strict', path='/crowd-set', max_age=3600)
        return response

    @app.exception_handler(BlobError)
    async def storage_error(request, error):
        return JSONResponse({'detail': str(error)}, status_code=503)

    @app.post('/crowdset/worker/{operation}')
    async def worker_control(operation: str, request: Request):
        expected = env('CROWDSET_WORKER_TOKEN', '')
        if not expected or not hmac.compare_digest(expected, request.headers.get('authorization', '').removeprefix('Bearer ')):
            raise HTTPException(403, 'Invalid worker credential.')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 2 * 1024 ** 2:
                raise HTTPException(413, 'Worker metadata exceeds its bound.')
        try:
            body = json.loads(raw or b'{}')
            def execute():
                store = request.app.state.store
                remote = store.remote
                if not remote:
                    raise HTTPException(503, 'Remote processing is disabled.')
                with store.lock:
                    if operation == 'claim':
                        return remote.claim()
                    job = remote.owned(body['job'], body['claim'], allow_complete=operation == 'publish')
                    if operation == 'heartbeat':
                        return remote.heartbeat(job, body.get('stage', 'Processing on the PC…'), body.get('processing'))
                    if operation == 'read':
                        return remote.read(job, body['key'])
                    if operation == 'reserve':
                        return remote.reserve(job, body['name'], body['bytes'], body['sha256'], body.get('mime', 'application/octet-stream'))
                    if operation == 'part':
                        return store.blobs.direct_part(job['artifacts'][body['name']]['key'], body['part'])
                    if operation == 'complete':
                        return remote.complete(job, body['name'])
                    if operation == 'publish':
                        return remote.publish(job, body['result'])
                    if operation == 'fail':
                        return remote.fail(job, body['error'])
                    raise HTTPException(404, 'Unknown worker operation.')
            return await asyncio.to_thread(execute)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(422, 'Invalid worker metadata.') from exc

    @app.post('/crowdset/sets/{set_id}/uploads/{upload_id}/parts/{number}')
    def direct_part(set_id: str, upload_id: str, number: int, request: Request, ack: bool = False):
        store = request.app.state.store
        with store.lock:
            session = store.session(set_id, upload_id, request.state.owner)
            if not store.remote or not session.get('direct') or session['state'] != 'uploading':
                raise HTTPException(409, 'This recording is not accepting direct parts.')
            store.remote.touch_batch(session)
            if ack:
                return store.remote.browser_ack(session, number)
            return store.blobs.direct_part(session['object_key'], number)

    @app.get('/crowdset/health')
    def health():
        return {'status': 'ok'}

    @app.delete('/crowdset/session', status_code=204)
    def logout():
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path='/crowdset', secure=True, httponly=True, samesite='strict')
        response.delete_cookie('__Secure-crowd-set', path='/crowd-set', secure=True, httponly=True, samesite='strict')
        return response

    @app.get('/crowdset/sets')
    def list_sets(request: Request, limits: bool = False):
        if limits:
            return request.app.state.store.limits.public()
        return [present(item, request.state.owner, request.app.state.store.uploaders, request.state.is_admin) for item in request.app.state.store.list()
                if visible(item, request.state.owner, hosted.origin, request.state.is_admin)]

    @app.post('/crowdset/sets', status_code=201)
    def create_set(body: Performance, request: Request):
        event = body.model_dump(exclude={'name'}, exclude_none=True)
        return present(request.app.state.store.create(body.name, owner=request.state.owner, event=event), request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.get('/crowdset/sets/{set_id}')
    def get_set(set_id: str, request: Request):
        return present(request.app.state.store.get(set_id), request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.post('/crowdset/sets/{set_id}/youtube', status_code=202)
    def import_youtube(set_id: str, body: YouTubeImport, request: Request):
        return present(request.app.state.store.import_youtube(set_id, body.url, request.state.owner), request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.delete('/crowdset/sets/{set_id}', status_code=204)
    def delete_set(set_id: str, request: Request):
        request.app.state.store.delete(set_id)

    @app.post('/crowdset/sets/{set_id}/batches', status_code=201)
    def begin_batch(set_id: str, request: Request):
        return request.app.state.store.begin_batch(set_id, request.state.owner)

    @app.post('/crowdset/sets/{set_id}/batches/{batch_id}/finish')
    def finish_batch(set_id: str, batch_id: str, request: Request):
        return present(request.app.state.store.finish_batch(set_id, batch_id, request.state.owner), request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.post('/crowdset/sets/{set_id}/uploads', status_code=201)
    def prepare_upload(set_id: str, body: Upload, request: Request):
        store = request.app.state.store
        value = store.prepare_session(set_id, body.name, body.size, body.fingerprint, request.state.owner, body.batch_id)
        if store.remote:
            with store.lock:
                value = store.remote.browser_prepare(store.session(set_id, value['id'], request.state.owner))
        return value

    @app.get('/crowdset/sets/{set_id}/uploads/{upload_id}')
    def upload_status(set_id: str, upload_id: str, request: Request):
        store = request.app.state.store
        session = store.session(set_id, upload_id, request.state.owner)
        return {**store.public_session(session), 'direct': bool(session.get('direct'))}

    @app.delete('/crowdset/sets/{set_id}/uploads/{upload_id}', status_code=204)
    def cancel_upload(set_id: str, upload_id: str, request: Request):
        request.app.state.store.cancel_session(set_id, upload_id, request.state.owner)

    @app.patch('/crowdset/sets/{set_id}/uploads/{upload_id}')
    async def upload_chunk(set_id: str, upload_id: str, request: Request, offset: int = Query(ge=0), checksum: str = Query(pattern=r'^[a-f0-9]{64}$')):
        store = request.app.state.store
        if store.remote:
            raise HTTPException(409, 'Reload Crowdset to upload directly to cloud storage.')
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

    @app.post('/crowdset/sets/{set_id}/uploads/{upload_id}/finish')
    def complete_upload(set_id: str, upload_id: str, request: Request):
        store = request.app.state.store
        if store.remote:
            with store.lock:
                return present(store.remote.browser_finish(store.session(set_id, upload_id, request.state.owner)), request.state.owner, store.uploaders, request.state.is_admin)
        return present(request.app.state.store.complete_session(set_id, upload_id, request.state.owner), request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.put('/crowdset/sets/{set_id}/clips', status_code=201)
    async def upload(set_id: str, request: Request, name: str = Query(min_length=1, max_length=180), role: Literal['reference', 'crowd', 'recording'] = 'recording', batch_id: str | None = Query(default=None, max_length=32)):
        if request.app.state.store.remote:
            raise HTTPException(409, 'Reload Crowdset to upload directly to cloud storage.')
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
        return present(data, request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.patch('/crowdset/sets/{set_id}/clips/{clip_id}')
    def select_clip(set_id: str, clip_id: str, body: Selection, request: Request):
        return present(request.app.state.store.edit_clip(set_id, clip_id, included=body.included), request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.delete('/crowdset/sets/{set_id}/clips/{clip_id}')
    def remove_clip(set_id: str, clip_id: str, request: Request):
        return present(request.app.state.store.edit_clip(set_id, clip_id, delete=True), request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.put('/crowdset/sets/{set_id}/soundtrack')
    def soundtrack(set_id: str, body: Soundtrack, request: Request):
        return present(request.app.state.store.select_soundtrack(set_id, body.clip_id, request.state.owner), request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.get('/crowdset/sets/{set_id}/overlays/{asset_id}')
    def overlay(set_id: str, asset_id: str, request: Request, v: str):
        store = request.app.state.store
        data = store.get(set_id)
        if v != data.get('mix_revision'):
            data = data.get('previous_revision', {})
        if v != data.get('mix_revision'):
            raise HTTPException(404, 'This cut revision is no longer available. Reload the set.')
        asset = (data.get('composition') or {}).get('assets', {}).get(asset_id)
        if not asset:
            raise HTTPException(404, 'Video insert not found.')
        if asset.get('object'):
            return stored_media(store, asset['object'], request, 'friend.mp4', False, 'video/mp4')
        return FileResponse(store.directory(set_id) / asset['file'], media_type='video/mp4')

    @app.get('/crowdset/sets/{set_id}/previews/{sheet}')
    def scrub_preview(set_id: str, sheet: str, request: Request, v: str):
        store = request.app.state.store
        data = store.get(set_id)
        if v != data.get('mix_revision'):
            data = data.get('previous_revision', {})
        if v != data.get('mix_revision') or not any(
                sheet in preview['sheets'] for preview in (data.get('scrub_previews') or {}).values()):
            raise HTTPException(404, 'Preview unavailable')
        if data.get('preview_objects', {}).get(sheet):
            return RedirectResponse(store.blobs.signed('GET', data['preview_objects'][sheet]))
        path = store.directory(set_id) / sheet
        if not path.is_file():
            raise HTTPException(404, 'Preview unavailable')
        return FileResponse(path, media_type='image/jpeg')

    @app.post('/crowdset/sets/{set_id}/process', status_code=202)
    def process(set_id: str, request: Request):
        return present(request.app.state.store.start(set_id), request.state.owner, request.app.state.store.uploaders, request.state.is_admin)

    @app.get('/crowdset/sets/{set_id}/clips/{clip_id}/thumbnail')
    def thumbnail(set_id: str, clip_id: str, request: Request):
        store = request.app.state.store
        clip = next((c for c in store.get(set_id)['clips'] if c['id'] == clip_id), None)
        if not clip:
            raise HTTPException(404, 'Recording not found')
        if clip.get('thumbnail_object'):
            return RedirectResponse(store.blobs.signed('GET', clip['thumbnail_object']))
        path = store.directory(set_id) / f'{clip["id"]}.jpg'
        if not path.exists():
            raise HTTPException(404, 'Preview unavailable')
        return FileResponse(path, media_type='image/jpeg')

    @app.get('/crowdset/sets/{set_id}/clips/{clip_id}/media')
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

    def compiled(set_id, request, download, revision, video=False):
        store = request.app.state.store
        data = store.get(set_id)
        if revision is not None and revision != (data.get('mix_revision') or 'legacy'):
            data = data.get('previous_revision', {})
            if revision != (data.get('mix_revision') or 'legacy'):
                raise HTTPException(404, 'This cut revision is no longer available. Reload the set.')
        kind, suffix, mime = ('video', 'mp4', 'video/mp4') if video else ('mix', 'wav', 'audio/wav')
        if not data.get('video_playable' if video else 'playable'):
            raise HTTPException(404, 'No compiled media is available. Add a recording first.')
        filename = f'crowdset.{suffix}'
        if data.get(f'{kind}_object'):
            return stored_media(store, data[f'{kind}_object'], request, filename, download, mime)
        return FileResponse(store.directory(set_id) / (data.get(f'{kind}_file') or 'reconstruction.wav'), media_type=mime,
                            filename=filename if download else None, headers={'Cache-Control': 'no-store'})

    @app.get('/crowdset/sets/{set_id}/audio')
    def audio(set_id: str, request: Request, download: bool = False, v: str | None = None):
        return compiled(set_id, request, download, v)

    @app.get('/crowdset/sets/{set_id}/video')
    def video(set_id: str, request: Request, download: bool = False, v: str | None = None):
        return compiled(set_id, request, download, v, video=True)

    static = env('CROWDSET_STATIC_DIR')
    if static:
        directory = Path(static)
        app.mount('/crowdset/assets', StaticFiles(directory=directory / 'assets'), name='assets')

        @app.get('/crowdset')
        @app.get('/crowdset/')
        @app.get('/crowdset/{slug}')
        def index(slug: str | None = None):
            if slug == 'session':
                raise HTTPException(404, 'Not found')
            return FileResponse(directory / 'index.html')

    return app


def stored_media(store, key, request, filename, download, media_type):
    if store.remote:
        params = {'response-content-disposition': "attachment; filename*=UTF-8''" + quote(filename, safe='')} if download else None
        return RedirectResponse(store.blobs.signed('GET', key, params=params, expires=14400))
    if not store.blobs:
        raise HTTPException(503, 'Private media storage is not configured.')
    client = store.blobs.client()
    try:
        headers = {'Accept-Encoding': 'identity'}
        if 'range' in request.headers:
            headers['Range'] = request.headers['range']
        response = client.send(client.build_request('GET', store.blobs.object_url(key), headers=headers), stream=True)
    except (httpx.HTTPError, BlobError) as exc:
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
