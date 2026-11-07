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
@pytest.mark.parametrize('local', [False, True])
def test_sdk_preserves_request_extensions_credentials_and_http_client(asynchronous, local):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]})
    payload = {**PAYLOAD, 'thinking': {'type': 'disabled'}}
    if asynchronous:
        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
                async with async_model_response(http, BASE, 'synthetic-secret', 12, payload, local=local) as response:
                    assert json.loads(await response.aread())['choices'][0]['finish_reason'] == 'stop'
                assert not http.is_closed
        asyncio.run(run())
    else:
        with httpx.Client(transport=httpx.MockTransport(handler)) as http:
            with sync_model_response(http, BASE, 'synthetic-secret', 12, payload, local=local) as response:
                assert json.loads(response.read())['choices'][0]['finish_reason'] == 'stop'
            assert not http.is_closed
    assert len(calls) == 1
    request = calls[0]
    assert str(request.url) == BASE + '/chat/completions'
    assert json.loads(request.content) == payload
    assert request.extensions['timeout'] == dict(connect=12, read=12, write=12, pool=12)
    if local:
        assert 'authorization' not in request.headers
    else:
        assert request.headers['authorization'] == 'Bearer synthetic-secret'
    assert payload['thinking'] == {'type': 'disabled'}  # SDK must not mutate caller input.


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
