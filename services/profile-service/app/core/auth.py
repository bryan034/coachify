import os
from dataclasses import dataclass
from secrets import token_urlsafe
from app.core.mail import mail_settings
from typing import Annotated
from fastapi import Depends, HTTPException, Request as FastAPIRequest
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request
from google.oauth2 import id_token

bearer = HTTPBearer(auto_error=False)

@dataclass(frozen=True)
class AuthSettings:
    mode: str
    google_client_id: str
    environment: str = "development"
    otp_secret: str = ""


def auth_settings() -> AuthSettings:
    environment = os.getenv('APP_ENV', 'production')
    if environment not in {'development', 'production'}:
        raise RuntimeError('APP_ENV must be development or production.')
    mode = os.getenv('AUTH_MODE', 'email')
    if mode not in {'google', 'email', 'local_test'}:
        raise RuntimeError('AUTH_MODE must be google, email or local_test.')
    if mode == 'local_test' and environment != 'development':
        raise RuntimeError('Local test accounts require APP_ENV=development.')
    audience = os.getenv('GOOGLE_CLIENT_ID', '') if mode == 'google' else ''
    secret = os.getenv('OTP_HASH_SECRET', '')
    if environment == 'production':
        if mode == 'google' and not audience:
            raise RuntimeError('Google mode requires GOOGLE_CLIENT_ID; choose AUTH_MODE=email for email-only production access.')
        if len(secret) < 32:
            raise RuntimeError('Production requires a random OTP_HASH_SECRET of at least 32 characters.')
    mail_settings(environment)
    return AuthSettings(mode, audience, environment, secret or token_urlsafe(48))


def verify_google(credential, audience, nonce):
    if not audience:
        raise HTTPException(503, 'Google sign-in is not configured on the server.')
    if not credential:
        raise HTTPException(401, 'Choose a Google account to continue.')
    try:
        claims = id_token.verify_oauth2_token(credential, Request(), audience)
        if claims.get('iss') not in ('accounts.google.com', 'https://accounts.google.com') or not claims.get('sub') or claims.get('nonce') != nonce:
            raise ValueError('Invalid issuer, subject or nonce')
        return claims
    except TransportError as exc:
        raise HTTPException(503, 'Google verification unavailable; please retry.') from exc
    except (ValueError, GoogleAuthError) as exc:
        raise HTTPException(401, 'Google sign-in expired or invalid. Start again.') from exc


def current_owner(request: FastAPIRequest,
                  credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if credentials is None:
        raise HTTPException(401, 'Sign in to access your profile.')
    accounts = getattr(request.app.state, 'accounts', None)
    if accounts is None:
        raise HTTPException(503, 'Account storage unavailable. Please retry.')
    return accounts.session(credentials.credentials, request.app.state.auth_settings)['owner']
