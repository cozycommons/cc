"""Exact settlement checks against an independent payment-search oracle."""
from functools import lru_cache
import random
from time import perf_counter

import pytest

from trips.ledger import FEWEST_PAYMENTS_LIMIT, new_group, public_group, transfers


def amounts_for(values):
    return {f"member-{index}": value for index, value in enumerate(values)}


def assert_settles(amounts, payments):
    remaining = amounts.copy()
    for payment in payments:
        assert set(payment) == {'from_member', 'to_member', 'amount_minor'}
        sender, recipient, amount = (payment[key] for key in
                                     ('from_member', 'to_member', 'amount_minor'))
        assert amounts[sender] < 0 < amounts[recipient]
        assert type(amount) is int and amount > 0
        remaining[sender] += amount
        remaining[recipient] -= amount
    assert all(value == 0 for value in remaining.values())
    assert sum(payment['amount_minor'] for payment in payments) == sum(
        value for value in amounts.values() if value > 0)
    assert payments == transfers(amounts)


@lru_cache(maxsize=None)
def payment_oracle(state):
    """Enumerate debtor/creditor payments, independently of subset partition DP.

    An optimal support is a forest (a cycle can be cancelled). Removing a leaf
    exhausts at least one endpoint, so some sequence of these payments is optimal.
    """
    if not any(state):
        return 0
    lower_bound = max(sum(value < 0 for value in state), sum(value > 0 for value in state))
    best = len(state)
    for debtor, debt in enumerate(state):
        if debt >= 0:
            continue
        for creditor, credit in enumerate(state):
            if credit <= 0:
                continue
            amount = min(-debt, credit)
            after = list(state)
            after[debtor] += amount
            after[creditor] -= amount
            best = min(best, 1 + payment_oracle(tuple(after)))
            if best == lower_bound:
                return best
    return best


@pytest.mark.parametrize('seed', range(100))
def test_random_small_cases_match_payment_oracle(seed):
    rng = random.Random(seed)
    for size in range(2, 9):
        values = [rng.randint(-12, 12) for _ in range(size - 1)]
        values.append(-sum(values))
        rng.shuffle(values)
        amounts = amounts_for(values)
        original = amounts.copy()
        payments = transfers(amounts)
        assert len(payments) == payment_oracle(tuple(values)), (seed, values)
        assert_settles(amounts, payments)
        assert amounts == original
    payment_oracle.cache_clear()


@pytest.mark.parametrize('seed', range(100))
def test_zero_sum_subgroups_match_oracle(seed):
    rng = random.Random(seed)
    values = [5, -5, 3, -3, 7, -7, 0, 0]
    rng.shuffle(values)
    amounts = amounts_for(values)
    payments = transfers(amounts)
    assert len(payments) == payment_oracle(tuple(values)) == 3
    assert_settles(amounts, payments)
    payment_oracle.cache_clear()


def test_exact_solver_beats_member_order_greedy():
    amounts = {'a': -3, 'b': -2, 'c': 2, 'd': 3, 'zero': 0}
    assert transfers(amounts) == [
        {'from_member': 'a', 'to_member': 'd', 'amount_minor': 3},
        {'from_member': 'b', 'to_member': 'c', 'amount_minor': 2},
    ]


def test_ties_and_display_order_follow_member_insertion_order():
    # IDs deliberately sort in the reverse of insertion order.
    amounts = {'z': -5, 'y': -5, 'x': 5, 'w': 5}
    assert transfers(amounts) == [
        {'from_member': 'z', 'to_member': 'x', 'amount_minor': 5},
        {'from_member': 'y', 'to_member': 'w', 'amount_minor': 5},
    ]
    reversed_order = dict(reversed(list(amounts.items())))
    assert transfers(reversed_order) == [
        {'from_member': 'y', 'to_member': 'w', 'amount_minor': 5},
        {'from_member': 'z', 'to_member': 'x', 'amount_minor': 5},
    ]


def public_for(amounts):
    row = new_group('trip', 'owner', 'Trip', 'USD', 'Owner')
    row['data']['members'] = [{'id': key, 'name': key} for key in amounts]
    anchor = next(iter(amounts), None)
    row['data']['repayments'] = [
        {'from_member': key if value > 0 else anchor,
         'to_member': anchor if value > 0 else key, 'amount_minor': abs(value)}
        for key, value in amounts.items() if key != anchor and value
    ]
    return public_group(row)


@pytest.mark.parametrize('values', [
    [], [0, 0], [-5, 5],
    [1] * (FEWEST_PAYMENTS_LIMIT - 1) + [1 - FEWEST_PAYMENTS_LIMIT] + [0] * 10,
])
def test_public_mode_counts_only_nonzero_balances(values):
    amounts = amounts_for(values)
    group = public_for(amounts)
    assert group['settlement'] == 'fewest'
    assert group['balances'] == amounts
    assert_settles(amounts, group['transfers'])


def test_above_limit_uses_original_greedy_and_reports_it():
    # Exact would find two isolated pairs, but fallback keeps original matching.
    values = [-3, -2, 2, 3] + [1] * (FEWEST_PAYMENTS_LIMIT - 4)
    values.append(-sum(values))
    amounts = amounts_for(values)
    assert sum(value != 0 for value in values) == FEWEST_PAYMENTS_LIMIT + 1
    group = public_for(amounts)
    assert group['settlement'] == 'greedy'
    assert group['balances'] == amounts
    assert group['transfers'][:2] == [
        {'from_member': 'member-0', 'to_member': 'member-2', 'amount_minor': 2},
        {'from_member': 'member-0', 'to_member': 'member-3', 'amount_minor': 1},
    ]
    assert_settles(amounts, group['transfers'])


def test_worst_case_at_limit_stays_within_200ms():
    # Every shape visits all 2**limit masks and limit*2**(limit-1) edges.
    # Check both no proper zero-sum subset and many tied optimal partitions.
    powers = [2 ** index for index in range(FEWEST_PAYMENTS_LIMIT - 1)]
    cases = [
        [1] * (FEWEST_PAYMENTS_LIMIT - 1) + [1 - FEWEST_PAYMENTS_LIMIT],
        [1, -1] * (FEWEST_PAYMENTS_LIMIT // 2),
        powers + [-sum(powers)],
    ]
    timings = []
    for values in cases:
        amounts = amounts_for(values)
        samples = []
        for _ in range(3):
            start = perf_counter()
            payments = transfers(amounts)
            samples.append(perf_counter() - start)
        assert_settles(amounts, payments)
        # The fastest sample avoids failures from unrelated CI scheduling pauses.
        assert min(samples) < 0.2, samples
        timings.extend(samples)
    print(f"limit={FEWEST_PAYMENTS_LIMIT}; maximum of 9 samples={max(timings) * 1000:.1f} ms")
