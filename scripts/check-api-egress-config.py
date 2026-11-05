#!/usr/bin/env python3
"""Offline rollout preflight. Never print secret values or connect to a service."""
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit


def check(values: dict[str, str], supabase_host: str, db_host: str) -> None:
    if not re.fullmatch(r'[a-z0-9]+\.supabase\.co', supabase_host):
        raise ValueError('EGRESS_SUPABASE_HOST must be the exact project-ref.supabase.co')
    if not re.fullmatch(r'[a-z0-9.-]+\.pooler\.supabase\.com', db_host):
        raise ValueError('use one exact Supabase session pooler hostname for EGRESS_DB_HOST')
    api = urlsplit(values.get('SUPABASE_URL', ''))
    if api.scheme != 'https' or api.netloc != supabase_host or api.path not in {'', '/'}:
        raise ValueError('SUPABASE_URL must match EGRESS_SUPABASE_HOST over HTTPS')
    if values.get('EXPECTED_SUPABASE_PROJECT') != supabase_host.split('.')[0]:
        raise ValueError('EXPECTED_SUPABASE_PROJECT must match EGRESS_SUPABASE_HOST')
    for key in ['SUPABASE_DB_URL', 'ANALYTICS_DATABASE_URL']:
        value = values.get(key)
        if not value and key == 'ANALYTICS_DATABASE_URL':
            continue
        parsed = urlsplit(value or '')
        if parsed.scheme not in {'postgres', 'postgresql'} or parsed.hostname != db_host or parsed.port != 5432:
            raise ValueError(f'{key} must use EGRESS_DB_HOST:5432 directly (session pooler)')
        if parse_qs(parsed.query).get('sslmode', ['require'])[-1] not in {'require', 'verify-ca', 'verify-full'}:
            raise ValueError(f'{key} must require TLS')
        if parse_qs(parsed.query).get('host') or parse_qs(parsed.query).get('hostaddr'):
            raise ValueError(f'{key} must not override its relay hostname')
    if not values.get('SUPABASE_SERVICE_KEY'):
        raise ValueError('SUPABASE_SERVICE_KEY is missing')


def main() -> None:
    # Compose env_file format:raw preserves each value, including dollar signs.
    values = {}
    for line in Path(sys.argv[1]).read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#'):
            key, separator, value = line.partition('=')
            if not separator or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
                raise ValueError('expected raw NAME=value lines without shell syntax')
            values[key] = value
    check(values, os.environ['EGRESS_SUPABASE_HOST'], os.environ['EGRESS_DB_HOST'])
    print('PASS egress runtime configuration (offline; no values printed)')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, IndexError):
        # URL parser exceptions can contain submitted passwords. Never echo them.
        raise SystemExit('Invalid egress runtime configuration; check deployment.md requirements') from None
