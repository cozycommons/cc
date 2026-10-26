import pytest
from venmo.links import transaction_link, profile_link

@pytest.mark.parametrize('action', ['pay', 'charge'])
def test_exact_links(action):
    assert transaction_link('alex-rivera', 1234, 'Cozy Trips dinner', action=action) == f'https://venmo.com/alex-rivera?txn={action}&amount=12.34&note=Cozy%20Trips%20dinner'
    assert transaction_link('alex-rivera', 1234, 'Cozy Trips · Lake', action=action, reference='CZ-4F2K') == f'https://venmo.com/alex-rivera?txn={action}&amount=12.34&note=Cozy%20Trips%20%C2%B7%20Lake%20%C2%B7%20CZ-4F2K'
    assert profile_link('alex-rivera') == 'https://venmo.com/u/alex-rivera'
