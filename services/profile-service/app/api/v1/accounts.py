from typing import Annotated
from ipaddress import ip_address
from socket import gaierror, getaddrinfo
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from app.core.auth import bearer, verify_google
from app.core.browser_session import browser_access, install_browser_session, clear_browser_session
from app.schemas.accounts import Attempt, Begin, Complete, VerificationAccess, Verify, AccountView, PendingVerification, Choice, Nonce, Done, ResetRequest, ResetComplete, ResetReceipt

router = APIRouter(prefix='/api/v1/profile/auth', tags=['P09–P16 account access'])


def repo(request: Request):
    if getattr(request.app.state, 'accounts', None) is None:
        raise HTTPException(503, 'Account storage unavailable. Please retry.')
    return request.app.state.accounts


def password_source(request: Request):
    peer = request.client.host if request.client else 'unknown'
    forwarded = request.headers.get('x-real-ip')
    if forwarded:
        # The Compose gateway replaces this header.
        try:
            source = str(ip_address(forwarded))
            if peer in {address[4][0] for address in getaddrinfo('gateway', None)}:
                return source
        except (ValueError, gaierror):
            pass
    return peer

@router.get('/local-accounts', response_model=list[Choice])
def local_accounts(request: Request, accounts=Depends(repo)):
    if request.app.state.auth_settings.mode != 'local_test':
        raise HTTPException(404, 'Local accounts are disabled.')
    return accounts.local_accounts()

@router.post('/forgot-password', response_model=ResetReceipt)
def forgot_password(data: ResetRequest, request: Request, accounts=Depends(repo)):
    return accounts.password_reset.request(data.email, request.app.state.auth_settings, accounts.mailer)

@router.post('/reset-password', response_model=Done)
def reset_password(data: ResetComplete, request: Request, accounts=Depends(repo)):
    return accounts.password_reset.complete(data, request.app.state.auth_settings)

@router.post('/attempts', response_model=Nonce)
def begin(data: Begin, request: Request, accounts=Depends(repo)):
    return accounts.begin(data, request.app.state.auth_settings)

@router.post('/attempts/cancel', response_model=Done)
def cancel(data: Attempt, accounts=Depends(repo)):
    accounts.cancel(data)
    return {'ok': True}

@router.post('/complete', response_model=AccountView | PendingVerification, responses={
    401: {'description': 'Incorrect password or invalid provider credential.'},
    404: {'description': 'No account found. Choose Create new account.'},
})
def complete(data: Complete, request: Request, response: Response, accounts=Depends(repo)):
    access = browser_access(data, request)
    result = accounts.finish(access, request.app.state.auth_settings, verify_google, password_source(request))
    install_browser_session(data, access, result, request, response)
    return result

@router.post('/verify-email', response_model=AccountView)
def verify(data: Verify, request: Request, response: Response, accounts=Depends(repo)):
    access = browser_access(data, request)
    result = accounts.verify_email(access, request.app.state.auth_settings)
    install_browser_session(data, access, result, request, response)
    return result

@router.post('/resend-verification', response_model=PendingVerification)
def resend(data: VerificationAccess, request: Request, accounts=Depends(repo)):
    return accounts.resend(browser_access(data, request), request.app.state.auth_settings)

@router.get('/session', response_model=AccountView)
def session(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], accounts=Depends(repo)):
    if credentials is None:
        raise HTTPException(401, 'Sign in to continue.')
    return accounts.session(credentials.credentials, request.app.state.auth_settings)

@router.post('/logout', response_model=Done)
def logout(request: Request, response: Response, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], accounts=Depends(repo)):
    clear_browser_session(request, response, credentials)
    if credentials:
        accounts.logout(credentials.credentials)
    return {'ok': True}
