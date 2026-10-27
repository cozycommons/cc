"""Private per-plan scans. Every metadata and byte request checks current membership."""
import logging
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

from .routes import current_user, database, document_access, get_document, one, require_verified, rows, verified_email
from .scan_validation import MAX_SCAN_BYTES, validate_scan

router = APIRouter(tags=['Floor Planner scans'])
BUCKET = 'floor-plan-scans'
logger = logging.getLogger(__name__)


def authorize(request, document_id, user):
    require_verified(user)
    client = database(request)
    document = get_document(client, document_id)
    if document_access(client, document, user) not in {'owner', 'editor'}:
        raise HTTPException(404, 'Scan not found.')
    return client, document


def metadata(scan):
    return {key: scan[key] for key in ('id', 'filename', 'byte_size', 'created_at')} if scan else None


def cleanup(client, key):
    try:
        active = rows(client.table('floor_plan_scans').select('id').eq('object_key', key).limit(1))
        if not active:
            client.storage.from_(BUCKET).remove([key])
        client.table('floor_plan_scan_cleanup').delete().eq('object_key', key).execute()
    except Exception:
        logger.warning('Floor plan scan cleanup deferred.')


def cleanup_pending(client):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    for item in rows(client.table('floor_plan_scan_cleanup').select('object_key').lt('created_at', cutoff).limit(10)):
        cleanup(client, item['object_key'])


def save_scan(request, document_id, user, content, filename, expected_id):
    client, document = authorize(request, document_id, user)
    cleanup_pending(client)
    details = validate_scan(content, filename)
    scan_id = str(uuid4())
    key = f'{document["id"]}/{scan_id}.usdz'
    client.table('floor_plan_scan_cleanup').insert({'object_key': key}).execute()
    rpc_started = False
    try:
        client.storage.from_(BUCKET).upload(key, content, file_options={
            'content-type': 'model/vnd.usdz+zip', 'cache-control': '0', 'upsert': 'false',
        })
        rpc_started = True
        result = client.rpc('floor_planner_set_scan', {
            'p_document_id': document['id'], 'p_user_id': str(user.id), 'p_email': verified_email(user),
            'p_expected_id': expected_id,
            'p_scan': {'id': scan_id, 'filename': filename, 'object_key': key, **details},
        }).execute().data
        if result['status'] != 'ok':
            raise HTTPException(409 if result['status'] == 'conflict' else 404,
                                'The attached scan changed. Reload and try again.' if result['status'] == 'conflict' else 'Scan access changed.')
    except HTTPException:
        cleanup(client, key)
        raise
    except Exception as error:
        if not rpc_started:
            cleanup(client, key)
        raise HTTPException(503, 'Could not save the scan. Check private Storage availability and its 50 MiB limit, then retry.') from error
    if result.get('old_key'):
        cleanup(client, result['old_key'])
    return metadata(result['scan'])


@router.get('/plans/{document_id}/scan')
def get_scan(document_id: str, request: Request, user=Depends(current_user)):
    client, document = authorize(request, document_id, user)
    cleanup_pending(client)
    scan = one(client.table('floor_plan_scans').select('*').eq('document_id', document['id']))
    return {'scan': metadata(scan)}


@router.put('/plans/{document_id}/scan')
async def upload_scan(document_id: str, request: Request, filename: str = 'scan.usdz', expected_id: str | None = None, user=Depends(current_user)):
    await run_in_threadpool(authorize, request, document_id, user)
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_SCAN_BYTES:
            raise HTTPException(413, 'USDZ scans must be at most 50 MiB.')
        content.extend(chunk)
    scan = await run_in_threadpool(save_scan, request, document_id, user, bytes(content), filename, expected_id)
    return {'scan': scan}


@router.get('/plans/{document_id}/scan/content')
def scan_content(document_id: str, request: Request, user=Depends(current_user)):
    client, document = authorize(request, document_id, user)
    scan = one(client.table('floor_plan_scans').select('*').eq('document_id', document['id']))
    if not scan:
        raise HTTPException(404, 'Scan not found.')
    try:
        content = client.storage.from_(BUCKET).download(scan['object_key'])
    except Exception as error:
        raise HTTPException(503, 'The scan is unavailable. Retry shortly.') from error
    if len(content) != scan['byte_size'] or hashlib.sha256(content).hexdigest() != scan['sha256']:
        raise HTTPException(503, 'The stored scan failed its integrity check.')
    authorize(request, document_id, user)
    return Response(content, media_type='model/vnd.usdz+zip', headers={
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Disposition': 'attachment; filename="scan.usdz"',
    })


@router.delete('/plans/{document_id}/scan', status_code=204)
def remove_scan(document_id: str, request: Request, expected_id: str, user=Depends(current_user)):
    client, document = authorize(request, document_id, user)
    result = client.rpc('floor_planner_set_scan', {
        'p_document_id': document['id'], 'p_user_id': str(user.id), 'p_email': verified_email(user),
        'p_expected_id': expected_id, 'p_scan': None,
    }).execute().data
    if result['status'] != 'ok':
        raise HTTPException(409 if result['status'] == 'conflict' else 404, 'Scan changed or access was revoked. Reload and try again.')
    if result.get('old_key'):
        cleanup(client, result['old_key'])
    return Response(status_code=204)
