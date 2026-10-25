"""Name-matching suggestions for linking trip members. Synthetic names only."""
import pytest

from trips.matching import candidates_for, name_score, suggest, tokens


def test_tokens_ignore_case_accents_punctuation_and_spacing():
    assert tokens("  Zoë   O'Neil ") == ['zoe', 'oneil']
    assert tokens('jean-luc.picard') == ['jean', 'luc', 'picard']


@pytest.mark.parametrize('member, candidate, basis, minimum', [
    ('Matt Example', 'matt  example', 'exact', 1.0),
    ('Matt Example', 'Matthew Example', 'nickname+last', 0.95),
    ('Matthew E.', 'Matthew Example', 'first+initial', 0.85),
    ('Matt E', 'Matthew Example', 'nickname+initial', 0.85),
    ('Matt', 'Matthew Example', 'nickname', 0.65),
    ('Renée', 'Renee Sample', 'first name', 0.7),
])
def test_name_variants_score_as_suggestions(member, candidate, basis, minimum):
    score, found = name_score(member, candidate)
    assert found == basis and score >= minimum


def test_different_people_score_low():
    assert name_score('Matt Example', 'Matt Other')[0] < 0.6
    assert name_score('Jordan', 'Priya Sample')[0] < 0.6
    assert name_score('', 'Anyone') == (0.0, None)


def test_suggestions_flag_ambiguity_skip_linked_accounts_and_report_venmo():
    members = [{'id': 'm1', 'name': 'Owner', 'user_id': 'u-owner'},
               {'id': 'm2', 'name': 'Sam', 'user_id': None},
               {'id': 'm3', 'name': 'Riley Sample', 'user_id': None},
               {'id': 'm4', 'name': 'Nobody Known', 'user_id': None},
               {'id': 'm5', 'name': 'Owner Person', 'user_id': None}]
    accounts = [{'user_id': 'u-owner', 'names': ['Owner Person'], 'venmo_username': 'owner-v'},
                {'user_id': 'u-sam1', 'names': ['Samuel Example'], 'venmo_username': None},
                {'user_id': 'u-sam2', 'names': ['Samantha Other'], 'venmo_username': None},
                {'user_id': 'u-riley', 'names': ['Dice Nick', 'Riley Sample'], 'venmo_username': 'riley-v'}]
    rows = {row['member_id']: row for row in suggest(members, accounts)}
    assert 'm1' not in rows  # Already linked places aren't offered.
    assert rows['m2']['status'] == 'suggested' and rows['m2']['flags'] == ['ambiguous', 'weak']
    assert rows['m3'] | {'alternatives': []} == {
        'member_id': 'm3', 'member_name': 'Riley Sample', 'status': 'suggested', 'user_id': 'u-riley',
        'account_name': 'Riley Sample', 'score': 1.0, 'basis': 'exact', 'venmo_username': 'riley-v',
        'avatar_url': None, 'lookalike': False, 'flags': [], 'alternatives': []}
    assert rows['m4']['status'] == 'no match' and rows['m4']['user_id'] is None
    assert rows['m5']['status'] == 'no match'  # The owner's account already has a place.


def test_an_exact_lone_first_name_is_still_weak():
    rows = suggest([{'id': 'm', 'name': 'Riley', 'user_id': None}],
                   [{'user_id': 'u', 'names': ['Riley'], 'venmo_username': None}])
    assert (rows[0]['score'], rows[0]['flags']) == (1.0, ['weak'])


def test_lookalikes_are_flagged_across_every_candidate_even_hidden_ones():
    members = [{'id': 'm1', 'name': 'Alex Smith', 'user_id': None}]
    # Same name throughout; only Venmo tells the first three apart. Avatars don't count: two URLs can show one picture.
    looks = [('Alex Smith', '/a.png', 'alex-a'), ('Alex Smith', None, 'alex-s'), ('Alex Smith', '/b.png', 'alex-b'),
             ('Alex Smith', '/c.png#one', None), ('Alex  smith', '/c.png#two', None)]
    accounts = [{'user_id': f'u{i}', 'names': [name], 'avatar_url': avatar, 'venmo_username': venmo}
                for i, (name, avatar, venmo) in enumerate(looks)]
    row = suggest(members, accounts)[0]
    shown = [row, *row['alternatives']]
    assert len(shown) == 4  # The fifth account is not displayed...
    assert {c['user_id']: c['lookalike'] for c in shown} == {'u0': False, 'u1': False, 'u2': False, 'u3': True}  # ...but its twin blocks linking.
    assert {c['user_id']: c['lookalike'] for c in candidates_for(members[0], members, accounts)}['u4'] is True
    assert 'email_hint' not in row
