"""Fernet keys for stored third-party credentials, with rotation.

`<PROJECT>_CREDENTIALS_KEY` holds one Fernet key, or several separated by
commas. The first key encrypts; every listed key decrypts. To rotate a key:
prepend a new one and deploy, run `python -m scripts.rotate_credentials` to
re-encrypt every row with it, then remove the old key and deploy again.
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, MultiFernet

GENERATE = 'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'


def credentials_fernet(name: str, error: type[Exception]) -> MultiFernet:
    """The MultiFernet for env var `name`, raising `error` when it is missing or malformed."""
    keys = [key.strip() for key in os.environ.get(name, "").split(",") if key.strip()]
    if not keys:
        raise error(f"{name} is not set. Generate one with: {GENERATE}")
    try:
        return MultiFernet([Fernet(key.encode("utf-8")) for key in keys])
    except ValueError as e:  # Fernet's message names the format, never the key
        raise error(f"{name} is invalid: {e}")
