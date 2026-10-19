from dataclasses import dataclass
import os

GIB = 1024 ** 3
MIB = 1024 ** 2


def integer(name, default, minimum, maximum):
    value = int(os.environ.get(f'CROWD_SET_{name}', default))
    if not minimum <= value <= maximum:
        raise ValueError(f'CROWD_SET_{name} must be between {minimum} and {maximum}.')
    return value


@dataclass(frozen=True)
class Limits:
    recordings: int = 64
    file_bytes: int = 2 * GIB
    recording_seconds: int = 7200
    set_seconds: int = 28800
    original_bytes: int = 16 * GIB
    work_bytes: int = 8 * GIB
    free_bytes: int = 2 * GIB
    chunk_bytes: int = 8 * MIB
    upload_seconds: int = 86400
    job_seconds: int = 3600
    media_seconds: int = 600
    free_tier: bool = False

    @classmethod
    def environment(cls):
        r2 = os.environ.get('CROWD_SET_STORAGE_PROVIDER', '').lower() == 'r2'
        original_default = 8_000_000_000 if r2 else (80 if os.environ.get('CROWD_SET_STORAGE_KEY') else 16) * GIB
        return cls(
            recordings=integer('MAX_RECORDINGS', 64, 1, 500),
            file_bytes=integer('MAX_FILE_BYTES', 2 * GIB, MIB, (2 if r2 else 16) * GIB),
            recording_seconds=integer('MAX_RECORDING_SECONDS', 7200, 1, 14400),
            set_seconds=integer('MAX_SET_SECONDS', 28800, 1, 86400),
            original_bytes=integer('ORIGINAL_BYTES', original_default, MIB, 8_000_000_000 if r2 else 16 * 1024 * GIB),
            work_bytes=integer('WORK_BYTES', 8 * GIB, MIB, 1024 * GIB),
            free_bytes=integer('FREE_BYTES', 2 * GIB, MIB, 1024 * GIB),
            job_seconds=integer('JOB_SECONDS', 3600, 60, 14400),
            media_seconds=integer('MEDIA_SECONDS', 600, 10, 1800),
            free_tier=r2,
        )

    def public(self):
        return {'resumable_uploads': True, 'event_metadata': True, **{key: getattr(self, key) for key in (
            'recordings', 'file_bytes', 'recording_seconds', 'set_seconds',
            'original_bytes', 'chunk_bytes', 'upload_seconds', 'free_tier',
        )}}
