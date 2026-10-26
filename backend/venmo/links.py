"""Public Venmo URLs with predictable percent-encoded notes."""
from urllib.parse import urlencode, quote
from .usernames import normalize_username


def required_handle(handle):
    value = normalize_username(handle)
    if not value:
        raise ValueError('Venmo handle required')
    return value


def profile_link(handle):
    return f'https://venmo.com/u/{required_handle(handle)}'


def transaction_link(handle, amount_minor, note, *, action='pay', reference=None):
    if action not in {'pay', 'charge'} or type(amount_minor) is not int or amount_minor <= 0:
        raise ValueError('Invalid transaction')
    note = f'{note} · {reference}' if reference else note
    params = urlencode(dict(txn=action, amount=f'{amount_minor // 100}.{amount_minor % 100:02d}', note=note), quote_via=quote)
    return f'https://venmo.com/{required_handle(handle)}?{params}'
