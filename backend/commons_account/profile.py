"""Commons profile: one row of cross-project identity per account (0087).

Visibility lives here so every reader selects the same fields:
- public: anyone who sees you in any project.
- shared: people who share something with you; the caller proves that relationship.
"""
from trips.venmo import account_venmo

TABLE = 'commons_profiles'
FIELDS = {
    'display_name': 'public',
    'avatar_url': 'public',
    'venmo_username': 'shared',
    'venmo_owner_confirmed': 'shared',
    'venmo_confirmed_name': 'shared',
}
PUBLIC_FIELDS = tuple(name for name, visibility in FIELDS.items() if visibility == 'public')
SHARED_FIELDS = tuple(FIELDS)
NAME_LIMIT = 80
AVATAR_LIMIT = 2048


def _rows(client, fields, user_ids):
    ids = list(dict.fromkeys(str(user_id) for user_id in user_ids if user_id))
    profiles = {}
    for start in range(0, len(ids), 100):
        rows = (client.table(TABLE).select(','.join(('user_id', *fields)))
                .in_('user_id', ids[start:start + 100]).execute().data)
        for row in rows:
            profiles[row['user_id']] = {name: row.get(name) for name in fields}
    return profiles


def public_profiles(client, user_ids) -> dict[str, dict]:
    return _rows(client, PUBLIC_FIELDS, user_ids)


def shared_profiles(client, user_ids) -> dict[str, dict]:
    """Public and shared fields. Only call after proving the viewer shares something with each user."""
    return _rows(client, SHARED_FIELDS, user_ids)


def _name(value):
    text = value.strip(' ') if isinstance(value, str) else ''
    return text[:NAME_LIMIT].strip(' ') or None


def _avatar(value):
    return value if isinstance(value, str) and len(value) <= AVATAR_LIMIT else None


def default_profile(user, dice_row=None) -> dict:
    """First values for a new row; the same precedence as the 0087 backfill.

    Dice name first (as Trips shows today), then Google metadata, then the email
    local part. Venmo follows trips.venmo.account_venmo.
    """
    metadata = user.user_metadata or {}
    dice_row = dice_row or {}
    name = (_name(dice_row.get('display_name')) or _name(metadata.get('full_name'))
            or _name(metadata.get('name')) or _name((user.email or '').split('@')[0]) or 'Friend')
    avatar = _avatar(dice_row.get('avatar_url'))
    venmo = account_venmo(metadata)
    confirmed_name = venmo.get('venmo_confirmed_name')
    return {
        'user_id': str(user.id),
        'display_name': name,
        'avatar_url': avatar if avatar is not None else _avatar(metadata.get('avatar_url')),
        'venmo_username': venmo['venmo_username'].lower() if venmo['venmo_username'] else None,
        'venmo_owner_confirmed': venmo['venmo_confirmed'],
        'venmo_confirmed_name': confirmed_name if isinstance(confirmed_name, str) and confirmed_name else None,
    }


def own_profile(client, user) -> dict:
    """The caller's own profile with every field, creating the row on first use."""
    if getattr(user, 'is_anonymous', False):
        raise ValueError('Anonymous sessions have no Commons profile.')
    existing = shared_profiles(client, [user.id]).get(str(user.id))
    if existing:
        return existing
    dice_rows = (client.table('dice_profiles').select('display_name,avatar_url')
                 .eq('user_id', str(user.id)).limit(1).execute().data)
    row = default_profile(user, dice_rows[0] if dice_rows else None)
    # A concurrent first request may insert first; keep whichever row won.
    client.table(TABLE).upsert(row, on_conflict='user_id', ignore_duplicates=True).execute()
    return shared_profiles(client, [user.id])[str(user.id)]
