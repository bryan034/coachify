import logging
import os
import re
from dataclasses import dataclass
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
    local_owner: str | None = None


def auth_settings() -> AuthSettings:
    mode = os.getenv("AUTH_MODE", "google")
    if mode not in {"google", "local_test"}:
        raise RuntimeError("AUTH_MODE must be google or local_test.")
    if mode == "local_test":
        if os.getenv("APP_ENV", "production") != "development":
            raise RuntimeError("Local test identity requires APP_ENV=development.")
        identity = os.getenv("LOCAL_TEST_USER_ID", "coachify-local-user")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity):
            raise RuntimeError("LOCAL_TEST_USER_ID must contain 1–64 letters, digits, underscores or hyphens.")
        logging.getLogger(__name__).warning("Local test identity enabled. All profile requests use one development identity.")
        return AuthSettings(mode, "", "local_test:" + identity)
    return AuthSettings(mode, os.getenv("GOOGLE_CLIENT_ID", ""))


def current_owner(request: FastAPIRequest,
                  credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    settings = request.app.state.auth_settings
    if settings.mode == "local_test":
        # Only server configuration selects the identity; caller headers cannot override it.
        return settings.local_owner
    if credentials is None:
        raise HTTPException(401, "Sign in with Google to access your profile.")
    audience = settings.google_client_id
    if not audience:
        raise HTTPException(503, "Google sign-in is not configured on the server.")
    try:
        claims = id_token.verify_oauth2_token(credentials.credentials, Request(), audience)
        if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com") or not claims.get("sub"):
            raise ValueError("Invalid issuer or subject")
    except TransportError as exc:
        raise HTTPException(503, "Sign-in verification unavailable; retry shortly.") from exc
    except (ValueError, GoogleAuthError) as exc:
        raise HTTPException(401, "Sign-in expired or invalid. Sign in again.") from exc
    return "google:" + claims["sub"]
