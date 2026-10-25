"""Name-matching suggestions for linking trip members. Synthetic names only."""
import pytest

from trips.matching import name_score, suggest, tokens


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
        'flags': [], 'alternatives': []}
    assert rows['m4']['status'] == 'no match' and rows['m4']['user_id'] is None
    assert rows['m5']['status'] == 'no match'  # The owner's account already has a place.


def test_an_exact_lone_first_name_is_still_weak():
    rows = suggest([{'id': 'm', 'name': 'Riley', 'user_id': None}],
                   [{'user_id': 'u', 'names': ['Riley'], 'venmo_username': None}])
    assert (rows[0]['score'], rows[0]['flags']) == (1.0, ['weak'])
