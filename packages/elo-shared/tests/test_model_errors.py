"""Provider response-body errors stay distinct from HTTP status and output."""
import copy
import json

import pytest

from elo_shared.model_errors import ModelResponseError, raise_for_completion_error


PRIVATE = 'private-CV-prompt-key-and-provider-prose'


@pytest.mark.parametrize('envelope', [
    None, [], {}, {'choices': []},
    {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"error":"user data"}'}}]},
    {'object': 'response', 'status': 'completed', 'error': None, 'output': []},
    {'error': None, 'choices': [{'error': None, 'message': {'content': '{}'}}]},
])
def test_no_provider_error_leaves_envelope_unchanged(envelope):
    original = copy.deepcopy(envelope)
    assert raise_for_completion_error(envelope) is None
    assert envelope == original


@pytest.mark.parametrize('choice_error', [False, True])
@pytest.mark.parametrize('code,reason', [
    (400, 'invalid_request'), (401, 'authentication_failed'), (402, 'rate_limit_or_quota'),
    (403, 'permission_denied'), (404, 'not_found'), (429, 'rate_limit_or_quota'),
    (502, 'provider_unavailable'), (599, 'provider_unavailable'),
])
def test_embedded_errors_beat_even_complete_content(choice_error, code, reason):
    error = {'code': code, 'message': PRIVATE}
    envelope = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
    (envelope['choices'][0] if choice_error else envelope)['error'] = error
    original = copy.deepcopy(envelope)
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error(envelope)
    failure = caught.value
    assert (failure.reason, failure.parameter, failure.status_code) == (reason, None, code)
    assert failure.quota_exhausted is (code == 402)
    assert not isinstance(failure, ValueError)  # Not a schema-repair candidate.
    assert PRIVATE not in str(failure) + repr(failure.__dict__)
    assert failure.__cause__ is None and failure.__context__ is None
    assert envelope == original


@pytest.mark.parametrize('code', [None, True, False, '429', 200, 399, 600, 429.0, [], {}])
def test_embedded_status_must_be_an_actual_http_error_integer(code):
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': {'code': code, 'message': PRIVATE}})
    assert caught.value.status_code is None
    assert caught.value.reason == 'http_error'


@pytest.mark.parametrize('error', ['', False, [], 42, {}, {'param': PRIVATE}, {'message': [PRIVATE]}])
def test_malformed_non_null_error_is_not_success(error):
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': error})
    assert caught.value.__dict__ == {'reason': 'http_error', 'parameter': None, 'status_code': None, 'quota_exhausted': False}


@pytest.mark.parametrize('raw_string', [False, True])
def test_one_bounded_nested_upstream_error_refines_reason_without_replacing_outer_code(raw_string):
    nested = {'error': {'code': 'unsupported_parameter', 'param': 'temperature', 'message': PRIVATE}}
    raw = json.dumps(nested) if raw_string else nested
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': {'code': 502, 'message': PRIVATE, 'metadata': {'raw': raw}}})
    assert caught.value.__dict__ == {'reason': 'unsupported_parameter', 'parameter': 'temperature', 'status_code': 502, 'quota_exhausted': False}
    assert PRIVATE not in str(caught.value) + repr(caught.value.__dict__)


@pytest.mark.parametrize('message,reason,parameter', [
    ('Schema produces too many states.', 'schema_too_complex', 'schema'),
    ('response_format json_schema is not supported.', 'structured_output_unsupported', 'response_format'),
    ('Invalid schema: unsupported keyword.', 'schema_rejected', 'schema'),
    ('Unsupported parameter reasoning_effort.', 'unsupported_parameter', 'reasoning_effort'),
])
def test_nested_request_rejections_keep_fixed_guidance(message, reason, parameter):
    raw = {'error': {'code': 400, 'message': message + PRIVATE}}
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': {'metadata': {'raw': raw}}})
    assert caught.value.__dict__ == {'reason': reason, 'parameter': parameter, 'status_code': 400, 'quota_exhausted': False}


