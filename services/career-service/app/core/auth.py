"""Validate the bearer through Profile; never read its database or trust owner inputs."""
import httpx
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


async def current_account(request: Request, credentials: HTTPAuthorizationCredentials | None = None):
    # Called by the dependency below so tests can replace one explicit boundary.
    if credentials is None:
        raise HTTPException(401, 'Sign in to import a job description.')
    try:
        response = await request.app.state.profile_client.get('/api/v1/profile/auth/session',
            headers={'Authorization': 'Bearer ' + credentials.credentials})
    except httpx.HTTPError as exc:
        raise HTTPException(503, 'Account verification is unavailable. Please retry.') from exc
    if response.status_code == 401:
        raise HTTPException(401, 'Your session has ended. Sign in again.')
    if response.status_code != 200:
        raise HTTPException(503, 'Account verification is unavailable. Please retry.')
    try:
        account = response.json()
        if not isinstance(account.get('id'), str) or not account['id'] or account.get('email_verified') is not True:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise HTTPException(503, 'Account verification is unavailable. Please retry.') from exc
    # A verified account may still be in initial setup. Read Profile's canonical
    # completion marker rather than trusting a browser flag or populated fields.
    try:
        response = await request.app.state.profile_client.get('/api/v1/profile',
            headers={'Authorization': 'Bearer ' + credentials.credentials})
        if response.status_code == 401:
            raise HTTPException(401, 'Your session has ended. Sign in again.')
        if response.status_code != 200:
            raise ValueError
        profile = response.json()
        if not isinstance(profile, dict):
            raise ValueError
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(503, 'Profile verification is unavailable. Please retry.') from exc
    if profile.get('onboarding_complete') is not True:
        raise HTTPException(403, 'Finish your initial setup before using Career Goal.')
    return account['id']
