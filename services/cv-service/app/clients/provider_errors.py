"""Classify bounded rejection bodies into fixed diagnostics; never expose prose."""
import json
from typing import get_args
from app.domain.extraction_errors import ExtractionFailure, ProviderParameter

PARAMETERS = frozenset(get_args(ProviderParameter))


def provider_failure(response, stage):
    status = response.status_code
    reason = {400: 'invalid_request', 401: 'authentication_failed', 403: 'permission_denied',
              404: 'not_found', 429: 'rate_limit_or_quota'}.get(status,
                  'provider_unavailable' if status >= 500 else 'http_error')
    parameter = None
    # The SDK transport already limits rejections to 16 KiB; do not read any
    # additional stream or retain the message, arbitrary fields or provider IDs.
    try:
        body = response.content
        payload = json.loads(body) if len(body) <= 16 * 1024 else None
        # Some OpenAI-compatible rejections wrap their single error in a list.
        # Never concatenate arbitrary/multiple errors or retain provider prose.
        if isinstance(payload, list) and len(payload) == 1:
            payload = payload[0]
        error = payload.get('error') if isinstance(payload, dict) else None
        message = error.get('message') if isinstance(error, dict) else None
        raw_parameter = error.get('param') if isinstance(error, dict) else None
        if isinstance(raw_parameter, str) and raw_parameter in PARAMETERS:
            parameter = raw_parameter
        text = message.casefold() if isinstance(message, str) else ''
        if status == 400:
            unsupported = any(word in text for word in ('not supported', 'unsupported', 'unknown name', 'not allowed'))
            if any(word in text for word in ('too many states', 'too much branching', 'schema is too complex', 'schema complexity')):
                reason, parameter = 'schema_too_complex', 'schema'
            elif unsupported and any(word in text for word in ('response_format', 'json_schema', 'structured output')):
                reason, parameter = 'structured_output_unsupported', 'response_format'
            elif 'schema' in text and any(word in text for word in ('invalid', 'unsupported', 'unknown name', 'not supported')):
                reason, parameter = 'schema_rejected', 'schema'
            elif unsupported or (parameter and 'invalid' in text) or ('invalid reasoning_effort' in text):
                reason = 'unsupported_parameter'
                if parameter is None:
                    parameter = next((name for name in sorted(PARAMETERS) if name in text), None)
    except (ValueError, TypeError, RuntimeError):
        # Malformed/oversized/HTML bodies and unread streams retain a safe
        # status-only classification. Never log parsing exceptions or the body.
        pass
    return classified_provider_failure(reason, parameter, stage, status)


def classified_provider_failure(reason, parameter, stage, status=None):
    """Reuse fixed recovery text; embedded errors do not invent an HTTP status."""
    messages = {
        'schema_too_complex': 'The model provider rejected the extraction schema as too complex. Your upload is saved; the schema request needs adjustment before retrying.',
        'schema_rejected': 'The model provider rejected the extraction schema. Your upload is saved; review the provider schema compatibility before retrying.',
        'structured_output_unsupported': 'The model provider does not support the requested structured-output format. Your upload is saved; use a compatible model/endpoint or explicitly configure JSON-object compatibility mode.',
        'unsupported_parameter': 'The model provider rejected an unsupported request parameter. Your upload is saved; review model compatibility before retrying.',
        'invalid_request': 'The model provider rejected the extraction request. Your upload is saved; review model and schema compatibility before retrying.',
        'authentication_failed': 'The model provider rejected authentication. Your upload is saved; check the server-side CV model credentials before retrying.',
        'permission_denied': 'The model provider denied access. Your upload is saved; check the configured model permissions before retrying.',
        'not_found': 'The model provider could not find the requested resource. Your upload is saved; check the configured model and endpoint before retrying.',
        'rate_limit_or_quota': 'The model provider rate limit or quota was exceeded. Your upload is saved; check provider usage and retry after capacity is available.',
        'provider_unavailable': 'The model provider is temporarily unavailable. Your upload is saved; retry later.',
        'http_error': 'The model provider rejected the extraction request. Your upload is saved; review the provider configuration before retrying.',
    }
    return ExtractionFailure(messages[reason], stage, 'provider_http_error', status,
                             provider_reason=reason, provider_parameter=parameter)
