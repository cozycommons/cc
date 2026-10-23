"""Venmo usernames are display data for preparing a payment, never identity or authorization."""
import re

USERNAME = re.compile(r'[A-Za-z0-9_-]{5,30}')
PREFIXES = re.compile(r'^(?:https?://)?(?:www\.|account\.)?venmo\.com/(?:u/)?', re.IGNORECASE)


def normalize_username(value):
    """Return a canonical username, None to clear, or raise ValueError with a user-facing message."""
    if value is None:
        return None
    text = PREFIXES.sub('', str(value).strip()).split('?')[0].strip('/').removeprefix('@').strip()
    if not text:
        return None
    if not USERNAME.fullmatch(text):
        raise ValueError('Use 5–30 letters, numbers, hyphens, or underscores, like @alex-smith.')
    return text


def stored_username(value):
    """Tolerate missing or malformed stored values without breaking a trip."""
    try:
        return normalize_username(value) if isinstance(value, str) else None
    except ValueError:
        return None


def account_venmo(metadata):
    username = stored_username(metadata.get('venmo_username'))
    provenance = metadata.get('venmo_username_provenance')
    # Only a username the person saved themselves counts as theirs. This is never proof of Venmo ownership.
    confirmed = isinstance(provenance, dict) and provenance.get('owner_confirmed') is True
    return {'venmo_username': username, 'venmo_confirmed': bool(username) and confirmed}
