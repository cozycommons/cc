"""Validation shared by hosted and stdio transports."""

import base64
import binascii
import hashlib
from urllib.parse import urlencode

TRANSFER_LIMIT = 16 * 1024 * 1024


def transfer_request(path, direction, content_base64, sha256):
    if direction not in {'upload', 'download'}:
        raise ValueError('Choose upload or download')
    if direction == 'download':
        if content_base64 is not None or sha256 is not None:
            raise ValueError('Download takes only app and path')
        return 'GET', '?' + urlencode({'path': path}), None
    if content_base64 is None or sha256 is None:
        raise ValueError('Upload requires content_base64 and its SHA-256')
    if len(content_base64) > ((TRANSFER_LIMIT + 2) // 3) * 4:
        raise ValueError('Transfer exceeds 16 MiB; split using shell')
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('Invalid base64 content') from None
    if len(content) > TRANSFER_LIMIT or hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError('Transfer too large or SHA-256 mismatch')
    return 'PUT', '?' + urlencode({'path': path, 'sha256': sha256}), content


def transfer_response(response):
    data = response.content
    expected = response.headers.get('X-Content-SHA256')
    actual = hashlib.sha256(data).hexdigest()
    if len(data) > TRANSFER_LIMIT or actual != expected:
        raise ValueError('Download size or checksum invalid')
    return {'content_base64': base64.b64encode(data).decode(), 'size_bytes': len(data), 'sha256': actual}


def snapshot_request(action, idempotency_key, backup_id, confirm_replace_data):
    if action == 'list':
        if idempotency_key or backup_id or confirm_replace_data:
            raise ValueError('List takes only app and action')
        return 'GET', '/backups', None
    if action not in {'create', 'restore'}:
        raise ValueError('Choose list, create or restore')
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValueError('Create/restore requires an idempotency key of 1–128 characters')
    data = {'idempotency_key': idempotency_key}
    if action == 'create':
        if backup_id or confirm_replace_data:
            raise ValueError('Create does not take restore parameters')
        return 'POST', '/backups', data
    if not backup_id or len(backup_id) != 32 or any(c not in '0123456789abcdef' for c in backup_id):
        raise ValueError('Choose an exact backup ID from list')
    if not confirm_replace_data:
        raise ValueError('Restore requires explicit user confirmation to replace current workspace data')
    data['confirm_replace_data'] = True
    return 'POST', '/backups/' + backup_id + '/restore', data


def validate_exec(command, job_id, cancel, after, wait_ms):
    if (command is None) == (job_id is None):
        raise ValueError('Provide either command to start or job_id to reconnect')
    if cancel and not job_id:
        raise ValueError('Cancel requires an existing job_id')
    if after < 0 or not 0 <= wait_ms <= 10000:
        raise ValueError('after must be nonnegative; wait_ms must be 0–10000')
