import hashlib
import hmac
from fastapi import HTTPException

COOKIE = 'elo_session'


def browser_access(data, request):
    if request.headers.get('x-elo-browser') != '1':
        return data
    key = request.app.state.auth_settings.otp_secret.encode()
    message = '\0'.join(('elo-browser-session-v1', data.flow_id, data.attempt_id, data.session_token)).encode()
    token = hmac.new(key, message, hashlib.sha256).hexdigest()
    return data.model_copy(update={'session_token': token})


def install_browser_session(data, access, result, request, response):
    if request.headers.get('x-elo-browser') != '1' or result.get('verification_required'):
        return
    response.set_cookie(COOKIE, f'{data.session_token}.{access.session_token}',
                        httponly=True, secure=request.app.state.auth_settings.environment == 'production',
                        samesite='strict', path='/api/v1')


def clear_browser_session(request, response, credentials):
    if request.headers.get('x-elo-browser') != '1':
        return
    if request.cookies.get(COOKIE) and credentials is None:
        raise HTTPException(409, 'The browser session changed. Sign in again.')
    response.delete_cookie(COOKIE, path='/api/v1', httponly=True,
                           secure=request.app.state.auth_settings.environment == 'production', samesite='strict')
