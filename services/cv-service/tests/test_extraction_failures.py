"""Synthetic provider failures retain useful diagnostics without private prose."""
import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from app.clients.extractor import Extractor
from app.domain.extraction_errors import ExtractionFailure
from tests.conftest import upload, mutation


PRIVATE = 'private-provider-response-and-cv-text'


def provider(monkeypatch, handler):
    monkeypatch.setenv('CV_LLM_API_KEY', PRIVATE)
    monkeypatch.setenv('CV_LLM_MODEL', 'synthetic-model')
    monkeypatch.setenv('CV_LLM_BASE_URL', 'https://provider.example/v1')
    original = httpx.Client
    monkeypatch.setattr('app.clients.extractor.Client',
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return Extractor()


@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 500, 503])
def test_provider_rejections_preserve_only_status(monkeypatch, status):
    calls = []
    def reject(request):
        calls.append(request)
        return httpx.Response(status, json={'error': {'message': PRIVATE}})
    extractor = provider(monkeypatch, reject)
    with pytest.raises(ExtractionFailure) as caught:
        extractor.extract([])
    failure = caught.value
    assert (failure.stage, failure.category, failure.provider_status_code) == ('model_request', 'provider_http_error', status)
    assert PRIVATE not in str(failure)
    assert failure.__cause__ is None
    assert len(calls) == 1  # SDK retries stay disabled.


@pytest.mark.parametrize('message,param,reason,parameter', [
    ('Schema produces a constraint with too many states for serving.', None, 'schema_too_complex', 'schema'),
    ('response_format json_schema is not supported by this model.', None, 'structured_output_unsupported', 'response_format'),
    ('Invalid schema: unsupported keyword in schema.', None, 'schema_rejected', 'schema'),
    ('Unsupported parameter reasoning_effort.', 'reasoning_effort', 'unsupported_parameter', 'reasoning_effort'),
    ('Invalid reasoning_effort: minimal. Valid values are high, low, medium, none.', None, 'unsupported_parameter', 'reasoning_effort'),
    ('Invalid input ' + PRIVATE, PRIVATE, 'invalid_request', None),
])
@pytest.mark.parametrize('list_wrapped', [False, True])
def test_safe_provider_rejection_reasons(monkeypatch, message, param, reason, parameter, list_wrapped):
    calls = []
    def reject(request):
        calls.append(json.loads(request.content))
        body = {'error': {'message': message, 'param': param, 'untrusted': PRIVATE}}
        return httpx.Response(400, json=[body] if list_wrapped else body)
    extractor = provider(monkeypatch, reject)
    with pytest.raises(ExtractionFailure) as caught: extractor.extract([])
    assert caught.value.provider_reason == reason
    assert caught.value.provider_parameter == parameter
    assert PRIVATE not in str(caught.value)
    assert len(calls) == 1 and calls[0]['response_format']['type'] == 'json_schema'


@pytest.mark.parametrize('body', [b'not-json', b'[]', b'{"error":"private"}', b'\xff', b'x' * (20 * 1024)])
def test_unrecognised_provider_body_retains_status_without_leaking_it(monkeypatch, body):
    extractor = provider(monkeypatch, lambda request: httpx.Response(400, content=body))
    with pytest.raises(ExtractionFailure) as caught: extractor.extract([])
    assert caught.value.provider_reason == 'invalid_request'
    assert caught.value.provider_parameter is None


def test_provider_reason_is_saved_and_logged_without_response_prose(harness, monkeypatch, caplog):
    client, app, *_ = harness
    message = 'Schema produces a constraint with too many states. ' + PRIVATE
    app.state.worker.extractor = provider(monkeypatch,
        lambda request: httpx.Response(400, json={'error': {'message': message}}))
    queued = upload(client).json()
    with caplog.at_level(logging.WARNING): app.state.worker.run_once()
    result = client.get('/api/v1/cv/operations/' + queued['operation_id']).json()
    error = result['error']
    assert error['provider_reason'] == 'schema_too_complex' and error['provider_parameter'] == 'schema'
    assert error['provider_status_code'] == 400 and not error['repair_attempted']
    assert client.get('/api/v1/cv').json()['cvs'][0]['error'] == error
    assert PRIVATE not in caplog.text + json.dumps(result)
    assert 'provider_reason=schema_too_complex provider_parameter=schema' in caplog.text


@pytest.mark.parametrize('exception,category', [
    (httpx.ReadTimeout, 'timeout'), (httpx.ConnectTimeout, 'timeout'),
    # The SDK wraps failures during send as connection errors.
    (httpx.ConnectError, 'connection_error'), (httpx.ReadError, 'connection_error'),
])
def test_transport_failure_categories(monkeypatch, exception, category):
    def fail(request):
        raise exception(PRIVATE, request=request)
    extractor = provider(monkeypatch, fail)
    with pytest.raises(ExtractionFailure) as caught:
        extractor.extract([])
    assert caught.value.stage == 'model_request'
    assert caught.value.category == category
    assert caught.value.provider_status_code is None
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize('body,stage,category', [
    (b'not-json', 'response_decode', 'invalid_json'),
    (b'\xff', 'response_decode', 'invalid_json'),
    (b'[]', 'response_decode', 'invalid_response'),
    (b'{}', 'response_decode', 'invalid_response'),
    (b'{"choices": []}', 'response_decode', 'invalid_response'),
    (b'{"choices": [null]}', 'response_decode', 'invalid_response'),
    (b'{"choices": [{}]}', 'response_decode', 'invalid_response'),
    (b'{"choices": [{"finish_reason": "length"}]}', 'response_decode', 'incomplete_output'),
    (b'{"choices": [{"finish_reason": "stop", "message": {"content": null}}]}', 'response_decode', 'invalid_response'),
    (b'{"choices": [{"finish_reason": "stop", "message": {"content": "bad-json"}}]}', 'content_decode', 'invalid_json'),
    (b'x' * (1024 * 1024 + 1), 'model_request', 'response_too_large'),
])
def test_response_failure_stages(monkeypatch, body, stage, category):
    extractor = provider(monkeypatch, lambda request: httpx.Response(200, content=body))
    with pytest.raises(ExtractionFailure) as caught:
        extractor.extract([])
    assert (caught.value.stage, caught.value.category) == (stage, category)


