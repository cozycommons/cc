"""Bounded validation for self-contained USDZ uploads; never extract archive paths."""
import hashlib
import io
from pathlib import PurePosixPath
import stat
import zipfile
import zlib

from fastapi import HTTPException

MAX_SCAN_BYTES = 50 * 1024 * 1024
MAX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 256


def validate_scan(content: bytes, filename: str) -> dict:
    if not filename.lower().endswith('.usdz') or len(filename) > 200:
        raise HTTPException(422, 'Choose a USDZ file with a filename shorter than 200 characters.')
    if not content or len(content) > MAX_SCAN_BYTES:
        raise HTTPException(413, 'USDZ scans must be between 1 byte and 50 MiB.')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_ARCHIVE_ENTRIES:
                raise ValueError('The USDZ must contain between 1 and 256 archive entries.')
            if PurePosixPath(entries[0].filename).suffix.lower() not in {'.usd', '.usda', '.usdc'}:
                raise ValueError('The first USDZ entry must be a USD, USDA, or USDC root layer.')
            total = 0
            names = set()
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValueError('The USDZ uses an unsupported ZIP compression method.')
                if (entry.filename in names or len(entry.filename) > 512 or path.is_absolute()
                        or any(part in {'.', '..'} for part in entry.filename.split('/'))
                        or '\\' in entry.filename or ':' in entry.filename
                        or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1):
                    raise ValueError('The USDZ contains an unsafe, duplicate, or encrypted archive entry.')
                names.add(entry.filename)
                if entry.file_size > MAX_EXPANDED_BYTES - total:
                    raise ValueError('The expanded USDZ exceeds 200 MiB.')
                with archive.open(entry) as source:
                    header = source.read(8)
                    total += len(header)
                    if entry is entries[0] and not (header.startswith(b'#usda') or header == b'PXR-USDC'):
                        raise ValueError('The USDZ root layer is not supported USDA or USDC data.')
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        total += len(chunk)
                        if total > MAX_EXPANDED_BYTES:
                            raise ValueError('The expanded USDZ exceeds 200 MiB.')
            return {'byte_size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, ValueError, EOFError, zlib.error) as error:
        raise HTTPException(422, str(error) or 'This file is not a valid USDZ archive.') from error
