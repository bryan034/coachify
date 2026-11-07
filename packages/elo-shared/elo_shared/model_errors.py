"""Recognize error envelopes after callers finish their bounded response reads.

An HTTP 200 can still contain a provider rejection. Keep its embedded code
distinct from the HTTP status and retain only fixed, safe diagnostic labels.
This helper performs no I/O, retries, content recovery or schema validation.
"""
import json


MAX_ERROR_BYTES = 16 * 1024
PARAMETERS = frozenset({'response_format', 'schema', 'model', 'reasoning_effort',
                        'temperature', 'max_tokens', 'messages'})
CODE_REASONS = {
    'authentication': 'authentication_failed',
    'authentication_error': 'authentication_failed',
    'invalid_api_key': 'authentication_failed',
    'unauthenticated': 'authentication_failed',
    'permission_denied': 'permission_denied',
    'content_policy_violation': 'permission_denied',
    'refusal': 'permission_denied',
    'not_found': 'not_found',
    'model_not_found': 'not_found',
    'payment_required': 'rate_limit_or_quota',
    'rate_limit_exceeded': 'rate_limit_or_quota',
    'insufficient_quota': 'rate_limit_or_quota',
    'provider_unavailable': 'provider_unavailable',
    'provider_overloaded': 'provider_unavailable',
    'timeout': 'provider_unavailable',
    'server': 'provider_unavailable',
    'server_error': 'provider_unavailable',
    'invalid_request': 'invalid_request',
    'invalid_request_error': 'invalid_request',
    'invalid_argument': 'invalid_request',
    'context_length_exceeded': 'invalid_request',
    'unsupported_parameter': 'unsupported_parameter',
    'unsupported_value': 'unsupported_parameter',
}
REASONS = frozenset(CODE_REASONS.values()) | {
    'schema_too_complex', 'schema_rejected', 'structured_output_unsupported', 'http_error',
}
EXHAUSTED_QUOTA_CODES = frozenset({'payment_required', 'insufficient_quota'})


class ModelResponseError(Exception):
    """Safe provider rejection; status_code is embedded, never the HTTP status."""

    def __init__(self, reason, parameter=None, status_code=None, *, quota_exhausted=False):
        self.reason = reason if isinstance(reason, str) and reason in REASONS else 'http_error'
        self.parameter = parameter if isinstance(parameter, str) and parameter in PARAMETERS else None
        self.status_code = _status(status_code)
        self.quota_exhausted = self.status_code == 402 or quota_exhausted is True
        super().__init__(self.reason)


def _status(value):
    return value if type(value) is int and 400 <= value <= 599 else None


def _bounded_error(value):
    if not isinstance(value, dict):
        return {}
    try:
        if len(json.dumps(value, ensure_ascii=False).encode('utf-8')) <= MAX_ERROR_BYTES:
            return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        pass
    return {}


def _details(error):
    status = _status(error.get('code'))
    quota_exhausted = status == 402
    reason = {400: 'invalid_request', 401: 'authentication_failed',
              402: 'rate_limit_or_quota', 403: 'permission_denied',
              404: 'not_found', 429: 'rate_limit_or_quota'}.get(
                  status, 'provider_unavailable' if status is not None and status >= 500 else 'http_error')
    metadata = error.get('metadata')
    typed = metadata.get('error_type') if isinstance(metadata, dict) else None
    for value in (error.get('code'), error.get('status'), error.get('type'), typed):
        if isinstance(value, str) and value.casefold() in CODE_REASONS:
            reason = CODE_REASONS[value.casefold()]
            quota_exhausted |= value.casefold() in EXHAUSTED_QUOTA_CODES
    parameter = error.get('param')
    parameter = parameter if isinstance(parameter, str) and parameter in PARAMETERS else None
    message = error.get('message')
    text = message.casefold() if isinstance(message, str) else ''
    # Only request-error prose can refine a rejection. Provider outage/auth
    # messages must not become schema guidance just because they mention JSON.
    if reason in ('invalid_request', 'unsupported_parameter', 'http_error'):
        unsupported = any(word in text for word in ('not supported', 'unsupported', 'unknown name', 'not allowed'))
        if any(word in text for word in ('too many states', 'too much branching', 'schema is too complex', 'schema complexity')):
            reason, parameter = 'schema_too_complex', 'schema'
        elif unsupported and any(word in text for word in ('response_format', 'json_schema', 'structured output')):
            reason, parameter = 'structured_output_unsupported', 'response_format'
        elif 'schema' in text and any(word in text for word in ('invalid', 'unsupported', 'unknown name', 'not supported')):
            reason, parameter = 'schema_rejected', 'schema'
        elif unsupported or (parameter and 'invalid' in text) or 'invalid reasoning_effort' in text:
            reason = 'unsupported_parameter'
            if parameter is None:
                parameter = next((name for name in sorted(PARAMETERS) if name in text), None)
    return reason, parameter, status, quota_exhausted


def _failure(value):
    error = _bounded_error(value)
    if not error and isinstance(value, dict):
        # Large/invalid detail must not hide a safe numeric rejection code.
        error = {'code': _status(value.get('code'))}
    reason, parameter, status, quota_exhausted = _details(error)
    metadata = error.get('metadata')
    raw = metadata.get('raw') if isinstance(metadata, dict) else None
    # OpenRouter may wrap one upstream error as JSON text or an object. Parse
    # only this documented layer; never recurse through arbitrary provider data.
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if len(raw.encode('utf-8')) <= MAX_ERROR_BYTES else None
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raw = None
    upstream = _bounded_error(raw)
    nested = _bounded_error(upstream.get('error'))
    if nested:
        nested_reason, nested_parameter, nested_status, nested_quota_exhausted = _details(nested)
        if nested_reason != 'http_error':
            reason = nested_reason
        if nested_parameter is not None:
            parameter = nested_parameter
        if status is None:
            status = nested_status
        quota_exhausted |= nested_quota_exhausted
    return ModelResponseError(reason, parameter, status, quota_exhausted=quota_exhausted)


def raise_for_completion_error(envelope):
    """Reject an explicit envelope error without examining generated content."""
    if not isinstance(envelope, dict):
        return
    if envelope.get('error') is not None:
        raise _failure(envelope['error'])
    choices = envelope.get('choices')
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        error = choices[0].get('error')
        if error is not None:
            raise _failure(error)
