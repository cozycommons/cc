from concurrent.futures import ThreadPoolExecutor
import hashlib
import xml.etree.ElementTree as ET

from fastapi import HTTPException
import httpx
import pytest

from crowdset.blobs import BlobError
from crowdset.limits import Limits
from crowdset.r2 import PART_BYTES, STORAGE_BYTES, R2Blobs, RequestBudget, atomic_json
from crowdset.storage import OriginalStore
from crowdset.store import Store

ACCOUNT = 'a' * 32


def provider(root, handler):
    value = R2Blobs(root, ACCOUNT, 'test-access', 'test-secret', 'crowdset-media', transport=httpx.MockTransport(handler))
    value.budget.initialize()
    return value


def reserve(root, blobs, key, size):
    originals = OriginalStore(root, blobs)
    originals.record_blob(key, size)
    return originals


def test_request_budget_is_durable_atomic_and_blocks_before_request(tmp_path, monkeypatch):
    budget = RequestBudget(tmp_path, 'account/bucket', class_a=7, class_b=3)
    budget.initialize()
    with pytest.raises(FileExistsError):
        budget.initialize()

    def spend(_):
        try:
            RequestBudget(tmp_path, 'account/bucket', class_a=7).consume('a')
            return True
        except BlobError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(spend, range(30))) == 7
    with pytest.raises(BlobError, match='exhausted'):
        budget.consume('a')
    budget.consume(None)
    with pytest.raises(BlobError, match='reconciliation'):
        RequestBudget(tmp_path, 'different/bucket').consume('b')
    import time
    now = time.time()
    monkeypatch.setattr('crowdset.r2.time.time', lambda: now - 86400)
    with pytest.raises(BlobError, match='reconciliation'):
        budget.consume('b')
    monkeypatch.setattr('crowdset.r2.time.time', lambda: now + 35 * 86400)
    budget.consume('a')
    budget.path.unlink()
    with pytest.raises(BlobError, match='persistent request ledger'):
        budget.consume('a')


