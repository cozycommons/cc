"""Reuse canonical Dice display fields without creating game/profile records."""
import logging
from urllib.parse import urlparse

from gotrue.errors import AuthApiError

from .ledger import public_group
from .venmo import account_venmo, stored_username

logger = logging.getLogger(__name__)


def avatar_url(value):
    if not isinstance(value, str):
        return None
    if value.startswith('/') and not value.startswith('//'):
        return value
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    return value if parsed.scheme in {'http', 'https'} and parsed.netloc and not parsed.username else None


def profile_map(client, user_ids):
    ids = list(dict.fromkeys(user_id for user_id in user_ids if user_id))
    profiles = {}
    for start in range(0, len(ids), 100):
        rows = (client.table('dice_profiles').select('user_id,display_name,avatar_url')
                .in_('user_id', ids[start:start + 100]).execute().data)
        for row in rows:
            profiles[row['user_id']] = {'display_name': row['display_name'],
                                        'avatar_url': avatar_url(row.get('avatar_url'))}
    return profiles


def current_profile(client, user):
    existing = profile_map(client, [user.id]).get(user.id)
    account = account_profile(user)
    if existing:
        return {**account, **existing, 'profile_source': 'dice'}
    return account


def account_profile(user):
    metadata = user.user_metadata or {}
    name = metadata.get('full_name') or metadata.get('name') or 'Travel friend'
    return {'user_id': user.id, 'display_name': str(name)[:80],
            'avatar_url': avatar_url(metadata.get('avatar_url')), 'profile_source': 'account',
            **account_venmo(metadata)}


def linked_accounts(client, user_ids):
    """Read only accounts already linked to authorized trip rows; never search by name or email."""
    accounts = {}
    for user_id in dict.fromkeys(user_ids):
        try:
            user = client.auth.admin.get_user_by_id(user_id).user
        except AuthApiError as error:
            if error.status != 404:
                logger.warning('Trips profile lookup failed with status %s', error.status)
            continue  # A deleted or unreachable account keeps its historical ledger identity.
        except Exception:  # noqa: BLE001 - optional display data must never fail a committed write.
            logger.warning('Trips profile lookup failed', exc_info=True)
            continue
        if user and user.id == user_id:
            accounts[user_id] = account_profile(user)
    return accounts


def render_groups(client, rows):
    linked_ids = [member['user_id'] for row in rows for member in row['data']['members'] if member.get('user_id')]
    try:
        profiles = profile_map(client, linked_ids)
    except Exception:  # noqa: BLE001 - optional display data must never fail a committed write.
        logger.warning('Trips Dice profile lookup failed', exc_info=True)
        profiles = {}
    accounts = linked_accounts(client, linked_ids)
    results = []
    for row in rows:
        group = public_group(row)
        for member in group['members']:
            account = accounts.get(member.get('user_id'), {})
            profile = profiles.get(member.get('user_id')) or account
            member['display_name'] = profile.get('display_name') or member['name']
            member['avatar_url'] = profile.get('avatar_url')
            if member.get('user_id'):
                member['venmo_username'] = account.get('venmo_username')
                member['venmo_confirmed'] = account.get('venmo_confirmed', False)
                member['venmo_confirmed_name'] = account.get('venmo_confirmed_name')
                member['venmo_source'] = 'account' if member['venmo_username'] else None
            else:
                member['venmo_username'] = stored_username(member.get('venmo_username'))
                member['venmo_confirmed'] = False
                member['venmo_source'] = 'trip' if member['venmo_username'] else None
        results.append(group)
    return results


def render_group(client, row):
    return render_groups(client, [row])[0]
