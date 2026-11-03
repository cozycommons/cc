"""Commons profile: one row of cross-project identity per account (0087).

Visibility lives here so every reader selects the same fields:
- public: anyone who sees you in any project, signed out included.
- shared: people who share something with you; the caller proves that relationship.

The Commons avatar is shared, not public: for Dice players without a Dice photo the
0087 backfill stored their Google photo, which may appear only behind sign-in. Public
readers get the Dice avatar instead, which dice_profiles already serves to anyone.
"""
from datetime import datetime, timezone

from postgrest.exceptions import APIError

from trips.venmo import account_venmo

TABLE = 'commons_profiles'
FIELDS = {
    'display_name': 'public',
    'avatar_url': 'shared',
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
    """Commons name and Dice avatar (None without a Dice row or photo)."""
    profiles = _rows(client, PUBLIC_FIELDS, user_ids)
    ids = list(profiles)
    avatars = {}
    for start in range(0, len(ids), 100):
        rows = (client.table('dice_profiles').select('user_id,avatar_url')
                .in_('user_id', ids[start:start + 100]).execute().data)
        avatars.update((row['user_id'], row.get('avatar_url')) for row in rows)
    return {user_id: {**profile, 'avatar_url': avatars.get(user_id)} for user_id, profile in profiles.items()}


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
    try:
        client.table(TABLE).insert(row).execute()
    except APIError as error:
        if error.code != '23505':
            raise
        # A concurrent first request inserted first; keep whichever row won.
    return shared_profiles(client, [user.id])[str(user.id)]


def update_profile(client, user_id, changes, user=None) -> dict:
    """Write profile fields; the only writer of name and avatar (0087 mirrors them into dice_profiles).

    A user without a row yet (an account made since the backfill) first gets one from
    own_profile, so the update fires the Dice mirror. Pass ``user`` when the caller
    already holds the Auth user; otherwise it is read by ID.
    """
    if 'display_name' in changes and not _name(changes['display_name']):
        raise ValueError('display name cannot be blank')
    if 'avatar_url' in changes and changes['avatar_url'] is not None and _avatar(changes['avatar_url']) is None:
        raise ValueError(f'avatar URL must be at most {AVATAR_LIMIT} characters')
    write = {**changes, 'updated_at': datetime.now(timezone.utc).isoformat()}
    rows = client.table(TABLE).update(write).eq('user_id', str(user_id)).execute().data
    if not rows:
        own_profile(client, user or client.auth.admin.get_user_by_id(str(user_id)).user)
        rows = client.table(TABLE).update(write).eq('user_id', str(user_id)).execute().data
    return {name: rows[0].get(name) for name in SHARED_FIELDS}
