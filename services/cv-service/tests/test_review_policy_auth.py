from types import SimpleNamespace

import anyio
import httpx
import pytest
from fastapi import HTTPException

from app.core.auth import current_account


def account_from_profile(session):
    async def exercise():
        async def transport(request):
            if request.url.path.endswith('/auth/session'):
                return httpx.Response(200, json=session)
            return httpx.Response(200, json={'onboarding_complete': True, 'version': 4})

        async with httpx.AsyncClient(transport=httpx.MockTransport(transport), base_url='http://profile') as client:
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(profile_client=client)))
            return await current_account(request, SimpleNamespace(credentials='test-session'))
    return anyio.run(exercise)


def test_trusted_review_policy_and_legacy_default():
    session = {'id': 'synthetic-owner', 'email_verified': True}
    assert account_from_profile(session)['cv_review_policy'] == {'scope': 'item', 'version': 1}
    for scope, version in [('section', 1), ('item', 1)]:
        session.update(cv_review_scope=scope, cv_review_policy_version=version)
        assert account_from_profile(session)['cv_review_policy'] == {'scope': 'item', 'version': 1}


@pytest.mark.parametrize('policy', [
    {'cv_review_scope': 'premium'},
    {'cv_review_scope': 'item', 'cv_review_policy_version': True},
    {'cv_review_scope': 'section', 'cv_review_policy_version': 2},
    {'cv_review_scope': 'item', 'cv_review_policy_version': 2},
    {'cv_review_scope': 'item', 'cv_review_policy_version': 3},
])
def test_unrecognised_policy_does_not_grant_access(policy):
    with pytest.raises(HTTPException) as error:
        account_from_profile({'id': 'synthetic-owner', 'email_verified': True, **policy})
    assert error.value.status_code == 503