def test_r2_signs_private_requests_and_stops_reads_at_budget(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.host == f'{ACCOUNT}.r2.cloudflarestorage.com'
        assert request.headers['authorization'].startswith('AWS4-HMAC-SHA256 Credential=test-access/')
        assert '/auto/s3/aws4_request' in request.headers['authorization']
        assert 'test-secret' not in str(request.url) + str(request.headers)
        assert request.headers['x-amz-content-sha256'] == hashlib.sha256(request.content).hexdigest()
        return httpx.Response(200, content=b'abc')
    blobs = provider(tmp_path, handler)
    blobs.budget.limits['b'] = 1
    with blobs.client() as client:
        assert client.get(blobs.object_url('originals/set/clip/hash')).content == b'abc'
        with pytest.raises(BlobError, match='exhausted'):
            client.head(blobs.object_url('originals/set/clip/hash'))
        with pytest.raises(BlobError, match='outside'):
            client.get('https://example.com/stolen')
    assert len(calls) == 1


def test_multipart_resumes_lost_part_and_completion_acknowledgments(tmp_path):
    body = b'a' * PART_BYTES + b'last part'
    path = tmp_path / 'original'
    path.write_bytes(body)
    key = 'originals/set/clip/hash'
    state = {'parts': {}, 'complete': False, 'fail_create': True, 'fail_part': True, 'fail_complete': True, 'creates': 0, 'writes': []}
    checksum = hashlib.sha256(body).hexdigest()

    def handler(request):
        query = request.url.params
        if request.method == 'HEAD':
            return httpx.Response(200, headers={'Content-Length': str(len(body)), 'x-amz-meta-sha256': checksum}) if state['complete'] else httpx.Response(404)
        if request.method == 'POST' and 'uploads' in query:
            assert request.headers['x-amz-storage-class'] == 'STANDARD'
            assert request.headers['x-amz-meta-sha256'] == checksum
            state['creates'] += 1
            if state['fail_create']:
                state['fail_create'] = False
                raise httpx.ReadError('Lost creation acknowledgment')
            return httpx.Response(200, content='<InitiateMultipartUploadResult><UploadId>one</UploadId></InitiateMultipartUploadResult>')
        if request.method == 'PUT':
            number = int(query['partNumber'])
            state['parts'][number] = request.content
            state['writes'].append(number)
            if state['fail_part']:
                state['fail_part'] = False
                raise httpx.ReadError('Lost part acknowledgment')
            return httpx.Response(200, headers={'ETag': '"' + hashlib.md5(request.content).hexdigest() + '"'})
        if request.method == 'GET' and 'uploads' in query:
            return httpx.Response(200, content=f'<ListMultipartUploadsResult><Upload><Key>{key}</Key><UploadId>one</UploadId></Upload></ListMultipartUploadsResult>')
        if request.method == 'GET':
            parts = ''.join(f'<Part><PartNumber>{number}</PartNumber><Size>{len(value)}</Size><ETag>"{hashlib.md5(value).hexdigest()}"</ETag></Part>' for number, value in state['parts'].items())
            return httpx.Response(200, content=f'<ListPartsResult>{parts}</ListPartsResult>')
        if request.method == 'POST':
            assert len(ET.fromstring(request.content).findall('Part')) == 2
            assert b''.join(value for _, value in sorted(state['parts'].items())) == body
            state['complete'] = True
            if state['fail_complete']:
                state['fail_complete'] = False
                raise httpx.ReadError('Lost completion acknowledgment')
        if request.method == 'DELETE':
            return httpx.Response(404)
        raise AssertionError(request)

    blobs = provider(tmp_path, handler)
    reserve(tmp_path, blobs, key, len(body))
    with pytest.raises(httpx.ReadError, match='creation acknowledgment'):
        blobs.put(path, key)
    with pytest.raises(httpx.ReadError, match='part acknowledgment'):
        blobs.put(path, key)
    with pytest.raises(httpx.ReadError, match='completion acknowledgment'):
        blobs.put(path, key)
    blobs.put(path, key)
    assert state['creates'] == 1
    assert state['writes'] == [1, 2]
    assert not blobs.state_path(key).exists()
    assert path.read_bytes() == body


def test_failed_abort_retains_reservation_and_can_cleanup_without_request_budget(tmp_path):
    state = {'fail': True, 'calls': []}
    def handler(request):
        state['calls'].append(request)
        return httpx.Response(503 if state['fail'] else 204)
    blobs = provider(tmp_path, handler)
    key = 'originals/set/clip/hash'
    originals = reserve(tmp_path, blobs, key, 100)
    atomic_json(blobs.state_path(key), {'key': key, 'upload_id': 'pending'})
    blobs.budget.path.unlink()
    with pytest.raises(BlobError, match='reservation is retained'):
        originals.remove_blobs([key])
    assert originals.usage()[0] == 100
    assert blobs.state_path(key).exists()
    state['fail'] = False
    originals.remove_blobs([key])
    assert originals.usage()[0] == 0
    assert not blobs.state_path(key).exists()
    assert all(request.method == 'DELETE' for request in state['calls'])


def test_r2_rejects_unreserved_or_over_budget_writes_before_network(tmp_path, monkeypatch):
    calls = []
    blobs = provider(tmp_path, lambda request: calls.append(request))
    source = tmp_path / 'file'
    source.write_bytes(b'abc')
    with pytest.raises(BlobError, match='reservation'):
        blobs.put(source, 'mixes/set/one.wav')
    originals = reserve(tmp_path, blobs, 'mixes/set/one.wav', 3)
    originals.record_blob('originals/other/clip/hash', STORAGE_BYTES)
    with pytest.raises(BlobError, match='reservation'):
        blobs.put(source, 'mixes/set/one.wav')
    assert calls == []
    monkeypatch.setenv('CROWDSET_STORAGE_PROVIDER', 'r2')
    limits = Limits.environment()
    assert limits.original_bytes == STORAGE_BYTES
    assert limits.public()['free_tier']
    with pytest.raises(HTTPException) as error:
        originals.admit(limits, incoming=1)
    assert error.value.status_code == 507
    monkeypatch.setenv('CROWDSET_ORIGINAL_BYTES', str(100_000_000_000 + 1))
    with pytest.raises(ValueError):
        Limits.environment()


@pytest.mark.parametrize('remote', [False, True])
def test_r2_startup_accepts_environment_default_upload_limit(tmp_path, monkeypatch, remote):
    monkeypatch.setenv('CROWDSET_STORAGE_PROVIDER', 'r2')
    monkeypatch.setenv('CROWDSET_REMOTE_WORKER', '1' if remote else '0')
    monkeypatch.setenv('CROWDSET_WORKER_TOKEN', 'test-worker-only')
    monkeypatch.setenv('CROWDSET_ORIGINAL_BYTES', '100000000000')
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == 'HEAD':
            return httpx.Response(200)
        body = '<ListBucketResult/>' if 'list-type' in request.url.params else '<ListMultipartUploadsResult/>'
        return httpx.Response(200, content=body)

    blobs = provider(tmp_path, handler)
    limits = Limits.environment()
    store = Store(tmp_path, blobs=blobs)
    try:
        assert store.limits.file_bytes == (8 if remote else 3) * 1024 ** 3
    finally:
        store.close()
    assert len(calls) == 3
    with pytest.raises(BlobError, match=f'{8 if remote else 3} GiB'):
        blobs.check_bucket(limits.file_bytes + 1)
    assert len(calls) == 3


@pytest.mark.parametrize('unaccounted', ['object', 'multipart', 'paid_class'])
def test_startup_fails_closed_on_unaccounted_remote_storage(tmp_path, unaccounted):
    key = 'originals/set/clip/hash'
    def handler(request):
        if request.method == 'HEAD':
            return httpx.Response(200)
        if 'list-type' in request.url.params:
            contents = f'<Contents><Key>{key}</Key><Size>3</Size><StorageClass>{"STANDARD_IA" if unaccounted == "paid_class" else "STANDARD"}</StorageClass></Contents>' if unaccounted != 'multipart' else ''
            return httpx.Response(200, content=f'<ListBucketResult>{contents}</ListBucketResult>')
        return httpx.Response(200, content=f'<ListMultipartUploadsResult><Upload><Key>{key}</Key><UploadId>unknown</UploadId></Upload></ListMultipartUploadsResult>')
    blobs = provider(tmp_path, handler)
    if unaccounted == 'paid_class':
        reserve(tmp_path, blobs, key, 3)
    with pytest.raises(BlobError, match='unaccounted'):
        blobs.check_bucket(2 * 1024 ** 3)


@pytest.mark.parametrize('reserved,remote_bytes', [(False, 3), (True, 4), (True, 3)])
def test_startup_reconciles_pending_transfer_reservations(tmp_path, reserved, remote_bytes):
    key = 'originals/set/clip/hash'
    def handler(request):
        if request.method == 'HEAD':
            return httpx.Response(200)
        if 'list-type' in request.url.params:
            return httpx.Response(200, content='<ListBucketResult/>')
        if 'uploadId' in request.url.params:
            return httpx.Response(200, content=f'<ListPartsResult><Part><PartNumber>1</PartNumber><Size>{remote_bytes}</Size></Part></ListPartsResult>')
        return httpx.Response(200, content=f'<ListMultipartUploadsResult><Upload><Key>{key}</Key><UploadId>pending</UploadId></Upload></ListMultipartUploadsResult>')
    blobs = provider(tmp_path, handler)
    atomic_json(blobs.state_path(key), {'key': key, 'size': 3, 'upload_id': 'pending'})
    if reserved:
        reserve(tmp_path, blobs, key, 3)
    if reserved and remote_bytes == 3:
        blobs.check_bucket(2 * 1024 ** 3)
    else:
        with pytest.raises(BlobError, match='unaccounted'):
            blobs.check_bucket(2 * 1024 ** 3)


def test_media_budget_exhaustion_returns_service_unavailable(tmp_path):
    from types import SimpleNamespace
    from starlette.requests import Request
    from crowdset.app import stored_media
    calls = []
    blobs = provider(tmp_path, lambda request: calls.append(request))
    blobs.budget.limits['b'] = 0
    request = Request({'type': 'http', 'headers': [(b'range', b'bytes=1-3')]})
    with pytest.raises(HTTPException) as error:
        stored_media(SimpleNamespace(blobs=blobs, remote=None), 'originals/set/clip/hash', request, 'clip.mp4', False, 'video/mp4')
    assert error.value.status_code == 503
    assert calls == []


def test_paid_storage_budget_is_shared_by_admission_and_r2(tmp_path, monkeypatch):
    monkeypatch.setenv('CROWDSET_STORAGE_PROVIDER', 'r2')
    monkeypatch.setenv('CROWDSET_ORIGINAL_BYTES', '100000000000')
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={'Content-Length': '3', 'x-amz-meta-sha256': hashlib.sha256(b'abc').hexdigest()})
    blobs = provider(tmp_path, handler)
    assert blobs.storage_bytes == Limits.environment().original_bytes == 100_000_000_000
    originals = reserve(tmp_path, blobs, 'mixes/set/one.wav', 3)
    originals.record_blob('originals/other/clip/hash', 9_000_000_000)
    source = tmp_path / 'file'
    source.write_bytes(b'abc')
    originals.admit(Limits.environment(), incoming=1)
    blobs.put(source, 'mixes/set/one.wav')
    assert len(calls) == 1
    calls.clear()
    originals.record_blob('originals/overflow/clip/hash', 100_000_000_000)
    with pytest.raises(BlobError, match='reservation'):
        blobs.put(source, 'mixes/set/one.wav')
    assert calls == []


