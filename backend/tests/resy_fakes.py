"""Synthetic Resy accounts and a fake Resy API for connector tests. No network."""
from datetime import date, datetime, timedelta, timezone
from itertools import count
from secrets import token_urlsafe
from uuid import uuid4

from cryptography.fernet import Fernet

from resy import accounts

VENUE_ID = 7001
VENUE = {'id': {'resy': VENUE_ID}, 'name': 'Synthetic Trattoria', 'type': 'Italian', 'price_range': 3,
         'rating': 4.7, 'url_slug': 'synthetic-trattoria',
         'location': {'neighborhood': 'West Village', 'locality': 'New York'}}
POLICY = ['Cancel at least 24 hours ahead to avoid the fee.', 'No-shows are charged the full fee.']
_ids = count(9000)


def day(offset=7):
    return (date.today() + timedelta(days=offset)).isoformat()


def slot_token(when, clock, kind):
    return f'rgs://resy/{VENUE_ID}/1/2/{when}/{when}/{clock}:00/2/{kind}'


class FakeResy:
    """One fake Resy login. Bookings land in db.resy_reservations, keyed by the login used.

    db.resy_sends counts every booking or cancellation request; db.resy_writes only
    those Resy recorded. resy_after_write: Resy recorded it, then the answer was lost.
    resy_lost_write: the request failed and Resy never recorded it.
    """

    def __init__(self, db, account):
        self.db, self.login = db, account['email']
        db.resy_logins.append(self.login)

    def read(self):
        if self.db.resy_failure:
            raise self.db.resy_failure

    def slots(self, when, party_size):
        self.read()
        fees, taken = self.db.resy_fees, {r['slot_token'] for rows in self.db.resy_reservations.values() for r in rows}
        offered = [
            {'config': {'token': slot_token(when, '19:00', 'Dining Room'), 'type': 'Dining Room'},
             'date': {'start': f'{when} 19:00:00', 'end': f'{when} 21:00:00'},
             'payment': {'deposit_fee': fees['deposit'], 'cancellation_fee': fees['cancellation_fee']}},
            {'config': {'token': slot_token(when, '21:00', 'Dining Room'), 'type': 'Dining Room'},
             'date': {'start': f'{when} 21:00:00', 'end': f'{when} 23:00:00'}, 'payment': {}},
            {'config': {'token': slot_token(when, '21:00', 'Bar'), 'type': 'Bar'},
             'date': {'start': f'{when} 21:00:00', 'end': f'{when} 22:30:00'}, 'payment': {}},
        ]
        return [slot for slot in offered if slot['config']['token'] not in taken]

    def search(self, query, lat, lng, when, party_size):
        self.read()
        return [{'venue': VENUE, 'slots': self.slots(when, party_size)}] if 'trattoria' in query.lower() else []

    def find_slots(self, venue_id, when, party_size):
        return self.slots(when, party_size) if venue_id == VENUE_ID else []

    def get_venue(self, venue_id):
        self.read()
        return VENUE if venue_id == VENUE_ID else None

    def get_user(self):
        self.read()
        return {'first_name': 'Synthetic', 'payment_methods': self.db.resy_cards[self.login]}

    def get_book_details(self, token, when, party_size):
        slot = next(s for s in self.slots(when, party_size) if s['config']['token'] == token)
        if slot['payment']:
            fees = self.db.resy_fees
            return {'book_token': {'value': 'bt:' + token}, 'venue': {'name': VENUE['name']},
                    'locale': {'currency': 'USD'},
                    'payment': {'config': {'type': 'deposit'}, 'amounts': {'total': fees['deposit']}},
                    'cancellation': {'fee': {'amount': fees['cancellation_fee'], 'date_cut_off': fees['cut_off']},
                                     'display': {'policy': fees['policy']}}}
        return {'book_token': {'value': 'bt:' + token}, 'venue': {'name': VENUE['name']},
                'payment': {'config': {'type': 'free'}, 'amounts': {'total': 0.0}}, 'cancellation': {}}

    def get_reservations(self):
        self.read()
        return [{'reservation': dict(r), 'venue': {'name': VENUE['name']}}
                for r in self.db.resy_reservations.get(self.login, [])]

    def send(self, kind, write):
        self.db.resy_sends.append((kind, self.login))
        if self.db.resy_lost_write:
            raise self.db.resy_lost_write
        result = write()
        self.db.resy_writes.append((kind, self.login))
        if self.db.resy_after_write:
            raise self.db.resy_after_write
        return result

    def book(self, book_token, payment_method_id):
        assert payment_method_id in {card['id'] for card in self.db.resy_cards[self.login]}
        token = book_token.removeprefix('bt:')
        parts = token.split('/')  # rgs: '' resy venue 1 2 day day HH:MM:SS seats type
        when, clock = parts[6], parts[8][:5]

        def write():
            reservation = add_reservation(self.db, self.login, when, clock, slot=token,
                                          fee=self.db.resy_fees['cancellation_fee'] if clock == '19:00' else None)
            return {'resy_token': reservation['resy_token'], 'reservation_id': reservation['reservation_id']}
        return self.send('book', write)

    def cancel(self, resy_token):
        rows = self.db.resy_reservations.get(self.login, [])
        assert any(r['resy_token'] == resy_token for r in rows), "never another login's reservation"

        def write():
            rows[:] = [r for r in rows if r['resy_token'] != resy_token]
            return {'payment': {}}
        return self.send('cancel', write)


