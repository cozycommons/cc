"""Re-encrypt stored third-party credentials with the first key in <PROJECT>_CREDENTIALS_KEY.

Rotation (see credential_keys.py): prepend a new key to the env var and deploy,
run this with --apply, then drop the old key and deploy again. Without --apply
it only counts what would change. It never prints a credential. A non-zero
exit means some rows were not rotated (undecryptable, or changed by the app
during the run); rerun it before dropping the old key.

    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... BELI_CREDENTIALS_KEY=new,old \\
        python -m scripts.rotate_credentials beli [--apply] [--host db.example.supabase.co]

Any host other than loopback must be named again with --host, so a stray
SUPABASE_URL cannot point a rotation at production by accident.
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

from cryptography.fernet import InvalidToken

from credential_keys import credentials_fernet

# Every encrypted column per project table. Empty strings (an unset Resy auth token) are left alone.
PROJECTS = {
    'beli': ('beli_accounts', 'BELI_CREDENTIALS_KEY', ('beli_id_enc', 'password_enc')),
    'resy': ('resy_accounts', 'RESY_CREDENTIALS_KEY', ('email_enc', 'password_enc', 'auth_token_enc')),
    'partiful': ('partiful_accounts', 'PARTIFUL_CREDENTIALS_KEY', ('refresh_token_enc', 'uid_enc')),
    'espn': ('espn_accounts', 'ESPN_CREDENTIALS_KEY', ('espn_s2_enc', 'swid_enc')),
}
LOOPBACK = {'127.0.0.1', 'localhost', '::1'}


class RotationError(Exception):
    pass


PAGE = 500  # well under PostgREST's max_rows, so a page is never silently truncated


def rotate(supabase, project: str, apply: bool) -> dict:
    """Re-encrypt every row of `project` and report what happened; never returns a credential.

    Each write is conditional on the row still holding the values read, so a
    token the app refreshed mid-rotation (already encrypted with the new key)
    is never overwritten with a stale one; such rows are listed under `changed`.
    """
    table, env_name, columns = PROJECTS[project]
    fernet = credentials_fernet(env_name, RotationError)
    seen, rotated, failed, changed, last_id = 0, 0, [], [], None
    while True:
        # Keyset pages (id > last seen), not offsets: a row deleted mid-run must not shift
        # an unvisited row out of the next page and leave it on the old key.
        query = supabase.table(table).select(','.join(('id',) + columns)).order('id').limit(PAGE)
        rows = (query.gt('id', last_id) if last_id is not None else query).execute().data or []
        for row in rows:
            try:
                changes = {column: fernet.rotate(row[column].encode()).decode()
                           for column in columns if row.get(column)}
            except InvalidToken:
                failed.append(row['id'])  # no listed key decrypts it; left untouched
                continue
            if not changes:
                continue
            if apply:
                query = supabase.table(table).update(changes).eq('id', row['id'])
                for column in changes:
                    query = query.eq(column, row[column])
                if not query.execute().data:
                    changed.append(row['id'])
                    continue
            rotated += 1
        seen += len(rows)
        if len(rows) < PAGE:
            break
        last_id = rows[-1]['id']
    return {'project': project, 'rows': seen, 'rotated': rotated, 'undecryptable': failed,
            'changed': changed, 'applied': apply}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('project', choices=sorted(PROJECTS))
    parser.add_argument('--apply', action='store_true', help='write the re-encrypted values (default: count only)')
    parser.add_argument('--host', help='required, and must match, when SUPABASE_URL is not loopback')
    args = parser.parse_args(argv)
    url, key = os.environ.get('SUPABASE_URL', ''), os.environ.get('SUPABASE_SERVICE_KEY', '')
    host = urlparse(url).hostname or ''
    if not url or not key:
        parser.error('SUPABASE_URL and SUPABASE_SERVICE_KEY are required')
    if host not in LOOPBACK and args.host != host:
        parser.error(f'SUPABASE_URL points at {host}; pass --host {host} to confirm')
    from supabase import create_client
    result = rotate(create_client(url, key), args.project, args.apply)
    print(result)
    return 1 if result['undecryptable'] or result['changed'] else 0


if __name__ == '__main__':
    sys.exit(main())
