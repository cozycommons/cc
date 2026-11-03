"""Show linked people by their Commons profile (0087), falling back to Auth metadata without a row."""
import logging
from urllib.parse import urlparse

from gotrue.errors import AuthApiError

from commons_account.profile import own_profile, shared_profiles
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


def trips_profile(profile):
    """A Commons profile with shared fields, in the shape Trips has always returned."""
    confirmed_name = profile.get('venmo_confirmed_name')
    return {'display_name': profile['display_name'], 'avatar_url': avatar_url(profile['avatar_url']),
            'venmo_username': profile['venmo_username'],
            'venmo_confirmed': bool(profile['venmo_username'] and profile['venmo_owner_confirmed']),
            **({'venmo_confirmed_name': confirmed_name} if confirmed_name else {})}


def current_profile(client, user):
    """The caller's own profile, creating their Commons row on first use."""
    if getattr(user, 'is_anonymous', False):
        return account_profile(user)  # Anonymous sessions have no Commons profile.
    return {'user_id': user.id, **trips_profile(own_profile(client, user)), 'profile_source': 'commons'}


def stored_profile(client, user):
    """Read-only: the caller's Commons profile, or the Auth metadata fallback when there is no row yet."""
    existing = shared_profiles(client, [user.id]).get(str(user.id))
    if existing:
        return {'user_id': user.id, **trips_profile(existing), 'profile_source': 'commons'}
    return account_profile(user)


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
    """Callers pass only trips the viewer belongs to, which is what lets co-members see shared fields."""
    linked_ids = [member['user_id'] for row in rows for member in row['data']['members'] if member.get('user_id')]
    try:
        profiles = {user_id: trips_profile(profile) for user_id, profile in shared_profiles(client, linked_ids).items()}
    except Exception:  # noqa: BLE001 - optional display data must never fail a committed write.
        logger.warning('Trips Commons profile lookup failed', exc_info=True)
        profiles = {}
    profiles.update(linked_accounts(client, [user_id for user_id in linked_ids if user_id not in profiles]))
    results = []
    for row in rows:
        group = public_group(row)
        for member in group['members']:
            profile = profiles.get(member.get('user_id'), {})
            member['display_name'] = profile.get('display_name') or member['name']
            member['avatar_url'] = profile.get('avatar_url')
            if member.get('user_id'):
                member['venmo_username'] = profile.get('venmo_username')
                member['venmo_confirmed'] = profile.get('venmo_confirmed', False)
                member['venmo_confirmed_name'] = profile.get('venmo_confirmed_name')
                member['venmo_source'] = 'account' if member['venmo_username'] else None
            else:
                member['venmo_username'] = stored_username(member.get('venmo_username'))
                member['venmo_confirmed'] = False
                member['venmo_source'] = 'trip' if member['venmo_username'] else None
        results.append(group)
    return results


def render_group(client, row):
    return render_groups(client, [row])[0]
