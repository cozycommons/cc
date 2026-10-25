"""Read-only suggestions for linking trip members to accounts. Never writes; a person confirms each link."""
from collections import Counter
from difflib import SequenceMatcher
import re
import unicodedata

from .profiles import profile_map
from .venmo import account_venmo

# Common English nicknames, both directions. A match on these is a suggestion, never evidence.
NICKNAMES = [
    {'matt', 'matthew', 'matty'}, {'alex', 'alexander', 'alexandra', 'alexis', 'xander'},
    {'andy', 'andrew', 'drew'}, {'ben', 'benjamin', 'benny'}, {'bill', 'will', 'william', 'liam', 'billy'},
    {'bob', 'rob', 'robert', 'bobby', 'robbie'}, {'chris', 'christopher', 'christine', 'christina'},
    {'dan', 'daniel', 'danny'}, {'dave', 'david'}, {'ed', 'edward', 'eddie', 'ted'},
    {'jim', 'james', 'jimmy', 'jamie'}, {'jen', 'jenny', 'jennifer'}, {'joe', 'joseph', 'joey'},
    {'jon', 'jonathan', 'john', 'johnny'}, {'josh', 'joshua'}, {'kate', 'katie', 'katherine', 'kathryn', 'kat'},
    {'liz', 'beth', 'elizabeth', 'eliza', 'lizzie'}, {'mike', 'michael', 'mikey'}, {'nick', 'nicholas'},
    {'pat', 'patrick', 'patricia'}, {'sam', 'samuel', 'samantha', 'sammy'}, {'steve', 'steven', 'stephen'},
    {'tom', 'thomas', 'tommy'}, {'tony', 'anthony'}, {'zach', 'zack', 'zachary'}, {'jake', 'jacob'},
    {'nate', 'nathan', 'nathaniel'}, {'abby', 'abigail'}, {'becca', 'rebecca'}, {'vicky', 'victoria'},
]
NICKNAME_GROUPS = {name: group for group in NICKNAMES for name in group}

AMBIGUOUS_MARGIN = 0.1
SUGGEST_THRESHOLD = 0.6
CANDIDATE_FLOOR = 0.4


def tokens(name):
    """Casefold, strip accents and punctuation: 'Zoë  O'Neil' -> ['zoe', 'oneil']."""
    plain = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().casefold()
    return re.sub(r"[^a-z0-9 ]", '', re.sub(r'[\s._-]+', ' ', plain)).split()


def same_first(a, b):
    return a == b or b in NICKNAME_GROUPS.get(a, ())


def name_score(member_name, candidate_name):
    """Return (score, basis) for one member name against one candidate name."""
    a, b = tokens(member_name), tokens(candidate_name)
    if not a or not b:
        return 0.0, None
    if a == b:
        return 1.0, 'exact'
    first, last = a[0], a[-1] if len(a) > 1 else None
    other_first, other_last = b[0], b[-1] if len(b) > 1 else None
    if same_first(first, other_first):
        if last and other_last:
            if last == other_last:
                return 0.95, 'first+last' if first == other_first else 'nickname+last'
            if len(last) == 1 and other_last.startswith(last) or len(other_last) == 1 and last.startswith(other_last):
                return 0.85, 'first+initial' if first == other_first else 'nickname+initial'
            return 0.4, 'first only, different last'
        return (0.7, 'first name') if first == other_first else (0.65, 'nickname')
    ratio = SequenceMatcher(None, ' '.join(a), ' '.join(b)).ratio()
    return round(ratio * 0.7, 2), 'similar spelling'


def suggest(members, accounts):
    """members: [{id, name, user_id}]; accounts: [{user_id, names, venmo_username}]. One review row per unlinked member."""
    linked = {m['user_id'] for m in members if m.get('user_id')}
    rows = []
    for member in members:
        if member.get('user_id'):
            continue
        scored = []
        for account in accounts:
            if account['user_id'] in linked:
                continue  # Linking refuses an account that already has a place.
            score, basis, matched = max(((*name_score(member['name'], name), name) for name in account['names']),
                                        key=lambda item: item[0], default=(0.0, None, None))
            if score >= CANDIDATE_FLOOR:
                scored.append({'user_id': account['user_id'], 'account_name': matched, 'score': score, 'basis': basis,
                               'venmo_username': account.get('venmo_username')})
        scored.sort(key=lambda item: -item['score'])
        best = scored[0] if scored and scored[0]['score'] >= SUGGEST_THRESHOLD else None
        flags = []
        if best and len(scored) > 1 and scored[1]['score'] >= best['score'] - AMBIGUOUS_MARGIN:
            flags.append('ambiguous')
        if best and (best['score'] < 0.9 or len(tokens(member['name'])) < 2):
            flags.append('weak')  # A lone first name matches many people, even exactly.
        rows.append({'member_id': member['id'], 'member_name': member['name'],
                     'status': 'suggested' if best else 'no match', **(best or {
                         'user_id': None, 'account_name': None, 'score': None, 'basis': None, 'venmo_username': None}),
                     'flags': flags, 'alternatives': scored[1:4] if best else scored[:3]})
    counts = Counter(row['user_id'] for row in rows if row['status'] == 'suggested')
    for row in rows:
        if row['status'] == 'suggested' and counts[row['user_id']] > 1:
            row['flags'].append('same account suggested twice')
    return rows


def read_accounts(client):
    """Read-only: Auth users plus their Dice display names."""
    users, page = [], 1
    while True:
        batch = client.auth.admin.list_users(page=page, per_page=1000)
        users += batch
        if len(batch) < 1000:
            break
        page += 1
    dice = profile_map(client, [user.id for user in users])
    accounts = []
    for user in users:
        metadata = user.user_metadata or {}
        names = [dice.get(user.id, {}).get('display_name'), metadata.get('full_name'), metadata.get('name')]
        accounts.append({'user_id': user.id, 'names': list(dict.fromkeys(n for n in names if isinstance(n, str) and n)),
                         'venmo_username': account_venmo(metadata)['venmo_username']})
    return accounts
