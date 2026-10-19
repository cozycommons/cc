import base64
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx


class BlobError(ValueError):
    pass


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


class BlobProvider:
    def materialize(self, key, destination, expected_size, expected_hash):
        destination = Path(destination)
        if destination.exists() and destination.stat().st_size == expected_size and digest(destination) == expected_hash:
            return destination
        partial = destination.with_name(destination.name + '.download')
        try:
            with self.client() as client, client.stream('GET', self.object_url(key)) as response:
                if response.status_code != 200:
                    raise BlobError('Could not read the original from media storage. Retry shortly.')
                written = 0
                checksum = hashlib.sha256()
                with partial.open('wb') as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        written += len(chunk)
                        if written > expected_size:
                            raise BlobError('Stored original exceeded its recorded size.')
                        checksum.update(chunk)
                        output.write(chunk)
            if written != expected_size or checksum.hexdigest() != expected_hash:
                raise BlobError('Stored original failed its integrity check. Original metadata is retained.')
            partial.replace(destination)
        finally:
            partial.unlink(missing_ok=True)
        return destination


class SupabaseBlobs(BlobProvider):
    def __init__(self, url, key, bucket, *, transport=None):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.supabase.co') or parsed.path not in ('', '/') or parsed.username or parsed.port:
            raise ValueError('Blob storage requires an HTTPS Supabase project URL.')
        if not key or key.startswith('sb_publishable_') or not bucket or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in bucket):
            raise ValueError('Blob storage requires a server-only key and a private bucket name.')
        if key.count('.') == 2:
            try:
                claims = json.loads(base64.urlsafe_b64decode(key.split('.')[1] + '==='))
            except (ValueError, UnicodeError):
                raise ValueError('Blob storage requires a server-only key.') from None
            if claims.get('role') != 'service_role':
                raise ValueError('Blob storage requires a server-only key.')
        self.url = url.rstrip('/')
        self.storage_url = self.url.replace('.supabase.co', '.storage.supabase.co')
        self.bucket = bucket
        self.headers = {'apikey': key, 'Authorization': f'Bearer {key}'}
        self.transport = transport

    @classmethod
    def environment(cls):
        key = os.environ.get('CROWD_SET_STORAGE_KEY')
        bucket = os.environ.get('CROWD_SET_STORAGE_BUCKET')
        if not key and not bucket:
            return None
        return cls(os.environ.get('CROWD_SET_AUTH_URL', ''), key, bucket or 'crowd-set-media')

    def client(self):
        return httpx.Client(headers=self.headers, timeout=120, follow_redirects=False, transport=self.transport)

    def object_url(self, key):
        parts = key.split('/')
        if not key or any(part in ('', '.', '..') for part in parts):
            raise ValueError('Invalid object key.')
        return f'{self.url}/storage/v1/object/authenticated/{self.bucket}/{quote(key, safe="/")}'

    def check_bucket(self, file_bytes):
        with self.client() as client:
            response = client.get(f'{self.url}/storage/v1/bucket/{self.bucket}')
        if response.status_code != 200:
            raise BlobError('Private media storage is unavailable. Check the bucket and server key.')
        data = response.json()
        if data.get('public') is not False or int(data.get('file_size_limit') or 0) < file_bytes:
            raise BlobError('Media bucket must be private and allow the configured file size.')

    def put(self, path, key, content_type='application/octet-stream'):
        path = Path(path)
        size = path.stat().st_size
        state = path.with_name(path.name + '.transfer.json')
        with self.client() as client:
            existing = client.head(self.object_url(key))
            if existing.status_code == 200:
                if int(existing.headers.get('content-length', -1)) != size:
                    raise BlobError('Stored media size did not match. Original bytes are retained; retry.')
                state.unlink(missing_ok=True)
                return
            if existing.status_code not in (400, 404):
                raise BlobError('Media storage is unavailable. Original bytes are retained; retry.')
            location = json.loads(state.read_text()).get('location') if state.exists() else None
            if location:
                self.validate_location(location)
                response = client.head(location, headers={'Tus-Resumable': '1.0.0'})
                if response.status_code in (404, 410):
                    location = None
                elif response.status_code != 200 and response.status_code != 204:
                    raise BlobError('Could not resume the storage transfer. Retry shortly.')
            if not location:
                metadata = {'bucketName': self.bucket, 'objectName': key, 'contentType': content_type, 'cacheControl': '0'}
                response = client.post(f'{self.storage_url}/storage/v1/upload/resumable', headers={
                    'Tus-Resumable': '1.0.0', 'Upload-Length': str(size),
                    'Upload-Metadata': ','.join(f'{name} {base64.b64encode(value.encode()).decode()}' for name, value in metadata.items()),
                })
                if response.status_code != 201 or 'location' not in response.headers:
                    raise BlobError('Could not start the storage transfer. Check storage capacity and retry.')
                location = urljoin(str(response.url), response.headers['location'])
                self.validate_location(location)
                temporary = state.with_suffix('.tmp')
                temporary.write_text(json.dumps({'location': location}))
                temporary.replace(state)
                offset = 0
            else:
                offset = int(response.headers.get('upload-offset', -1))
            if not 0 <= offset <= size:
                raise BlobError('Storage returned an invalid upload offset.')
            with path.open('rb') as source:
                source.seek(offset)
                while offset < size:
                    chunk = source.read(6 * 1024 * 1024)
                    response = client.patch(location, content=chunk, headers={
                        'Tus-Resumable': '1.0.0', 'Upload-Offset': str(offset), 'Content-Type': 'application/offset+octet-stream',
                    })
                    if response.status_code != 204 or int(response.headers.get('upload-offset', -1)) != offset + len(chunk):
                        raise BlobError('Storage transfer was interrupted. Original bytes are retained; retry.')
                    offset += len(chunk)
            confirmed = client.head(self.object_url(key))
            if confirmed.status_code != 200 or int(confirmed.headers.get('content-length', -1)) != size:
                raise BlobError('Storage has not confirmed the complete recording. Retry shortly.')
        state.unlink(missing_ok=True)

    def validate_location(self, location):
        parsed = urlsplit(location)
        if parsed.scheme != 'https' or parsed.netloc not in (urlsplit(self.url).netloc, urlsplit(self.storage_url).netloc) or not parsed.path.startswith('/storage/v1/upload/resumable/') or parsed.username:
            raise BlobError('Storage returned an invalid transfer location.')

    def remove(self, keys):
        if not keys:
            return
        with self.client() as client:
            response = client.request('DELETE', f'{self.url}/storage/v1/object/{self.bucket}', json={'prefixes': keys})
        if response.status_code != 200:
            raise BlobError('Media storage could not remove the recording. Retry shortly.')


def environment(root):
    provider = os.environ.get('CROWD_SET_STORAGE_PROVIDER', '').lower()
    if provider == 'r2':
        from .r2 import R2Blobs
        return R2Blobs.environment(root)
    if provider not in ('', 'supabase'):
        raise ValueError('Unknown media storage provider.')
    return SupabaseBlobs.environment()
