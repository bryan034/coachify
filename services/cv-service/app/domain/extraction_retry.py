"""Which extraction failures retry automatically, and what the model is told about the last one.

Everything sent to the model is a fixed sentence or allowlisted validation feedback,
never provider prose, exception text or CV content.
"""
from app.domain.model_usage import GLOBAL_DAILY, OWNER_DAILY

REJECTED_OUTPUT = frozenset({'schema_validation', 'evidence_validation'})
_RETRYABLE = REJECTED_OUTPUT | {'timeout', 'connection_error', 'transport_error', 'invalid_json',
                                'invalid_response', 'incomplete_output', 'response_too_large'}
_RETRYABLE_PROVIDER_REASONS = frozenset({'rate_limit_or_quota', 'provider_unavailable'})
_GUIDANCE = {
    'schema_validation': 'The output did not match the required schema, even after repair. Fix the listed issues.',
    'evidence_validation': 'The output cited evidence or facts the source did not support, even after repair. Fix the listed issues.',
    'invalid_json': 'The response was not valid JSON. Return only one complete JSON object.',
    'invalid_response': 'The response had an unusable shape. Return only one complete JSON object matching the schema.',
    'incomplete_output': 'The response was cut off before it finished. Use shorter evidence and descriptions so the whole object fits.',
    'response_too_large': 'The response was too large. Use shorter evidence and descriptions and do not repeat content.',
    'timeout': 'The request timed out. Return the complete object without extra commentary.',
    'connection_error': 'The request was interrupted before a response arrived.',
    'transport_error': 'The request was interrupted before a response arrived.',
    'provider_http_error': 'The model provider rejected or could not complete the request.',
}


_USER_REASONS = {
    'schema_validation': "the model's answer didn't pass our checks",
    'evidence_validation': "the model's answer didn't pass our checks",
    'invalid_json': "the model's answer couldn't be read",
    'invalid_response': "the model's answer couldn't be read",
    'incomplete_output': "the model's answer was cut off",
    'response_too_large': "the model's answer was too long",
    'timeout': 'the model took too long to respond',
    'connection_error': 'the connection to the model dropped',
    'transport_error': 'the connection to the model dropped',
    'provider_http_error': 'the model service is busy or unavailable',
    'model_admission': 'the model is busy with other requests',
}


def waiting_message(operation):
    reason = _USER_REASONS.get(operation.get('retry_reason'), 'something went wrong')
    return f"Hit an error: {reason}. Retrying shortly (retry {operation.get('auto_retries', 1)} of {operation.get('auto_retry_limit', 2)})."


def retrying_message(operation, message):
    return f"Retry {operation['auto_retries']} of {operation.get('auto_retry_limit', 2)}: {message}"


def should_auto_retry(error):
    category = error.get('failure_category')
    if category == 'provider_http_error':
        return error.get('provider_reason') in _RETRYABLE_PROVIDER_REASONS
    if category == 'model_admission':
        return error.get('message') not in (OWNER_DAILY, GLOBAL_DAILY)
    return category in _RETRYABLE


def failure_for_model(error, issues=()):
    """None when the failure happened before a model could have caused or influenced it."""
    category = error.get('failure_category')
    if category not in _GUIDANCE: return None
    return {'category': category, 'guidance': _GUIDANCE[category], 'issues': list(issues)}
