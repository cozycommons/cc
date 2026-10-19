"""Private R2 objects with durable admission and request budgets."""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import quote
import xml.etree.ElementTree as ET

from botocore.auth import S3SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
import httpx

from .blobs import BlobError, BlobProvider, digest

STORAGE_BYTES = 8_000_000_000
PART_BYTES = 8 * 1024 ** 2
CLASS_A = 100_000
CLASS_B = 1_000_000


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as output:
        json.dump(data, output)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class RequestBudget:
    def __init__(self, root, identity, *, class_a=CLASS_A, class_b=CLASS_B):
        self.path = Path(root) / 'r2-requests.sqlite'
        self.identity = identity
        self.limits = {'a': class_a, 'b': class_b}

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.path.open('xb'):
            pass
        self.path.chmod(0o600)
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE identity (value TEXT NOT NULL, last_day INTEGER NOT NULL)')
            db.execute('INSERT INTO identity VALUES (?, ?)', (self.identity, int(time.time() // 86400)))
            db.execute('CREATE TABLE requests (day INTEGER PRIMARY KEY, a INTEGER NOT NULL, b INTEGER NOT NULL)')

    def consume(self, category):
        if category is None:
            return
        day = int(time.time() // 86400)
        try:
            with sqlite3.connect(f'{self.path.as_uri()}?mode=rw', uri=True, timeout=10) as db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                identity, last_day = db.execute('SELECT value, last_day FROM identity').fetchone()
                if identity != self.identity or day < last_day:
                    raise BlobError('R2 spending protection needs reconciliation. Cloud requests are paused.')
                db.execute('DELETE FROM requests WHERE day < ?', (day - 34,))
                used = db.execute(f'SELECT COALESCE(SUM({category}), 0) FROM requests').fetchone()[0]
                if used >= self.limits[category]:
                    raise BlobError('The free storage request allowance is exhausted. Cloud requests are paused until usage expires.')
                db.execute('INSERT OR IGNORE INTO requests VALUES (?, 0, 0)', (day,))
                db.execute(f'UPDATE requests SET {category} = {category} + 1 WHERE day = ?', (day,))
                db.execute('UPDATE identity SET last_day = ?', (day,))
        except (sqlite3.Error, OSError, TypeError, ValueError) as exc:
            if isinstance(exc, BlobError):
                raise
            raise BlobError('R2 spending protection is unavailable. Restore its persistent request ledger before continuing.') from exc


class R2Auth(httpx.Auth):
    requires_request_body = True

    def __init__(self, credentials, budget, host):
        self.credentials, self.budget, self.host = credentials, budget, host

    def auth_flow(self, request):
        if request.url.scheme != 'https' or request.url.host != self.host:
            raise BlobError('Refusing to send storage credentials outside the configured R2 account.')
        category = None if request.method == 'DELETE' else ('b' if request.method in ('GET', 'HEAD') and not request.url.query else 'a')
        self.budget.consume(category)
        signed = AWSRequest(method=request.method, url=str(request.url), data=request.content, headers=dict(request.headers))
        S3SigV4Auth(self.credentials, 's3', 'auto').add_auth(signed)
        request.headers.update(dict(signed.headers))
        yield request


def xml(response):
    try:
        root = ET.fromstring(response.content)
        for element in root.iter():
            element.tag = element.tag.split('}')[-1]
        return root
    except ET.ParseError as exc:
        raise BlobError('R2 returned an invalid response. Retry shortly.') from exc


class R2Blobs(BlobProvider):
    def __init__(self, root, account, access_key, secret, bucket, *, transport=None):
        if not re.fullmatch('[a-f0-9]{32}', account or '') or not access_key or not secret or not re.fullmatch('[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket or ''):
            raise ValueError('R2 requires an account ID, bucket, and server-only access key pair.')
        self.root = Path(root).resolve()
        self.bucket = bucket
        self.host = f'{account}.r2.cloudflarestorage.com'
        self.url = f'https://{self.host}/{bucket}'
        self.budget = RequestBudget(self.root, f'{account}/{bucket}')
        self.auth = R2Auth(Credentials(access_key, secret), self.budget, self.host)
        self.transport = transport
        self.transfers = self.root / 'r2-transfers'
        self.transfers.mkdir(exist_ok=True, mode=0o700)

    @classmethod
    def environment(cls, root):
        return cls(root, os.environ.get('CROWD_SET_R2_ACCOUNT_ID'), os.environ.get('CROWD_SET_R2_ACCESS_KEY_ID'),
                   os.environ.get('CROWD_SET_R2_SECRET_ACCESS_KEY'), os.environ.get('CROWD_SET_STORAGE_BUCKET'))

    def client(self):
        return httpx.Client(auth=self.auth, timeout=120, follow_redirects=False, transport=self.transport)

    def object_url(self, key):
        if not key or any(part in ('', '.', '..') for part in key.split('/')):
            raise ValueError('Invalid object key.')
        return f'{self.url}/{quote(key, safe="/")}'

    def ledger(self):
        return {item['key']: item['bytes'] for item in (json.loads(path.read_text()) for path in (self.root / 'objects').glob('*.json'))}

    def check_bucket(self, file_bytes):
        if file_bytes > 3 * 1024 ** 3:
            raise BlobError('R2 free-tier mode limits individual files to 3 GiB.')
        ledger = self.ledger()
        if sum(ledger.values()) > STORAGE_BYTES:
            raise BlobError('Recorded media exceeds the free storage budget. Remove an old set before enabling R2.')
        with self.client() as client:
            if client.head(self.url).status_code != 200:
                raise BlobError('R2 bucket is unavailable. Check its server-only credentials.')
            params = {'list-type': '2', 'max-keys': '1000'}
            completed = set()
            tokens = set()
            while True:
                response = client.get(self.url, params=params)
                if response.status_code != 200:
                    raise BlobError('Cannot reconcile R2 storage. Cloud access is paused.')
                listing = xml(response)
                for item in listing.findall('Contents'):
                    key, size = item.findtext('Key'), int(item.findtext('Size'))
                    if ledger.get(key) != size or item.findtext('StorageClass', 'STANDARD') != 'STANDARD':
                        raise BlobError('R2 contains unaccounted media or a paid storage class. Reconcile the bucket before continuing.')
                    completed.add(key)
                if listing.findtext('IsTruncated') != 'true':
                    break
                token = listing.findtext('NextContinuationToken')
                if not token or token in tokens:
                    raise BlobError('R2 returned an invalid storage listing.')
                tokens.add(token)
                params['continuation-token'] = token
            response = client.get(self.url, params={'uploads': '', 'max-uploads': '1000'})
            if response.status_code != 200:
                raise BlobError('Cannot reconcile R2 unfinished uploads.')
            listing = xml(response)
            states = [json.loads(path.read_text()) for path in self.transfers.glob('*.json')]
            known = {state['upload_id']: state for state in states if state['upload_id']}
            intents = {state['key']: state for state in states if not state['upload_id']}
            if any(ledger.get(state['key']) != state['size'] for state in states):
                raise BlobError('R2 contains an unaccounted transfer reservation. Reconcile it before continuing.')
            if listing.findtext('IsTruncated') == 'true':
                raise BlobError('R2 contains unaccounted unfinished uploads. Reconcile them before continuing.')
            for item in listing.findall('Upload'):
                key, upload_id = item.findtext('Key'), item.findtext('UploadId')
                state = known.get(upload_id)
                if not state and key in intents:
                    state = intents.pop(key)
                    state['upload_id'] = upload_id
                    atomic_json(self.state_path(key), state)
                if not state or state['key'] != key or key in completed:
                    raise BlobError('R2 contains unaccounted unfinished uploads. Reconcile them before continuing.')
                response = client.get(self.object_url(key), params={'uploadId': upload_id})
                if response.status_code == 404:
                    continue
                if response.status_code != 200:
                    raise BlobError('Cannot reconcile R2 unfinished upload bytes.')
                parts = xml(response)
                if parts.findtext('IsTruncated') == 'true' or sum(int(part.findtext('Size')) for part in parts.findall('Part')) > state['size']:
                    raise BlobError('R2 contains unaccounted unfinished upload bytes. Reconcile them before continuing.')

    def state_path(self, key):
        return self.transfers / f'{hashlib.sha256(key.encode()).hexdigest()}.json'

    def abort(self, client, key, state):
        if not state['upload_id']:
            self.recover_creation(client, state)
            if not state['upload_id']:
                return
        response = client.delete(self.object_url(key), params={'uploadId': state['upload_id']})
        if response.status_code not in (204, 404):
            raise BlobError('R2 could not cancel the transfer. Its storage reservation is retained.')

    def recover_creation(self, client, state):
        response = client.get(self.url, params={'uploads': '', 'prefix': state['key'], 'max-uploads': '1000'})
        if response.status_code != 200:
            raise BlobError('R2 could not reconcile the interrupted transfer creation.')
        listing = xml(response)
        matches = [item.findtext('UploadId') for item in listing.findall('Upload') if item.findtext('Key') == state['key']]
        if listing.findtext('IsTruncated') == 'true' or len(matches) > 1:
            raise BlobError('R2 contains ambiguous unfinished uploads. Reconcile them before continuing.')
        if matches:
            state['upload_id'] = matches[0]
            atomic_json(self.state_path(state['key']), state)

    def put(self, path, key, content_type='application/octet-stream'):
        path = Path(path)
        size, checksum = path.stat().st_size, digest(path)
        ledger = self.ledger()
        if ledger.get(key) != size or sum(ledger.values()) > STORAGE_BYTES:
            raise BlobError('The free storage budget has no reservation for this upload.')
        state_path = self.state_path(key)
        state = json.loads(state_path.read_text()) if state_path.exists() else None
        if state and (state['key'], state['size'], state['sha256']) != (key, size, checksum):
            raise BlobError('Transfer state does not match the original. Original bytes are retained.')
        with self.client() as client:
            response = client.head(self.object_url(key))
            if response.status_code == 200:
                self.verify(response, size, checksum)
                if state:
                    self.abort(client, key, state)
                state_path.unlink(missing_ok=True)
                return
            if response.status_code != 404:
                raise BlobError('R2 could not check the original. Retry shortly.')
            parts = {}
            if state and not state['upload_id']:
                self.recover_creation(client, state)
                if not state['upload_id']:
                    state = None
            if state:
                response = client.get(self.object_url(key), params={'uploadId': state['upload_id']})
                if response.status_code == 404:
                    state = None
                elif response.status_code != 200:
                    raise BlobError('R2 could not resume the transfer. Retry shortly.')
                else:
                    listing = xml(response)
                    if listing.findtext('IsTruncated') == 'true':
                        raise BlobError('R2 returned too many upload parts.')
                    parts = {int(item.findtext('PartNumber')): (int(item.findtext('Size')), item.findtext('ETag')) for item in listing.findall('Part')}
            if not state:
                state = {'key': key, 'size': size, 'sha256': checksum, 'upload_id': None}
                atomic_json(state_path, state)
                response = client.post(self.object_url(key), params={'uploads': ''}, headers={
                    'Content-Type': content_type, 'x-amz-storage-class': 'STANDARD', 'x-amz-meta-sha256': checksum,
                })
                if response.status_code != 200:
                    raise BlobError('R2 could not start the transfer. Retry shortly.')
                state['upload_id'] = xml(response).findtext('UploadId')
                if not state['upload_id']:
                    raise BlobError('R2 returned an invalid transfer ID.')
                atomic_json(state_path, state)
            completed = ET.Element('CompleteMultipartUpload')
            with path.open('rb') as source:
                number = 0
                for chunk in iter(lambda: source.read(PART_BYTES), b''):
                    number += 1
                    md5 = hashlib.md5(chunk, usedforsecurity=False).hexdigest()
                    if number in parts:
                        part_size, etag = parts[number]
                        if part_size != len(chunk) or etag.strip('"') != md5:
                            raise BlobError('Stored upload part failed its integrity check.')
                    else:
                        response = client.put(self.object_url(key), params={'uploadId': state['upload_id'], 'partNumber': str(number)}, content=chunk)
                        etag = response.headers.get('etag', '')
                        if response.status_code != 200 or etag.strip('"') != md5:
                            raise BlobError('R2 transfer was interrupted. Reselect the original to resume.')
                    part = ET.SubElement(completed, 'Part')
                    ET.SubElement(part, 'PartNumber').text = str(number)
                    ET.SubElement(part, 'ETag').text = etag
            response = client.post(self.object_url(key), params={'uploadId': state['upload_id']}, content=ET.tostring(completed), headers={'Content-Type': 'application/xml'})
            if response.status_code != 200 or xml(response).tag == 'Error':
                raise BlobError('R2 has not confirmed the completed transfer. Retry shortly.')
            self.verify(client.head(self.object_url(key)), size, checksum)
        state_path.unlink(missing_ok=True)

    @staticmethod
    def verify(response, size, checksum):
        if response.status_code != 200 or int(response.headers.get('content-length', -1)) != size or response.headers.get('x-amz-meta-sha256') != checksum:
            raise BlobError('Stored media failed its size or integrity check. Original bytes are retained.')

    def remove(self, keys):
        with self.client() as client:
            for key in keys:
                state_path = self.state_path(key)
                if state_path.exists():
                    self.abort(client, key, json.loads(state_path.read_text()))
                response = client.delete(self.object_url(key))
                if response.status_code not in (204, 404):
                    raise BlobError('R2 could not remove media. Its storage reservation is retained.')
                state_path.unlink(missing_ok=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Initialize spending protection once for a new, empty R2 bucket. Never reset existing counters.')
    parser.add_argument('--initialize-budget', action='store_true', required=True)
    parser.parse_args()
    provider = R2Blobs.environment(os.environ['CROWD_SET_DATA_DIR'])
    provider.budget.initialize()
    print('Initialized persistent R2 request protection.')
