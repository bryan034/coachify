from typing import Annotated, Literal
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field, field_validator
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
    session_token: Secret
    name: str | None = Field(None, max_length=80)
    email: str | None = Field(None, max_length=254)
    password: str | None = Field(None, min_length=8, max_length=128)
    credential: str | None = Field(None, max_length=12000)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        return normalize_email(value) if value is not None else None

class VerificationAccess(Attempt):
    session_token: Secret

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
def complete(data: Complete, request: Request, accounts=Depends(repo)):
    return accounts.finish(data, request.app.state.auth_settings, verify_google)

@router.post('/verify-email', response_model=AccountView)
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
