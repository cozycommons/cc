import io
import zipfile

from fastapi import HTTPException
import pytest

from floor_planner.scan_validation import validate_scan


def synthetic_scan(root='#usda 1.0\n\ndef Mesh "Wall" {\n point3f[] points = [(0,0,0), (3,0,0), (3,2,0), (0,2,0)]\n int[] faceVertexCounts = [4]\n int[] faceVertexIndices = [0,1,2,3]\n}\n', name='root.usda', compression=zipfile.ZIP_STORED):
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w', compression=compression) as archive:
        archive.writestr(name, root)
    return target.getvalue()


def test_accepts_ascii_and_binary_usdz_and_records_integrity():
    ascii_scan = synthetic_scan()
    result = validate_scan(ascii_scan, 'apartment.usdz')
    assert result['byte_size'] == len(ascii_scan)
    assert len(result['sha256']) == 64
    assert validate_scan(synthetic_scan(b'PXR-USDC\x00', 'root.usdc'), 'binary.usdz')


@pytest.mark.parametrize('content,filename', [
    (b'not a zip', 'bad.usdz'), (synthetic_scan(), 'bad.glb'),
    (synthetic_scan(name='../root.usda'), 'bad.usdz'),
    (synthetic_scan(name='https://example.com/root.usda'), 'bad.usdz'),
    (synthetic_scan(name='root.txt'), 'bad.usdz'),
    (synthetic_scan(root='not USD'), 'bad.usdz'),
])
def test_rejects_invalid_or_unsafe_archives(content, filename):
    with pytest.raises(HTTPException) as failure:
        validate_scan(content, filename)
    assert failure.value.status_code == 422


def test_rejects_expansion_bomb_without_materializing_decompressed_archive(monkeypatch):
    import floor_planner.scan_validation as validation
    monkeypatch.setattr(validation, 'MAX_EXPANDED_BYTES', 1024)
    with pytest.raises(HTTPException, match='') as failure:
        validate_scan(synthetic_scan(root='#usda 1.0\n' + ' ' * 2000, compression=zipfile.ZIP_DEFLATED), 'bomb.usdz')
    assert '200 MiB' in failure.value.detail


def test_checks_uploaded_size_and_duplicate_entries(monkeypatch):
    import floor_planner.scan_validation as validation
    monkeypatch.setattr(validation, 'MAX_SCAN_BYTES', 10)
    with pytest.raises(HTTPException) as failure:
        validate_scan(synthetic_scan(), 'large.usdz')
    assert failure.value.status_code == 413
    monkeypatch.setattr(validation, 'MAX_SCAN_BYTES', 50 * 1024 * 1024)
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w') as archive:
        archive.writestr('root.usda', '#usda 1.0\n')
        with pytest.warns(UserWarning):
            archive.writestr('root.usda', '#usda 1.0\n')
    with pytest.raises(HTTPException) as failure:
        validate_scan(target.getvalue(), 'duplicate.usdz')
    assert 'duplicate' in failure.value.detail
