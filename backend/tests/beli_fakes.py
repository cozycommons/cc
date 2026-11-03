"""Synthetic Beli accounts and a fake Beli API for connector tests. No network."""
from secrets import token_urlsafe
from uuid import uuid4

from cryptography.fernet import Fernet

from ig_logger.accounts import hash_token
from ig_logger.sinks.beli import accounts

BISTRO = {'id': 501, 'name': 'Synthetic Bistro', 'neighborhood': 'West Village', 'city': 'New York',
          'cuisines': ['French'], 'price': 2, 'businesshours_set': [], 'reservation_platforms': {'resy': {}}}
TRENDING = {'id': 502, 'name': 'Synthetic Noodles', 'neighborhood': 'West Village', 'city': 'New York',
            'businesshours_set': []}


class FakeBeli:
    """One fake Beli login. Saves land in db.beli_writes, keyed by the login used."""

    def __init__(self, db, account):
        self.db, self.beli_id = db, account['beli_id']
        db.beli_logins.append(self.beli_id)

    def saved(self):
        return {write['business_id'] for login, write in self.db.beli_writes if login == self.beli_id}

    def api_with_reauth(self, path, method='GET', body=None):
        if self.db.beli_failure:
            raise self.db.beli_failure
        if path.startswith('/api/user/logged-in/'):
            return {'uuid': 'beli-' + self.beli_id}
        if path.startswith('/api/get-bookmark/'):
            return {'Restaurants': [{'business': BISTRO if bid == BISTRO['id'] else {'id': bid}}
                                    for bid in self.saved()]}
        if path.startswith('/api/get-ranking/'):
            return {'results': []}
        if path.startswith('/api/trending/'):
            return {'results': [{'business': BISTRO}, {'business': TRENDING}]}
        if path.startswith('/api/search-app/'):
            if 'Synthetic' not in path:
                return {'predictions': []}
            return {'predictions': [
                {'business': BISTRO['id'], 'structured_formatting':
                 {'main_text': BISTRO['name'], 'secondary_text': 'New York'}},
                {'business': 503, 'structured_formatting':
                 {'main_text': 'Synthetic Bakery', 'secondary_text': 'Brooklyn'}}]}
        if path.startswith('/api/business/?id='):
            bid = int(path.split('id=')[1])
            return [next((b for b in (BISTRO, TRENDING) if b['id'] == bid), {'id': bid, 'name': 'Synthetic Bakery'})]
        if path.startswith('/api/businesses-res-availability/'):
            return {'results': [{'business_id': BISTRO['id'], 'slots': ['19:00', '19:30']}]}
        if path.startswith('/api/add-bookmark/'):
            assert method == 'POST'
            self.db.beli_writes.append((self.beli_id, body))
            if self.db.beli_after_write:  # Beli took the write, but the response never arrived
                raise self.db.beli_after_write
            return None
        raise AssertionError(f'unexpected Beli path {path}')


def install(db, monkeypatch):
    """Encrypt synthetic logins with a throwaway key and route Beli calls to FakeBeli."""
    monkeypatch.setenv('BELI_CREDENTIALS_KEY', Fernet.generate_key().decode())
    db.beli_writes, db.beli_logins, db.beli_failure, db.beli_after_write = [], [], None, None
    monkeypatch.setattr('ig_logger.sinks.beli.accounts.make_client_for_account',
                        lambda account: FakeBeli(db, account))


def add_account(db, owner=None, label='synthetic'):
    """Add an onboarded Beli account and return (row, its plaintext ccb_ token)."""
    token = 'ccb_' + token_urlsafe(32)
    login = f'synthetic-{uuid4().hex[:8]}@example.test'
    row = {'id': str(uuid4()), 'label': label, 'beli_id_enc': accounts.encrypt_secret(login),
           'password_enc': accounts.encrypt_secret('synthetic-password'), 'token_hash': hash_token(token),
           'token_prefix': token[:12], 'watcher_opt_in': True, 'owner_user_id': owner, 'login': login}
    db.beli_accounts.append(row)
    return row, token
