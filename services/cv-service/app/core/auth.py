"""Validate the existing Profile session; never trust a browser-supplied owner."""
import httpx
from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer

bearer = HTTPBearer(auto_error=False)


async def current_account(request: Request, credentials):
    if credentials is None: raise HTTPException(401, 'Sign in to access your CVs.')
    headers = {'Authorization': 'Bearer ' + credentials.credentials}
    try:
        session = await request.app.state.profile_client.get('/api/v1/profile/auth/session', headers=headers)
        if session.status_code == 401: raise HTTPException(401, 'Your session has ended. Sign in again.')
        if session.status_code != 200: raise ValueError
        account = session.json()
        if not isinstance(account.get('id'), str) or not account['id'] or account.get('email_verified') is not True: raise ValueError
        response = await request.app.state.profile_client.get('/api/v1/profile', headers=headers)
        if response.status_code == 401: raise HTTPException(401, 'Your session has ended. Sign in again.')
        if response.status_code != 200: raise ValueError
        profile = response.json()
        if not isinstance(profile, dict): raise ValueError
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise HTTPException(503, 'Account verification is unavailable. Keep your inputs and retry.') from exc
    if profile.get('onboarding_complete') is not True:
        raise HTTPException(403, 'Finish your initial setup before using CV review.')
    return {'id': account['id'], 'profile_version': profile.get('version', 0), 'authorization': headers['Authorization']}
