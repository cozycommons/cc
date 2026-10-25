"""Trips confirmation provenance for account Venmo handles."""
from venmo.usernames import normalize_username, stored_username

def account_venmo(metadata):
    username = stored_username(metadata.get('venmo_username'))
    provenance = metadata.get('venmo_username_provenance')
    # Only a username the person saved themselves counts as theirs. This is never proof of Venmo ownership.
    confirmed = isinstance(provenance, dict) and provenance.get('owner_confirmed') is True
    return {'venmo_username': username, 'venmo_confirmed': bool(username) and confirmed,
            **({'venmo_confirmed_name': provenance['display_name']} if isinstance(provenance, dict) and provenance.get('display_name') else {})}
