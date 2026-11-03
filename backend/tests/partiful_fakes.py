"""Synthetic Partiful accounts and a fake Partiful API for connector tests. No network."""
from secrets import token_urlsafe
from uuid import uuid4

from cryptography.fernet import Fernet

from partiful import accounts
from partiful.partiful_client import PartifulError


def event(event_id, title, start='2026-11-14T20:00:00Z', **extra):
    return {'id': event_id, 'title': title, 'startDate': start, 'endDate': None, 'timezone': 'America/New_York',
            'location': 'Synthetic Loft', 'status': 'PUBLISHED', 'attendedGuestCount': 12,
            # Fields the connector must never return.
            'guests': [{'name': 'Synthetic Guest', 'phoneNumber': '+15555550100'}], **extra}


class FakePartiful:
    """One fake Partiful session. Reads are recorded in db.partiful_reads, keyed by the session's uid."""

    def __init__(self, db, account):
        self.db, self.uid = db, account['uid']
        db.partiful_logins.append(self.uid)

    def _events(self):
        if self.db.partiful_failure:
            raise self.db.partiful_failure
        return self.db.partiful_events.setdefault(self.uid, {'hosted': [], 'rsvps': []})

    def get_published_events(self):
        self.db.partiful_reads.append((self.uid, 'getPublishedEvents'))
        return self._events()['hosted']

    def get_my_rsvps(self):
        self.db.partiful_reads.append((self.uid, 'getMyRsvps'))
        return self._events()['rsvps']

    def get_event_info(self, event_id):
        self.db.partiful_reads.append((self.uid, 'getEventInfo'))
        events = self._events()
        found = next((e for e in events['hosted'] + events['rsvps'] if e['id'] == event_id), None)
        if found is None:  # Partiful shows only events this session may view
            raise PartifulError('Partiful getEventInfo -> 404', status=404)
        return {'event': found, 'passwordRequired': False}


def install(db, monkeypatch):
    """Encrypt synthetic sessions with a throwaway key and route Partiful calls to FakePartiful."""
    monkeypatch.setenv('PARTIFUL_CREDENTIALS_KEY', Fernet.generate_key().decode())
    db.partiful_logins, db.partiful_reads, db.partiful_events, db.partiful_failure = [], [], {}, None
    monkeypatch.setattr('partiful.accounts.make_client_for_account',
                        lambda supabase, account: FakePartiful(db, account))


def add_account(db, owner=None, label='synthetic'):
    """Add an onboarded Partiful account and return (row, its plaintext ccp_ token)."""
    token = 'ccp_' + token_urlsafe(32)
    uid = f'synthetic-uid-{uuid4().hex[:8]}'
    refresh = f'synthetic-refresh-{uuid4().hex}'
    row = {'id': str(uuid4()), 'label': label, 'refresh_token_enc': accounts.encrypt_secret(refresh),
           'uid_enc': accounts.encrypt_secret(uid), 'token_hash': accounts.hash_token(token),
           'token_prefix': token[:12], 'owner_user_id': owner, 'uid': uid, 'refresh_token': refresh}
    db.partiful_accounts.append(row)
    hosted = event(f'host{uid[-8:]}', f'Synthetic party hosted by {label}')
    invited = {**event(f'inv{uid[-8:]}', 'Synthetic dinner', start='2026-11-21T19:00:00Z'),
               'guest': {'status': 'GOING'}}
    db.partiful_events[uid] = {'hosted': [hosted], 'rsvps': [invited]}
    return row, token
