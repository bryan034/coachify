"""Local summary decoding uses the blocks contract, without relaxing provenance."""
import asyncio
import json
import httpx
import pytest
from app.ai.adapter import AIAdapter, AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.usage import input_tokens
from app.workflows.goal_summary import summarize
from tests.test_goal_chat_presentation import environment


def settings(**values):
    return AISettings(**{'enabled': True, 'provider': 'local', 'model': 'synthetic',
        'base_url': 'http://127.0.0.1:11434/v1', 'response_mode': 'json_object',
        'context_tokens': 16384, **values})


@pytest.mark.parametrize('mode', ['json_object', 'json_schema', 'json_schema_strict'])
def test_local_summary_sends_native_blocks_grammar_and_explicit_prompt(mode):
    payload = AIAdapter(settings(response_mode=mode), None)._payload(AIInput(stage='goal_summary', context='{}'))
    output = payload['response_format']
    assert output['type'] == 'json_schema'
    schema = output['json_schema']['schema']
    assert schema['required'] == ['blocks']
    assert set(schema['properties']) == {'blocks'}
    assert schema['additionalProperties'] is False
    block = schema['$defs']['SummaryBlock']
    assert set(block['required']) == {'label', 'text', 'references'}
    assert block['additionalProperties'] is False
    assert block['properties']['references']['minItems'] == 1
    assert schema['properties']['blocks']['maxItems'] == 12
    assert 'JSON schema:' in payload['messages'][0]['content']
    assert 'Never put references at the' in payload['messages'][0]['content']
    assert input_tokens(payload) + payload['max_tokens'] + 1638 <= 16384
    if mode == 'json_object': assert output['json_schema']['strict'] is True


@pytest.mark.parametrize('provider', ['deepseek', 'compatible'])
def test_cloud_json_mode_is_not_upgraded_without_provider_support(provider):
    payload = AIAdapter(settings(provider=provider, base_url='https://api.deepseek.com/v1', api_key='synthetic'), None)._payload(AIInput(stage='goal_summary', context='{}'))
    assert payload['response_format'] == {'type': 'json_object'}
    assert 'JSON schema:' in payload['messages'][0]['content']


@pytest.mark.parametrize('defect', [None, 'wrong_shape', 'unknown_reference', 'no_research'])
def test_real_local_adapter_summary_preserves_validation_and_attaches_only_saved_links(defect):
    async def run():
        request, body, checks, _, _ = environment()
        calls = []
        output = {'blocks': [{'label': 'Interview expectations', 'text': 'An interview is reported.', 'references': ['research_0']}]}
        if defect == 'wrong_shape': output = {'role': 'Analyst', 'references': ['research_0']}
        if defect == 'unknown_reference': output['blocks'][0]['references'] = ['invented_fact']
        if defect == 'no_research': output['blocks'][0]['references'] = ['goal']
        def handler(http_request):
            calls.append(json.loads(http_request.content))
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            request.app.state.ai = AIAdapter(settings(), client)
            if defect:
                with pytest.raises(AIError, match='invalid_output'):
                    await summarize(request, 'owner', body)
            else:
                result = await summarize(request, 'owner', body)
                assert '**Interview expectations:** An interview is reported.' in result['reply']
                assert '[Source](<https://example.test/job>)' in result['reply']
                assert result['reply'].endswith('Ask me anything about this goal set!')
                assert len(calls) == 1
        assert calls and all(item['response_format']['type'] == 'json_schema' for item in calls)
        assert len(checks) >= 3
    asyncio.run(run())


def test_local_summary_uses_tokens_for_full_prompt_instead_of_utf8_bytes():
    context = json.dumps({'goal': {'role': 'Analyst', 'summary': 'SQL data analysis. ' * 650}})
    adapter = AIAdapter(settings(), None)
    payload = adapter._payload(AIInput(stage='goal_summary', context=context))
    input_budget = 16384 - payload['max_tokens'] - 1638
    assert sum(len(message['content'].encode()) for message in payload['messages']) > input_budget
    assert input_tokens(payload) <= input_budget
    assert json.loads(payload['messages'][1]['content'])['context']['goal']['summary'] == 'SQL data analysis. ' * 650