def install(db, monkeypatch):
    """Encrypt synthetic logins with a throwaway key and route Resy calls to FakeResy."""
    monkeypatch.setenv('RESY_CREDENTIALS_KEY', Fernet.generate_key().decode())
    db.resy_logins, db.resy_sends, db.resy_writes, db.resy_cards, db.resy_reservations = [], [], [], {}, {}
    db.resy_failure = db.resy_after_write = db.resy_lost_write = None
    cut_off = (datetime.now(timezone.utc) + timedelta(days=5)).replace(microsecond=0).isoformat()
    db.resy_fees = {'deposit': 25.0, 'cancellation_fee': 50.0, 'cut_off': cut_off, 'policy': list(POLICY)}
    monkeypatch.setattr('resy.accounts.make_client_for_account', lambda supabase, account: FakeResy(db, account))


def add_account(db, owner=None, label='synthetic'):
    """Add an onboarded Resy account with two saved cards; return (row, its plaintext ccr_ token)."""
    token = 'ccr_' + token_urlsafe(32)
    email = f'synthetic-{uuid4().hex[:8]}@example.test'
    row = {'id': str(uuid4()), 'label': label, 'email_enc': accounts.encrypt_secret(email),
           'password_enc': accounts.encrypt_secret('synthetic-password'),
           'auth_token_enc': accounts.encrypt_secret('synthetic-auth'), 'token_hash': accounts.hash_token(token),
           'token_prefix': token[:12], 'owner_user_id': owner, 'email': email}
    db.resy_accounts.append(row)
    db.resy_cards[email] = [{'id': next(_ids), 'brand': 'visa', 'last_four': '4242', 'is_default': True},
                            {'id': next(_ids), 'brand': 'amex', 'last_four': '1005', 'is_default': False}]
    return row, token


def add_reservation(db, login, when=None, clock='19:00', slot=None, fee=50.0, allowed=True):
    reservation = {
        'reservation_id': next(_ids), 'resy_token': f'rr://{uuid4().hex}', 'day': when or day(),
        'time_slot': f'{clock}:00', 'num_seats': 2, 'venue': {'id': VENUE_ID}, 'slot_token': slot,
        'cancellation': {'allowed': allowed, **({'fee': {'amount': fee, 'date_cut_off': db.resy_fees['cut_off']}}
                                                if fee is not None else {})},
        'cancellation_policy': list(db.resy_fees['policy']) if fee is not None else [],
        'status': {'finished': 0, 'no_show': 0}}
    db.resy_reservations.setdefault(login, []).append(reservation)
    return reservation
