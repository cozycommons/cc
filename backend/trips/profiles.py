"""Reuse canonical Dice display fields without creating game/profile records."""
from urllib.parse import urlparse

from gotrue.errors import AuthApiError

from .ledger import public_group


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
    if existing:
        return {'user_id': user.id, **existing, 'profile_source': 'dice'}
    return account_profile(user)


def account_profile(user):
    metadata = user.user_metadata or {}
    name = metadata.get('full_name') or metadata.get('name') or 'Travel friend'
    return {'user_id': user.id, 'display_name': str(name)[:80],
            'avatar_url': avatar_url(metadata.get('avatar_url')), 'profile_source': 'account'}


def render_groups(client, rows):
    # Only resolve IDs already attached to authorized trip rows, never names or emails.
    profiles = profile_map(client, [member.get('user_id') for row in rows for member in row['data']['members']])
    linked_ids = dict.fromkeys(member.get('user_id') for row in rows for member in row['data']['members'] if member.get('user_id'))
    # Resolve each authorized linked identity once, without creating a Dice profile.
    for user_id in linked_ids:
        if user_id in profiles:
            continue
        try:
            user = client.auth.admin.get_user_by_id(user_id).user
        except AuthApiError as error:
            if error.status == 404:
                continue  # A deleted account still retains its historical ledger identity.
            raise
        if user and user.id == user_id:
            profiles[user_id] = account_profile(user)
    results = []
    for row in rows:
        group = public_group(row)
        for member in group['members']:
            profile = profiles.get(member.get('user_id'), {})
            member['display_name'] = profile.get('display_name') or member['name']
            member['avatar_url'] = profile.get('avatar_url')
        results.append(group)
    return results


def render_group(client, row):
    return render_groups(client, [row])[0]
