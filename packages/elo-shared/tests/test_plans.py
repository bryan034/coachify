import pytest

from elo_shared.plans import account_type


@pytest.mark.parametrize(('account', 'expected'), [
    ({'account_type': 'premium'}, 'premium'),
    ({'account_type': 'free'}, 'free'),
    ({'account_type': 'Premium'}, 'free'),
    ({'account_type': ' premium '}, 'free'),
    ({'account_type': True}, 'free'),
    ({}, 'free'),
])
def test_account_type_requires_exact_premium_value(account, expected):
    assert account_type(account) == expected
