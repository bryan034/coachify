"""Provider rejection under HTTP 200 must not become an output repair."""
import asyncio
import json

import httpx
import pytest

from app.ai.adapter import AIAdapter, AIError, Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput


@pytest.mark.parametrize('embedded_status,expected', [(400, 'provider_configuration'),
    (401, 'provider_auth'), (402, 'provider_access'), (403, 'provider_auth'), (404, 'model_unavailable'),
    (429, 'rate_limited'), (503, 'unavailable')])
@pytest.mark.parametrize('choice_error', [False, True])
def test_embedded_rejection_bypasses_correction_and_provider_retries(embedded_status, expected, choice_error):
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            error = {'code': embedded_status, 'message': 'PRIVATE provider prose'}
            body = {'error': error}
            if choice_error:
                body = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}, 'error': error}]}
            return httpx.Response(200, json=body)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = AIAdapter(AISettings(enabled=True, api_key='synthetic'), client)
            operation = Operation('synthetic', '1', 'jd_extraction')
            with pytest.raises(AIError) as raised:
                await adapter.generate(AIInput(stage='jd_extraction', source_text='Analyst. SQL required.'),
                    operation, current_revision=lambda: '1')
        error = raised.value
        assert error.code == expected and len(calls) == 1
        assert operation.status == 'failed'
        assert error.provider_error['http_status'] == 200
        assert 'PRIVATE' not in json.dumps(error.provider_error)
        assert error.retry_after == (30 if embedded_status == 429 else None)
    asyncio.run(run())


def test_successful_responses_api_error_null_is_accepted():
    adapter = AIAdapter(AISettings(enabled=True, api_key='synthetic'), None)
    body = {'object': 'response', 'status': 'completed', 'error': None, 'output': [
        {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '{"reply":"OK"}'}]}]}
    assert json.loads(adapter._content(json.dumps(body))) == {'reply': 'OK'}


@pytest.mark.parametrize('code', [402, 'insufficient_quota', 'payment_required'])
def test_permanent_quota_rejection_does_not_enter_workflow_wait(code):
    from app.ai.adapter import quota_progress
    async def run():
        calls = []
        progress = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={'error': {'code': code, 'message': 'PRIVATE'}})
        async def no_wait(_):
            pytest.fail('Permanent quota errors must not suspend the deadline and retry.')
        token = quota_progress.set(progress.append)
        try:
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = AIAdapter(AISettings(enabled=True, api_key='synthetic'), client, sleep=no_wait)
                with pytest.raises(AIError) as caught:
                    await adapter.generate(AIInput(stage='jd_extraction', source_text='Analyst. SQL required.'),
                        Operation('synthetic', '1', 'jd_extraction'), current_revision=lambda: '1')
            assert caught.value.code == 'provider_access' and not caught.value.retryable
            assert len(calls) == 1 and progress == []
        finally:
            quota_progress.reset(token)
    asyncio.run(run())


@pytest.mark.parametrize('header,expected', [('600', 600), ('nan', 30), ('bad', 30), ('-3', 1), ('9000', 3600)])
def test_embedded_rate_limit_preserves_bounded_provider_cooldown(header, expected):
    async def run():
        def handler(request):
            return httpx.Response(200, headers={'retry-after': header}, json={'error': {'code': 429}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = AIAdapter(AISettings(enabled=True, api_key='synthetic'), client)
            with pytest.raises(AIError) as caught:
                await adapter._complete({'model': 'synthetic', 'messages': []}, owner='synthetic')
        assert caught.value.code == 'rate_limited' and caught.value.retry_after == expected
    asyncio.run(run())