@pytest.mark.parametrize('typed,reason', [
    ('authentication', 'authentication_failed'), ('rate_limit_exceeded', 'rate_limit_or_quota'),
    ('provider_overloaded', 'provider_unavailable'), ('refusal', 'permission_denied'),
])
def test_typed_metadata_maps_only_known_reasons(typed, reason):
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': {'metadata': {'error_type': typed}}})
    assert caught.value.reason == reason
    assert caught.value.status_code is None


@pytest.mark.parametrize('raw', ['{bad', '[' * 1200 + '0' + ']' * 1200,
                               PRIVATE * 2000, {'error': {'message': PRIVATE * 2000}}])
def test_unusable_nested_error_is_bounded_and_never_leaks(raw):
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': {'metadata': {'raw': raw}}})
    assert caught.value.__dict__ == {'reason': 'http_error', 'parameter': None, 'status_code': None, 'quota_exhausted': False}


def test_nested_metadata_is_not_followed_recursively():
    nested = {'error': {'metadata': {'raw': {'error': {'code': 401}}}}}
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': {'metadata': {'raw': nested}}})
    assert caught.value.reason == 'http_error'
    assert caught.value.status_code is None


def test_oversized_details_preserve_only_safe_outer_status():
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': {'code': 429, 'message': PRIVATE * 2000}})
    assert caught.value.__dict__ == {'reason': 'rate_limit_or_quota', 'parameter': None, 'status_code': 429, 'quota_exhausted': False}


def test_exception_constructor_also_rejects_unsafe_diagnostics():
    failure = ModelResponseError(PRIVATE, PRIVATE, True)
    assert failure.__dict__ == {'reason': 'http_error', 'parameter': None, 'status_code': None, 'quota_exhausted': False}
    assert PRIVATE not in str(failure)


def test_only_selected_first_choice_is_examined():
    envelope = {'choices': [{'message': {'content': '{}'}}, {'error': {'code': 401}}]}
    assert raise_for_completion_error(envelope) is None


@pytest.mark.parametrize('nested', [False, True])
@pytest.mark.parametrize('error', [
    {'code': 402},
    {'code': 'insufficient_quota'},
    {'status': 'payment_required'},
    {'type': 'insufficient_quota'},
    {'metadata': {'error_type': 'payment_required'}},
    {'code': 429, 'metadata': {'error_type': 'insufficient_quota'}},
])
def test_known_exhausted_quota_is_distinct_from_temporary_rate_limits(error, nested):
    envelope = {'error': error}
    if nested:
        envelope = {'error': {'code': 429, 'metadata': {'raw': json.dumps(envelope)}}}
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error(envelope)
    assert caught.value.reason == 'rate_limit_or_quota'
    assert caught.value.quota_exhausted is True
    if nested:
        assert caught.value.status_code == 429


@pytest.mark.parametrize('error', [
    {'code': 429},
    {'code': 'rate_limit_exceeded'},
    {'metadata': {'error_type': 'rate_limit_exceeded'}},
    {'code': 429, 'message': 'insufficient_quota payment_required ' + PRIVATE},
    {'code': 429, 'quota_exhausted': True},
    {'code': 429, 'metadata': {'error_type': ['insufficient_quota']}},
])
def test_arbitrary_content_cannot_mark_temporary_limit_as_exhausted(error):
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': error})
    assert caught.value.reason == 'rate_limit_or_quota'
    assert caught.value.quota_exhausted is False


@pytest.mark.parametrize('value', [None, 1, 0, 'true', 'insufficient_quota', [], {}])
def test_quota_constructor_accepts_only_boolean_true(value):
    assert ModelResponseError('rate_limit_or_quota', quota_exhausted=value).quota_exhausted is False
    assert ModelResponseError('rate_limit_or_quota', quota_exhausted=True).quota_exhausted is True


def test_exhausted_outer_quota_cannot_be_downgraded_by_nested_temporary_limit():
    error = {'code': 402, 'metadata': {'raw': {'error': {'code': 429}}}}
    with pytest.raises(ModelResponseError) as caught:
        raise_for_completion_error({'error': error})
    assert caught.value.status_code == 402 and caught.value.quota_exhausted is True
