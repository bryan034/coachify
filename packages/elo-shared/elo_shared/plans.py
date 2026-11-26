from collections.abc import Mapping
from typing import Literal

AccountType = Literal['free', 'premium']
PREMIUM_REQUIRED = 'premium_required'
FREE_ROADMAP_DETAIL_WEEKS = 2


def account_type(account: Mapping[str, object]) -> AccountType:
    return 'premium' if account.get('account_type') == 'premium' else 'free'
