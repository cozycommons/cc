"""Validation shared by hosted and stdio transports."""

import base64
import binascii
import hashlib
from urllib.parse import urlencode

TRANSFER_LIMIT = 16 * 1024 * 1024
MCP_TRANSFER_LIMIT = 2 * 1024 * 1024


def transfer_request(path, direction, content_base64, sha256):
    if direction not in {'upload', 'download'}:
        raise ValueError('Choose upload or download')
    if direction == 'download':
        if content_base64 is not None or sha256 is not None:
            raise ValueError('Download takes only app and path')
        return 'GET', '?' + urlencode({'path': path, 'max_bytes': MCP_TRANSFER_LIMIT}), None
    if content_base64 is None or sha256 is None:
        raise ValueError('Upload requires content_base64 and its SHA-256')
    if len(content_base64) > ((MCP_TRANSFER_LIMIT + 2) // 3) * 4:
        raise ValueError('MCP transfer exceeds 2 MiB; split using shell or use binary HTTP/CLI (16 MiB)')
    try:
        content = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('Invalid base64 content') from None
    if len(content) > MCP_TRANSFER_LIMIT:
        raise ValueError('MCP transfer exceeds 2 MiB; split using shell or use binary HTTP/CLI (16 MiB)')
    if hashlib.sha256(content).hexdigest() != sha256:
        raise ValueError('SHA-256 mismatch')
    return 'PUT', '?' + urlencode({'path': path, 'sha256': sha256}), content


def transfer_response(response, max_bytes=TRANSFER_LIMIT):
    data = response.content
    expected = response.headers.get('X-Content-SHA256')
    actual = hashlib.sha256(data).hexdigest()
    if len(data) > max_bytes or actual != expected:
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


# Only exact platform-authored messages may cross the OAuth bridge.
SAFE_MANAGER_ERRORS = {
    'Apps caller not recognized': 'Apps manager rejected this Commons backend. Ask the platform owner to set the same APPS_MANAGER_CALLER_SECRET on both services.',
    'Idempotency key already used for a different command': 'Command retry key conflicts with another command or timeout. Use a new key only for new work.',
    'Idempotency key already used for different parameters': 'Snapshot retry key conflicts with different parameters. Recover the original request before starting new work.',
    'Operation outcome is unknown; inspect snapshots and app before a new request': 'Snapshot outcome is unknown. Inspect inventory and actual app state before choosing a new key.',
    'Output cursor is ahead of this job': 'Output cursor is ahead of this job; reconnect using a cursor returned by this job.',
    'SHA-256 mismatch; file was not changed': 'Upload checksum mismatch; file was not changed.',
    'Transfer failed: path must be a regular file inside /workspace and within the requested byte limit': 'File must be regular, inside /workspace and within the transfer limit (2 MiB MCP; 16 MiB binary HTTP/CLI).',
    'Transfer metadata exceeded its output limit': 'File helper returned oversized metadata; inspect the app runtime before retrying.',
    'Export the legacy managed database into a new sandbox before backup': 'Snapshot rejected: migrate legacy storage first. This rejection is recorded; use a new key after resolving it.',
    'App is unavailable for backup': 'Snapshot rejected: app is unavailable. This rejection is recorded; use a new key after resolving it.',
    'Snapshot manifest is invalid; no workspace data was changed': 'Snapshot rejected: manifest is invalid; workspace was not changed. Inspect snapshots before selecting another ID and key.',
    'App is busy; retry this transfer after maintenance': 'App is busy; retry this transfer after maintenance. No file was changed.',
    'Upload body timed out; file was not changed': 'Upload timed out; file was not changed.',
}


def manager_error(response):
    try:
        detail = response.json().get('detail')
    except (ValueError, AttributeError):
        return None
    return SAFE_MANAGER_ERRORS.get(detail) if isinstance(detail, str) else None
