"""own_profile creates the caller's row once and visibility selects the right fields."""
from types import SimpleNamespace

import pytest

from commons_account.profile import own_profile, public_profiles, shared_profiles


class Table:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.columns, self.row = db, name, {}, None, None

    def select(self, columns):
        self.columns = columns.split(',')
        return self

    def in_(self, key, values):
        self.filters[key] = set(values)
        return self

    def eq(self, key, value):
        self.filters[key] = {value}
        return self

    def limit(self, _):
        return self

    def upsert(self, row, on_conflict, ignore_duplicates):
        assert (on_conflict, ignore_duplicates) == ('user_id', True)
        self.row = row
        return self

    def execute(self):
        rows = self.db.setdefault(self.name, [])
        if self.row is not None:
            self.db['writes'] = self.db.get('writes', 0) + 1
            if not any(row['user_id'] == self.row['user_id'] for row in rows):
                rows.append(self.row)
            return SimpleNamespace(data=[])
        found = [row for row in rows if all(row.get(key) in values for key, values in self.filters.items())]
        return SimpleNamespace(data=[{name: row.get(name) for name in self.columns} for row in found])


class Client:
    def __init__(self, **tables):
        self.db = tables

    def table(self, name):
        return Table(self.db, name)


def account(**metadata):
    return SimpleNamespace(id='u1', email='sam@example.test', user_metadata=metadata, is_anonymous=False)


def test_first_call_creates_the_row_from_dice_then_reuses_it():
    client = Client(dice_profiles=[{'user_id': 'u1', 'display_name': 'Dice Sam', 'avatar_url': None}])
    user = account(full_name='Google Sam', avatar_url='https://google.example/s.png', venmo_username='Sam-Pays')
    created = own_profile(client, user)
    assert created == {'display_name': 'Dice Sam', 'avatar_url': 'https://google.example/s.png',
                       'venmo_username': 'sam-pays', 'venmo_owner_confirmed': False, 'venmo_confirmed_name': None}
    assert own_profile(client, account(full_name='Renamed in Google')) == created
    assert client.db['writes'] == 1


def test_anonymous_sessions_get_no_row():
    client = Client()
    with pytest.raises(ValueError):
        own_profile(client, SimpleNamespace(id='u1', email=None, user_metadata={}, is_anonymous=True))
    assert 'writes' not in client.db


def test_public_reads_never_include_shared_fields():
    client = Client(commons_profiles=[{'user_id': 'u1', 'display_name': 'Sam', 'avatar_url': None,
                                       'venmo_username': 'sam-pays', 'venmo_owner_confirmed': True,
                                       'venmo_confirmed_name': 'Sam P'}])
    assert public_profiles(client, ['u1', 'missing']) == {'u1': {'display_name': 'Sam', 'avatar_url': None}}
    assert shared_profiles(client, ['u1'])['u1']['venmo_username'] == 'sam-pays'
