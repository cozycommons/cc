"""Credential key rotation: comma-separated keys, and re-encrypting stored rows with the newest."""
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from credential_keys import credentials_fernet
from ig_logger.sinks.beli import accounts as beli_accounts
from espn import accounts as espn_accounts
from partiful import accounts as partiful_accounts
from resy import accounts as resy_accounts
from scripts import rotate_credentials


class Table:
    """A table fake with the calls rotation makes: paged reads and conditional updates."""

    def __init__(self, rows):
        self.rows, self.updates, self.change, self.filters = rows, [], None, []
        self.after, self.size, self.reads = None, None, 0

    def select(self, *_):
        return self

    def order(self, _):
        return self

    def limit(self, size):
        self.after, self.size = None, size
        return self

    def gt(self, key, value):
        assert key == 'id'
        self.after = value
        return self

    def update(self, change):
        self.change, self.filters = change, []
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def execute(self):
        if self.change is not None:
            matched = [r for r in self.rows if all(r[k] == v for k, v in self.filters)]
            for row in matched:
                row.update(self.change)
            self.updates.append(self.change)
            self.change = None
            return SimpleNamespace(data=[dict(r) for r in matched])
        self.reads += 1
        page = sorted((r for r in self.rows if self.after is None or r['id'] > self.after), key=lambda r: r['id'])
        return SimpleNamespace(data=[dict(r) for r in page[:self.size]])


def test_first_key_encrypts_and_every_key_decrypts(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv('BELI_CREDENTIALS_KEY', old)
    stored = beli_accounts.encrypt_secret('synthetic-password')
    monkeypatch.setenv('BELI_CREDENTIALS_KEY', f'{new}, {old}')
    assert beli_accounts.decrypt_secret(stored) == 'synthetic-password'
    assert Fernet(new.encode()).decrypt(beli_accounts.encrypt_secret('x').encode()) == b'x'


def test_missing_or_malformed_keys_name_the_variable_not_the_value(monkeypatch):
    monkeypatch.setenv('RESY_CREDENTIALS_KEY', ' , ')
    with pytest.raises(resy_accounts.AccountError, match='RESY_CREDENTIALS_KEY is not set'):
        resy_accounts.encrypt_secret('x')
    monkeypatch.setenv('RESY_CREDENTIALS_KEY', 'not-a-key-secret-value')
    with pytest.raises(resy_accounts.AccountError, match='RESY_CREDENTIALS_KEY is invalid') as error:
        credentials_fernet('RESY_CREDENTIALS_KEY', resy_accounts.AccountError)
    assert 'not-a-key-secret-value' not in str(error.value)


def test_rotation_reencrypts_rows_so_the_old_key_can_be_dropped(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv('RESY_CREDENTIALS_KEY', old)
    rows = [{'id': 'r1', 'email_enc': resy_accounts.encrypt_secret('sam@example.test'),
             'password_enc': resy_accounts.encrypt_secret('synthetic'), 'auth_token_enc': ''},
            {'id': 'r2', 'email_enc': 'garbage', 'password_enc': 'garbage', 'auth_token_enc': ''}]
    table = Table(rows)
    db = SimpleNamespace(table=lambda name: table)
    monkeypatch.setenv('RESY_CREDENTIALS_KEY', f'{new},{old}')

    counted = rotate_credentials.rotate(db, 'resy', apply=False)
    assert counted == {'project': 'resy', 'rows': 2, 'rotated': 1, 'undecryptable': ['r2'], 'changed': [],
                       'applied': False}
    assert table.updates == []

    assert rotate_credentials.rotate(db, 'resy', apply=True)['rotated'] == 1
    monkeypatch.setenv('RESY_CREDENTIALS_KEY', new)  # old key dropped
    assert resy_accounts.decrypt_secret(rows[0]['email_enc']) == 'sam@example.test'
    assert rows[0]['auth_token_enc'] == '' and rows[1]['email_enc'] == 'garbage'


def test_rotation_refuses_a_remote_database_unless_named(monkeypatch, capsys):
    monkeypatch.setenv('SUPABASE_URL', 'https://db.example.supabase.co')
    monkeypatch.setenv('SUPABASE_SERVICE_KEY', 'synthetic')
    with pytest.raises(SystemExit):
        rotate_credentials.main(['beli'])
    assert 'pass --host db.example.supabase.co' in capsys.readouterr().err


def test_rotation_pages_past_one_page_and_never_overwrites_a_concurrent_refresh(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv('PARTIFUL_CREDENTIALS_KEY', old)
    monkeypatch.setattr(rotate_credentials, 'PAGE', 2)
    rows = [{'id': f'p{i}', 'refresh_token_enc': partiful_accounts.encrypt_secret(f'token-{i}'),
             'uid_enc': partiful_accounts.encrypt_secret('uid')} for i in range(5)]
    table = Table(rows)
    db = SimpleNamespace(table=lambda name: table)
    monkeypatch.setenv('PARTIFUL_CREDENTIALS_KEY', f'{new},{old}')
    fresh = partiful_accounts.encrypt_secret('token-refreshed')
    real_execute = table.execute

    def app_refreshes_p3_after_it_is_read():  # the app saves a new token between rotation's read and write
        result = real_execute()
        if table.change is None and table.reads == 2 and rows[3]['refresh_token_enc'] != fresh:
            rows[3]['refresh_token_enc'] = fresh
        return result
    table.execute = app_refreshes_p3_after_it_is_read

    result = rotate_credentials.rotate(db, 'partiful', apply=True)
    assert result['rows'] == 5 and result['rotated'] == 4 and result['changed'] == ['p3']
    monkeypatch.setenv('PARTIFUL_CREDENTIALS_KEY', new)
    assert partiful_accounts.decrypt_secret(rows[3]['refresh_token_enc']) == 'token-refreshed'
    assert partiful_accounts.decrypt_secret(rows[4]['refresh_token_enc']) == 'token-4'


def test_a_row_deleted_mid_rotation_does_not_strand_a_later_row_on_the_old_key(monkeypatch):
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv('ESPN_CREDENTIALS_KEY', old)
    monkeypatch.setattr(rotate_credentials, 'PAGE', 2)
    rows = [{'id': f'e{i}', 'espn_s2_enc': espn_accounts.encrypt_secret(f's2-{i}'),
             'swid_enc': espn_accounts.encrypt_secret('swid')} for i in range(3)]
    table = Table(rows)
    db = SimpleNamespace(table=lambda name: table)
    monkeypatch.setenv('ESPN_CREDENTIALS_KEY', f'{new},{old}')
    real_execute = table.execute

    def user_deletes_e0_after_the_first_page():  # DELETE /espn/account between pages
        if table.change is None and table.reads == 1 and rows[0]['id'] == 'e0':
            del rows[0]  # e0 was already rotated; under offsets this pushed e2 out of page two
        return real_execute()
    table.execute = user_deletes_e0_after_the_first_page

    result = rotate_credentials.rotate(db, 'espn', apply=True)
    assert result['rotated'] == 3 and result['changed'] == [] and result['undecryptable'] == []
    assert [r['id'] for r in rows] == ['e1', 'e2']
    monkeypatch.setenv('ESPN_CREDENTIALS_KEY', new)
    assert espn_accounts.decrypt_secret(next(r for r in rows if r['id'] == 'e2')['espn_s2_enc']) == 's2-2'
