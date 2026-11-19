import os
from typing import Annotated, Literal
from datetime import datetime
from ipaddress import ip_address, ip_network
from socket import gaierror, getaddrinfo
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.core.auth import bearer, verify_google
from app.core.mail import normalize_email

router = APIRouter(prefix='/api/v1/profile/auth', tags=['P09–P16 account access'])
Secret = Annotated[str, Field(min_length=32, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]

class Attempt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    flow_id: Secret
    attempt_id: Secret

class Begin(Attempt):
    intent: Literal['login', 'register']
    generation: int = Field(strict=True, ge=1, le=9007199254740991)

class Complete(Attempt):
    name: str | None = Field(None, max_length=80)
    email: str | None = Field(None, max_length=254)
    password: str | None = Field(None, min_length=8, max_length=128)
    credential: str | None = Field(None, max_length=12000)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        return normalize_email(value) if value is not None else None

class VerificationAccess(Attempt):
    pass

class Verify(VerificationAccess):
    challenge_id: Secret
    code: str = Field(pattern=r'^[0-9]{6}$')

class AccountView(BaseModel):
    id: str
    name: str
    email: str
    email_verified: bool
    provider: Literal['google', 'local_test', 'email']
    expires_at: datetime
    # The current service-wide policy gives every account the same item scope.
    # Keep these server-owned fields in the response for CV service consumers.
    cv_review_scope: Literal['item'] = 'item'
    # Item scope keeps its existing v1 wire contract, so older CV deployments
    # can authenticate while the CV service upgrades its saved policy state.
    cv_review_policy_version: Literal[1] = 1

    @model_validator(mode='before')
    @classmethod
    def current_review_policy(cls, value):
        # Legacy accounts can carry the earlier tier-specific settings. Project
        # the current policy without mutating stored account data or accepting
        # a browser-supplied entitlement.
        if isinstance(value, dict):
            return {**value, 'cv_review_scope': 'item', 'cv_review_policy_version': 1}
        return value

class AuthenticatedSession(AccountView):
    session_token: Secret

class PendingVerification(BaseModel):
    verification_required: Literal[True]
    challenge_id: str
    masked_email: str
    expires_at: datetime
    resend_at: datetime

class Choice(BaseModel):
    id: str
    name: str
    email: str

class Nonce(BaseModel):
    nonce: str

class Done(BaseModel):
    ok: bool

class ResetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(max_length=254)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        return normalize_email(value)

class ResetComplete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    challenge_id: Secret
    code: str = Field(pattern=r'^[0-9]{6}$')
    password: str = Field(min_length=8, max_length=128)

class ResetReceipt(BaseModel):
    challenge_id: str
    message: str


def repo(request: Request):
    if getattr(request.app.state, 'accounts', None) is None:
        raise HTTPException(503, 'Account storage unavailable. Please retry.')
    return request.app.state.accounts


def _trusted_proxy(peer: str) -> bool:
    configured = os.getenv('TRUSTED_PROXY_CIDRS', '')
    if configured.strip():
        try:
            peer_ip = ip_address(peer)
            for entry in configured.split(','):
                cidr = entry.strip()
                if cidr and peer_ip in ip_network(cidr, strict=False):
                    return True
        except ValueError:
            pass
    try:
        return peer in {address[4][0] for address in getaddrinfo('gateway', None)}
    except gaierror:
        return False


def password_source(request: Request):
    peer = request.client.host if request.client else 'unknown'
    forwarded = request.headers.get('x-real-ip')
    if forwarded:
        # The Compose gateway or configured trusted proxy replaces this header.
        # Direct clients and other backend services cannot spoof password limits.
        try:
            source = str(ip_address(forwarded))
            if _trusted_proxy(peer):
                return source
        except ValueError:
            pass
    return peer

@router.get('/local-accounts', response_model=list[Choice])
def local_accounts(request: Request, accounts=Depends(repo)):
    if request.app.state.auth_settings.mode != 'local_test':
        raise HTTPException(404, 'Local accounts are disabled.')
    return accounts.local_accounts()

@router.post('/forgot-password', response_model=ResetReceipt)
def forgot_password(data: ResetRequest, request: Request, background_tasks: BackgroundTasks, accounts=Depends(repo)):
    return accounts.password_reset.request(data.email, request.app.state.auth_settings, accounts.mailer, background_tasks)

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

@router.post('/complete', response_model=AuthenticatedSession | PendingVerification, responses={
    401: {'description': 'Incorrect email/password or invalid provider credential.'},
    404: {'description': 'No account found for Google sign-in. Choose Create new account.'},
})
def complete(data: Complete, request: Request, accounts=Depends(repo)):
    return accounts.finish(data, request.app.state.auth_settings, verify_google, password_source(request))

@router.post('/verify-email', response_model=AuthenticatedSession)
def verify(data: Verify, request: Request, accounts=Depends(repo)):
    return accounts.verify_email(data, request.app.state.auth_settings)

@router.post('/resend-verification', response_model=PendingVerification)
def resend(data: VerificationAccess, request: Request, accounts=Depends(repo)):
    return accounts.resend(data, request.app.state.auth_settings)

@router.get('/session', response_model=AccountView)
def session(request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], accounts=Depends(repo)):
    if credentials is None:
        raise HTTPException(401, 'Sign in to continue.')
    return accounts.session(credentials.credentials, request.app.state.auth_settings)

@router.post('/logout', response_model=Done)
def logout(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], accounts=Depends(repo)):
    if credentials:
        accounts.logout(credentials.credentials)
    return {'ok': True}
