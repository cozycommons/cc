"""own_profile creates the caller's row once and visibility selects the right fields."""
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from commons_account.profile import own_profile, public_profiles, shared_profiles, update_profile


class Table:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.columns, self.row, self.changes = db, name, {}, None, None, None

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

    def insert(self, row):
        self.row = row
        return self

    def update(self, changes):
        self.changes = changes
        return self

    def execute(self):
        rows = self.db.setdefault(self.name, [])
        if self.row is not None:
            self.db['writes'] = self.db.get('writes', 0) + 1
            if any(row['user_id'] == self.row['user_id'] for row in rows):
                raise APIError({'code': '23505', 'message': 'duplicate key'})
            rows.append(self.row)
            return SimpleNamespace(data=[self.row])
        found = [row for row in rows if all(row.get(key) in values for key, values in self.filters.items())]
        if self.changes is not None:
            for row in found:
                row.update(self.changes)
            return SimpleNamespace(data=found)
        return SimpleNamespace(data=[{name: row.get(name) for name in self.columns} for row in found])


class Client:
    def __init__(self, accounts=(), **tables):
        self.db = tables
        users = {user.id: user for user in accounts}
        self.auth = SimpleNamespace(admin=SimpleNamespace(
            get_user_by_id=lambda user_id: SimpleNamespace(user=users[user_id])))

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
    google = 'https://google.example/sam.png'
    client = Client(commons_profiles=[
        {'user_id': 'u1', 'display_name': 'Sam', 'avatar_url': google, 'venmo_username': 'sam-pays',
         'venmo_owner_confirmed': True, 'venmo_confirmed_name': 'Sam P'},
        {'user_id': 'u2', 'display_name': 'Dee', 'avatar_url': 'https://dice.example/dee.png'},
    ], dice_profiles=[{'user_id': 'u2', 'avatar_url': 'https://dice.example/dee.png'}])
    # The Commons avatar (here a backfilled Google photo) is shared; public readers get the Dice one.
    assert public_profiles(client, ['u1', 'u2', 'missing']) == {
        'u1': {'display_name': 'Sam', 'avatar_url': None},
        'u2': {'display_name': 'Dee', 'avatar_url': 'https://dice.example/dee.png'},
    }
    shared = shared_profiles(client, ['u1'])['u1']
    assert (shared['venmo_username'], shared['avatar_url']) == ('sam-pays', google)


def test_a_lost_creation_race_keeps_the_winning_row(monkeypatch):
    client = Client(dice_profiles=[], commons_profiles=[])
    insert = Table.insert

    def racing_insert(self, row):  # Another request inserts between our read and our insert.
        self.db['commons_profiles'].append({**row, 'display_name': 'Winner'})
        return insert(self, row)
    monkeypatch.setattr(Table, 'insert', racing_insert)
    assert own_profile(client, account(full_name='Loser'))['display_name'] == 'Winner'


def test_update_creates_a_missing_row_from_the_account_then_writes():
    client = Client(accounts=[account(full_name='Google Sam')], dice_profiles=[], commons_profiles=[])
    saved = update_profile(client, 'u1', {'display_name': 'Sam Edited'})
    assert saved['display_name'] == 'Sam Edited'
    assert client.db['commons_profiles'][0]['display_name'] == 'Sam Edited'


@pytest.mark.parametrize('changes', [{'display_name': '   '}, {'avatar_url': 'https://x.test/' + 'a' * 2048}])
def test_update_rejects_values_the_table_would_refuse(changes):
    client = Client(commons_profiles=[{'user_id': 'u1', 'display_name': 'Sam'}])
    with pytest.raises(ValueError):
        update_profile(client, 'u1', changes)
    assert client.db['commons_profiles'] == [{'user_id': 'u1', 'display_name': 'Sam'}]
