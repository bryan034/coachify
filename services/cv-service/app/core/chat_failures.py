"""Log why CV chat steps fail using fixed codes.

Never log exception strings, prompts, provider bodies, URLs, answers or CV text.
"""
import json
import logging
import re
import traceback
import httpx
from pydantic import ValidationError

logger = logging.getLogger(__name__)
_MESSAGE_CATEGORIES = (
    ('is busy', 'capacity_busy'), ('not configured', 'not_configured'), ('timed out', 'provider_timeout'),
    ('exceeded', 'response_too_large'), ('incomplete', 'response_incomplete'),
    ('could not choose a valid next step', 'plan_rejected'), ('still needs interpretation', 'evidence_pending'),
    ('referred to', 'reference_rejected'), ('refers to', 'reference_rejected'), ('invalid source choice', 'reference_rejected'),
    ('not supported', 'evidence_unsupported'), ('needs a matching', 'interpretation_missing'),
)


def _safe_name(value):
    value = str(value)
    return value if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) else 'other'


def validation_errors(error):
    """Field paths and error types only; pydantic's message text can repeat the input."""
    return [{'field': '.'.join(_safe_name(part) for part in item['loc']), 'type': _safe_name(item['type'])}
            for item in error.errors(include_input=False, include_url=False)[:8]]


def _category(error, cause):
    if isinstance(error, ValidationError): return 'schema_validation'
    if isinstance(cause, httpx.TimeoutException): return 'provider_timeout'
    if isinstance(cause, httpx.HTTPStatusError): return 'provider_status'
    if isinstance(cause, httpx.HTTPError): return 'provider_connection'
    if isinstance(cause, (KeyError, IndexError, TypeError, json.JSONDecodeError)): return 'provider_response'
    if isinstance(error, ValueError):
        text = str(error)
        return next((category for marker, category in _MESSAGE_CATEGORIES if marker in text), 'rejected')
    return 'unexpected'


def log_chat_failure(stage, conversation_id, action_id, error, *, category=None):
    cause = error.__cause__
    status = cause.response.status_code if isinstance(cause, httpx.HTTPStatusError) else None
    frames = traceback.extract_tb(error.__traceback__)
    where = f'{frames[-1].filename.rsplit("/app/", 1)[-1]}:{frames[-1].lineno}' if frames else None
    logger.warning('CV chat failed stage=%s conversation_id=%s action_id=%s category=%s exception=%s cause=%s provider_status_code=%s where=%s',
        stage, conversation_id, action_id, category or _category(error, cause), type(error).__name__,
        type(cause).__name__ if cause else None, status, where)
