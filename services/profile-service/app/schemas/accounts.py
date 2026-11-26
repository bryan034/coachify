"""Account access requests and views."""
from datetime import datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from elo_shared.plans import AccountType
from app.core.mail import normalize_email

Secret = Annotated[str, Field(min_length=32, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')]

class Attempt(BaseModel):
    model_config = ConfigDict(extra='forbid')
    flow_id: Secret
    attempt_id: Secret

class Begin(Attempt):
    intent: Literal['login', 'register']
    generation: int = Field(strict=True, ge=1, le=9007199254740991)

class Complete(Attempt):
    session_token: Secret = Field(description='Client session marker in X-Elo-Browser: 1 mode; the server derives the credential and returns it only in an HttpOnly cookie. Otherwise the caller-supplied bearer for non-browser API clients.')
    name: str | None = Field(None, max_length=80)
    email: str | None = Field(None, max_length=254)
    password: str | None = Field(None, min_length=8, max_length=128)
    credential: str | None = Field(None, max_length=12000)

    @field_validator('email')
    @classmethod
    def valid_email(cls, value):
        return normalize_email(value) if value is not None else None

class VerificationAccess(Attempt):
    session_token: Secret = Field(description='The same client session marker (browser cookie mode) or bearer (non-browser mode) supplied at account completion.')

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
    account_type: AccountType = 'free'
    cv_review_scope: Literal['item'] = 'item'
    cv_review_policy_version: Literal[1] = 1

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