def test_direct_parts_have_exact_length_and_expiring_scoped_signatures(tmp_path):
    from urllib.parse import urlsplit, parse_qs
    blobs = provider(tmp_path, lambda request: httpx.Response(500))
    key = 'originals/set/clip/direct'
    reserve(tmp_path, blobs, key, 3)
    atomic_json(blobs.state_path(key), {'key': key, 'size': 3, 'sha256': 'f' * 64, 'upload_id': 'private-upload'})
    part = blobs.direct_part(key, 1)
    params = parse_qs(urlsplit(part['url']).query)
    assert params['uploadId'] == ['private-upload'] and params['partNumber'] == ['1']
    assert params['X-Amz-Expires'] == ['300']
    assert params['X-Amz-SignedHeaders'] == ['content-length;host']
    assert part['bytes'] == 3
    with pytest.raises(BlobError):
        blobs.direct_part(key, 2)


def test_direct_completion_uses_authoritative_parts_and_preserves_incomplete_reservations(tmp_path):
    state = {'complete': False, 'part_size': 2}
    checksum = hashlib.sha256(b'abc').hexdigest()
    def handler(request):
        if request.method == 'HEAD':
            return httpx.Response(200, headers={'Content-Length': '3', 'x-amz-meta-sha256': checksum}) if state['complete'] else httpx.Response(404)
        if request.method == 'GET':
            return httpx.Response(200, content=f'<ListPartsResult><Part><PartNumber>1</PartNumber><Size>{state["part_size"]}</Size><ETag>etag</ETag></Part></ListPartsResult>')
        state['complete'] = True
        return httpx.Response(200, content='<CompleteMultipartUploadResult/>')
    blobs = provider(tmp_path, handler)
    key = 'originals/set/clip/direct'
    reserve(tmp_path, blobs, key, 3)
    atomic_json(blobs.state_path(key), {'key': key, 'size': 3, 'sha256': checksum, 'upload_id': 'upload'})
    with pytest.raises(BlobError, match='bounds'):
        blobs.finish_direct(key, 3, checksum)
    assert blobs.state_path(key).exists() and blobs.ledger()[key] == 3
    state['part_size'] = 3
    blobs.finish_direct(key, 3, checksum)
    assert not blobs.state_path(key).exists()
    blobs.finish_direct(key, 3, checksum)


def test_direct_lost_completion_ack_does_not_leave_unaccounted_multipart(tmp_path):
    checksum = hashlib.sha256(b'abc').hexdigest()
    calls = []
    def handler(request):
        calls.append(request)
        if request.method == 'HEAD':
            return httpx.Response(200, headers={'Content-Length': '3', 'x-amz-meta-sha256': checksum})
        assert request.method == 'DELETE'
        return httpx.Response(204)
    blobs = provider(tmp_path, handler)
    key = 'originals/set/clip/direct'
    reserve(tmp_path, blobs, key, 3)
    state = {'key': key, 'size': 3, 'sha256': checksum, 'upload_id': 'lost-ack-upload'}
    atomic_json(blobs.state_path(key), state)
    assert blobs.begin_direct(key, 3, checksum, 'video/mp4')['complete']
    assert [r.method for r in calls] == ['HEAD', 'DELETE']
    assert not blobs.state_path(key).exists()
    atomic_json(blobs.state_path(key), state)
    blobs.finish_direct(key, 3, checksum)
    assert [r.method for r in calls][-2:] == ['HEAD', 'DELETE']
    assert not blobs.state_path(key).exists()