def test_unconfigured_category(monkeypatch):
    monkeypatch.delenv('CV_LLM_MODEL', raising=False)
    with pytest.raises(ExtractionFailure) as caught:
        Extractor().extract([])
    assert (caught.value.stage, caught.value.category) == ('model_request', 'not_configured')


def test_stream_transport_error(monkeypatch):
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadError(PRIVATE)
            yield b''
    extractor = provider(monkeypatch, lambda request: httpx.Response(200, stream=BrokenStream()))
    with pytest.raises(ExtractionFailure) as caught:
        extractor.extract([])
    assert (caught.value.stage, caught.value.category) == ('model_request', 'transport_error')


def test_response_wall_deadline(monkeypatch):
    extractor = provider(monkeypatch, lambda request: httpx.Response(200, content=b'{}'))
    ticks = iter([0, 100])
    monkeypatch.setattr('app.clients.extractor.time', SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(ExtractionFailure) as caught:
        extractor.extract([])
    assert (caught.value.stage, caught.value.category) == ('model_request', 'timeout')


def test_failure_diagnostics_survive_poll_list_reload_and_retry(harness, monkeypatch, caplog):
    client, app, *_ = harness
    extractor = provider(monkeypatch, lambda request: httpx.Response(401, text=PRIVATE))
    app.state.worker.extractor = extractor
    queued = upload(client).json()
    with caplog.at_level(logging.WARNING):
        app.state.worker.run_once()
    result = client.get('/api/v1/cv/operations/' + queued['operation_id']).json()
    error = result['error']
    assert error['code'] == 'extraction_failed' and error['retryable'] is True
    assert error['failure_stage'] == 'model_request'
    assert error['failure_category'] == 'provider_http_error'
    assert error['provider_status_code'] == 401
    assert client.get('/api/v1/cv/' + result['id']).json()['error'] == error
    assert client.get('/api/v1/cv').json()['cvs'][0]['error'] == error
    diagnostic = '\n'.join(record.message for record in caplog.records if record.name == 'app.workers.ingestion')
    assert result['id'] in diagnostic and result['operation_id'] in diagnostic
    assert 'stage=model_request category=provider_http_error provider_status_code=401' in diagnostic
    assert PRIVATE not in diagnostic + json.dumps(result)
    assert 'provider.example' not in diagnostic
    assert result['source_available'] and result['extraction_version'] == 0
    assert client.post('/api/v1/cv/operations/' + result['operation_id'] + '/retry',
                       json=mutation(result['version'])).status_code == 200
    # A successful retry clears the prior failure instead of leaving stale diagnostics.
    app.state.worker.extractor = harness[2]
    app.state.worker.run_once()
    recovered = client.get('/api/v1/cv/' + result['id']).json()
    assert recovered['status'] == 'ready' and recovered['error'] is None


@pytest.mark.parametrize('failure,stage,category', [
    ('source', 'source_read', 'source_unavailable'),
    ('parse', 'document_parse', 'invalid_document'),
    ('schema', 'extraction_validation', 'schema_validation'),
    ('evidence', 'extraction_validation', 'evidence_validation'),
    ('unexpected', 'model_request', 'unexpected_error'),
    ('admission', 'model_request', 'model_admission'),
])
def test_worker_failure_stages(harness, monkeypatch, failure, stage, category):
    from app.domain.model_usage import ModelAdmissionError
    client, app, extractor, *_ = harness
    queued = upload(client).json()
    if failure == 'source':
        app.state.files.remove(queued['id'])
    elif failure == 'parse':
        def fail_parse(*args):
            raise ValueError('Synthetic invalid document')
        app.state.worker.parser = fail_parse
    elif failure == 'schema':
        extractor.payload = {'items': [{'kind': 'skill'}]}
    elif failure == 'evidence':
        extractor.payload = {'items': [{'kind': 'skill', 'title': 'Python', 'description': 'A skill',
            'explicit': True, 'evidence': [{'block_id': 'missing', 'excerpt': 'Python'}]}]}
    else:
        def fail(*args, **kwargs):
            if failure == 'admission': raise ModelAdmissionError('Synthetic admission failure')
            raise RuntimeError(PRIVATE)
        monkeypatch.setattr(app.state.worker.model_usage, 'run', fail)
    app.state.worker.run_once()
    result = client.get('/api/v1/cv/' + queued['id']).json()
    assert result['status'] == 'failed'
    assert (result['error']['failure_stage'], result['error']['failure_category']) == (stage, category)
    assert result['error']['provider_status_code'] is None
    assert PRIVATE not in json.dumps(result)
