"""Summary decoding uses the blocks contract, without relaxing provenance."""
import asyncio
import json
import httpx
import pytest
from app.ai.adapter import AIAdapter
from app.ai.errors import AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.usage import input_tokens
from app.workflows.goal_summary import summarize
from tests.test_goal_chat_presentation import environment


def settings(**values):
    return AISettings(**{'enabled': True, 'model': 'synthetic', 'api_key': 'synthetic',
        'base_url': 'https://example.test/v1', 'response_mode': 'json_schema_strict',
        'context_tokens': 16384, 'max_output_tokens': 8192, **values})


@pytest.mark.parametrize('mode', ['json_schema', 'json_schema_strict'])
def test_summary_sends_native_blocks_grammar_and_explicit_prompt(mode):
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
    assert 'Never put references at the' in payload['messages'][0]['content']
    assert input_tokens(payload) + payload['max_tokens'] + 1638 <= 16384
    assert output['json_schema']['strict'] is (mode == 'json_schema_strict')


def test_json_object_mode_is_not_upgraded_without_provider_support():
    payload = AIAdapter(settings(response_mode='json_object'), None)._payload(AIInput(stage='goal_summary', context='{}'))
    assert payload['response_format'] == {'type': 'json_object'}
    assert 'JSON schema:' in payload['messages'][0]['content']


@pytest.mark.parametrize('defect', [None, 'wrong_shape', 'unknown_reference', 'no_research'])
def test_real_adapter_summary_preserves_validation_and_attaches_only_saved_links(defect):
    async def run():
        request, body, checks, _, _ = environment()
        calls = []
        output = {'blocks': [{'label': 'Interview expectations', 'text': 'An interview is reported.', 'references': ['research_0']}]}
        if defect == 'wrong_shape': output = {'role': 'Analyst', 'references': ['research_0']}
        if defect == 'unknown_reference': output['blocks'][0]['references'] = ['invented_fact']
        if defect == 'no_research': output['blocks'][0]['references'] = ['goal']
        if defect and defect!='wrong_shape':output['blocks'][0]['text']='UNAPPROVED_MODEL_CLAIM'
        def handler(http_request):
            calls.append(json.loads(http_request.content))
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            request.app.state.ai = AIAdapter(settings(), client)
            if defect:
                result=await summarize(request, 'owner', body)
                assert 'UNAPPROVED_MODEL_CLAIM' not in result['reply']
                assert 'Showing saved facts' in result['reply']
                assert 'An interview is reported. [Source](<https://example.test/job>)' in result['reply']
            else:
                result = await summarize(request, 'owner', body)
                assert '#### Interview expectations\n\nAn interview is reported.' in result['reply']
                assert '[Source](<https://example.test/job>)' in result['reply']
                assert result['reply'].endswith('Ask me anything about this goal set!')
                assert len(calls) == 1
        assert calls and all(item['response_format']['type'] == 'json_schema' for item in calls)
        assert all(item['response_format']['json_schema']['schema']['$defs']['SummaryBlock']['properties']['references']['items']['enum']==['goal','coverage_interviews','research_0'] for item in calls)
        assert len(checks) >= 3
    asyncio.run(run())


def test_summary_uses_tokens_for_full_prompt_instead_of_utf8_bytes():
    context = json.dumps({'goal': {'role': 'Analyst', 'summary': 'SQL data analysis. ' * 650}})
    adapter = AIAdapter(settings(), None)
    payload = adapter._payload(AIInput(stage='goal_summary', context=context))
    input_budget = 16384 - payload['max_tokens'] - 1638
    assert sum(len(message['content'].encode()) for message in payload['messages']) > input_budget
    assert input_tokens(payload) <= input_budget
    assert json.loads(payload['messages'][1]['content'])['context']['goal']['summary'] == 'SQL data analysis. ' * 650
