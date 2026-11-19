"""Synthetic SDK wire behavior: bounded reads, quota ownership and client lifetime."""
import asyncio
import gzip
import json

import httpx
import pytest

from elo_shared.model_sdk import async_model_response, sync_model_response

PAYLOAD = {'model': 'synthetic-model', 'messages': [{'role': 'user', 'content': 'Synthetic question'}],
           'max_tokens': 100, 'response_format': {'type': 'json_object'}}
BASE = 'https://provider.example.test/v1'


@pytest.mark.parametrize('asynchronous', [False, True])
def test_sdk_preserves_request_credentials_and_http_client(asynchronous):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]})
    payload = dict(PAYLOAD)
    if asynchronous:
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                async with async_model_response(http, BASE, 'synthetic-secret', 12, payload) as response:
                    assert json.loads(await response.aread())['choices'][0]['finish_reason'] == 'stop'
                assert not http.is_closed
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            with sync_model_response(http, BASE, 'synthetic-secret', 12, payload) as response:
                assert json.loads(response.read())['choices'][0]['finish_reason'] == 'stop'
            assert not http.is_closed
    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == BASE + '/chat/completions'
    assert json.loads(request.content) == payload
    assert request.extensions['timeout'] == dict(connect=12, read=12, write=12, pool=12)
    assert request.headers['authorization'] == 'Bearer synthetic-secret'
    assert payload == PAYLOAD


@pytest.mark.parametrize('asynchronous', [False, True])
@pytest.mark.parametrize('status', [200, 400, 429, 500, 302])
def test_sdk_bounds_streams_closes_them_and_does_not_retry_or_redirect(asynchronous, status):
    counts = {'chunks': 0, 'requests': 0, 'closed': False}
    class SyncStream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(1000):
                counts['chunks'] += 1
                yield b'x' * 1024
        def close(self): counts['closed'] = True
    class AsyncStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(1000):
                counts['chunks'] += 1
                yield b'x' * 1024
        async def aclose(self): counts['closed'] = True
    def handler(request):
        counts['requests'] += 1
        return httpx.Response(status, headers={'location': 'https://other.example.test', 'retry-after': '7'},
                              stream=AsyncStream() if asynchronous else SyncStream())
    if asynchronous:
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                async with async_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD) as response:
                    assert response.status_code == status
                    if status == 200:
                        async for chunk in response.aiter_bytes():
                            if counts['chunks'] == 4: break
                    else:
                        assert response.headers['retry-after'] == '7'
                        assert len(response.content) <= 16 * 1024
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            with sync_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD) as response:
                assert response.status_code == status
                if status == 200:
                    for chunk in response.iter_bytes():
                        if counts['chunks'] == 4: break
                else:
                    assert response.headers['retry-after'] == '7'
                    assert len(response.content) <= 16 * 1024
    assert counts == {'chunks': 4 if status == 200 else 17, 'requests': 1, 'closed': True}


@pytest.mark.parametrize('asynchronous', [False, True])
def test_compressed_rejection_is_not_decoded_twice(asynchronous):
    raw = json.dumps({'error': {'message': 'Synthetic rejection'}}).encode()
    def handler(request):
        return httpx.Response(400, headers={'content-encoding': 'gzip'}, content=gzip.compress(raw))
    if asynchronous:
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                async with async_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD) as response:
                    assert response.content == raw
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            with sync_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD) as response:
                assert response.content == raw
@pytest.mark.parametrize('url,expected', [
    ('https://openrouter.ai/api/v1', 'synthetic-shared'),
    ('https://OPENROUTER.AI:443/api/v1', 'synthetic-shared'),
    ('https://openrouter.ai:8443/api/v1', ''),
    ('http://openrouter.ai/api/v1', ''),
    ('https://openrouter.ai.example/api/v1', ''),
    ('https://example.test/openrouter.ai/api/v1', ''),
    ('https://user@openrouter.ai/api/v1', ''),
    ('https://openrouter.ai/api/v1?x=y', ''),
    ('https://openrouter.ai/api/v1#fragment', ''),
    ('https://api.openai.com/v1', ''),
])
def test_shared_openrouter_key_only_applies_to_trusted_origin(monkeypatch, url, expected):
    from elo_shared.model_sdk import resolve_model_api_key
    monkeypatch.setenv('OPENROUTER_API_KEY', 'synthetic-shared')
    assert resolve_model_api_key(url, '') == expected
    assert resolve_model_api_key(url, 'synthetic-specific') == 'synthetic-specific'


def test_shared_openrouter_key_can_be_left_blank(monkeypatch):
    from elo_shared.model_sdk import resolve_model_api_key
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    assert resolve_model_api_key('https://openrouter.ai/api/v1', '') == ''

