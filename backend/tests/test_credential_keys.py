"""Credential key rotation: comma-separated keys, and re-encrypting stored rows with the newest."""
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from credential_keys import credentials_fernet
from ig_logger.sinks.beli import accounts as beli_accounts
from resy import accounts as resy_accounts
from scripts import rotate_credentials


class Table:
    def __init__(self, rows):
        self.rows, self.updates, self.change, self.match = rows, [], None, None

    def select(self, *_):
        return self

    def update(self, change):
        self.change = change
        return self

    def eq(self, key, value):
        self.match = (key, value)
        return self

    def execute(self):
        if self.change is not None:
            for row in self.rows:
                if row[self.match[0]] == self.match[1]:
                    row.update(self.change)
            self.updates.append(self.change)
            self.change = None
        return SimpleNamespace(data=[dict(row) for row in self.rows])


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
    assert counted == {'project': 'resy', 'rows': 2, 'rotated': 1, 'undecryptable': ['r2'], 'applied': False}
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