@pytest.mark.parametrize('asynchronous', [False, True])
def test_usage_event_is_content_free_and_captured_before_domain_parse(asynchronous, caplog):
    import logging
    secret_text = 'private cv and secret answer'
    envelope = {'id': 'gen-synthetic', 'model': 'test/model',
        'choices': [{'finish_reason': 'stop', 'message': {'content': secret_text}}],
        'usage': {'prompt_tokens': 100, 'completion_tokens': 20,
                  'prompt_tokens_details': {'cached_tokens': 30},
                  'completion_tokens_details': {'reasoning_tokens': 5}, 'cost': 0.012}}
    def handler(request): return httpx.Response(200, json=envelope)
    labels = {'service': 'cv', 'stage': 'extraction', 'prompt_version': 'v1'}
    with caplog.at_level(logging.INFO, logger='uvicorn.error.model_usage'):
        if asynchronous:
            async def run():
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                    async with async_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD, telemetry=labels) as response:
                        await response.aread()
            asyncio.run(run())
        else:
            with httpx.Client(transport=httpx.MockTransport(handler)) as http:
                with sync_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD, telemetry=labels) as response:
                    response.read()
    assert len(caplog.records) == 1
    log = caplog.records[0].getMessage()
    event = json.loads(log.removeprefix('model_usage '))
    assert event['service'] == 'cv' and event['stage'] == 'extraction'
    assert (event['input_tokens'], event['cached_input_tokens'], event['output_tokens'], event['reasoning_tokens']) == (100, 30, 20, 5)
    assert event['finish_status'] == 'stop' and event['provider_cost'] == 0.012
    assert event['request_bytes'] > 0 and event['schema_bytes'] > 0
    assert secret_text not in log and 'Synthetic question' not in log and 'synthetic-secret' not in log


def test_usage_unknown_on_malformed_response_and_timeout(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger='uvicorn.error.model_usage'):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'not json'))) as http:
            with sync_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD, telemetry={'service': 'cv', 'stage': 'extraction'}) as response:
                response.read()
        def timeout(request): raise httpx.ReadTimeout('private provider text', request=request)
        with httpx.Client(transport=httpx.MockTransport(timeout)) as http:
            with pytest.raises(httpx.ReadTimeout):
                with sync_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD, telemetry={'service': 'cv', 'stage': 'extraction'}):
                    pass
    events = [json.loads(record.getMessage().removeprefix('model_usage ')) for record in caplog.records]
    assert len(events) == 2
    assert all(event['input_tokens'] is None and event['output_tokens'] is None for event in events)
    assert events[1]['transport_failure'] == 'timeout'
    assert 'private provider text' not in caplog.text


def test_usage_captures_consumed_stream_once(caplog):
    import logging
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"usage":{"prompt_tokens":'
            yield b'9,"completion_tokens":3},"choices":[]}'
    with caplog.at_level(logging.INFO, logger='uvicorn.error.model_usage'):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream()))) as http:
            with sync_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD, telemetry={'service': 'cv', 'stage': 'extraction'}) as response:
                assert b''.join(response.iter_bytes()).startswith(b'{')
    event = json.loads(caplog.records[0].getMessage().removeprefix('model_usage '))
    assert event['input_tokens'] == 9 and event['output_tokens'] == 3


def test_operation_scope_is_concurrent_and_does_not_log_original_ids(caplog):
    import logging
    from elo_shared.model_telemetry import operation_scope
    async def worker(identifier):
        with operation_scope(identifier):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'usage': {'prompt_tokens': 2}}))) as http:
                for _ in range(2):
                    async with async_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD, telemetry={'service': 'roadmap', 'stage': 'OutlineDraft'}) as response:
                        await response.aread()
                    await asyncio.sleep(0)
    async def run():
        await asyncio.gather(worker('random-operation-a'), worker('random-operation-b'))
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}))) as http:
            async with async_model_response(http, BASE, 'synthetic-secret', 12, PAYLOAD) as response:
                await response.aread()
    with caplog.at_level(logging.INFO, logger='uvicorn.error.model_usage'):
        asyncio.run(run())
    events = [json.loads(record.getMessage().removeprefix('model_usage ')) for record in caplog.records]
    ids = [event['operation_id'] for event in events]
    assert len(set(ids[:4])) == 2 and all(ids[:4].count(value) == 2 for value in ids[:4])
    assert ids[4] is None
    assert 'random-operation-a' not in caplog.text and 'random-operation-b' not in caplog.text


def test_schema_version_fingerprints_structured_and_json_object_schemas():
    from elo_shared.model_telemetry import fingerprint, schema_fingerprint
    schema = {'type': 'object', 'properties': {'value': {'type': 'string'}}}
    native = {'response_format': {'type': 'json_schema', 'json_schema': {'schema': schema}}}
    compatible = {'response_format': {'type': 'json_object'}, 'messages': [{'role': 'system', 'content': 'Return JSON.\nJSON schema: ' + json.dumps(schema)}]}
    responses = {'text': {'format': {'type': 'json_schema', 'schema': schema}}}
    assert schema_fingerprint(native) == schema_fingerprint(compatible) == schema_fingerprint(responses) == fingerprint(schema)
    assert schema_fingerprint({'response_format': {'type': 'json_object'}, 'messages': []}) is None
    assert schema_fingerprint({'response_format': {'type': 'json_object'}, 'messages': [{'role': 'system', 'content': 'JSON schema: private'}]}) is None
