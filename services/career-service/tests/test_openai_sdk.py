"""SDK transport retains the application's validation, privacy and retry bounds."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from app.ai.adapter import AIAdapter, AIError, Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.schemas.workspace import WorkspaceView
from app.schemas.analysis import ResearchSource
from app.ai.opportunity_contracts import structure_input


def test_browser_fixture_is_an_actual_canonical_api_response():
    path=Path(__file__).resolve().parents[3]/'apps/frontend/tests/fixtures/career-workspace.json'
    value=json.loads(path.read_text())
    assert WorkspaceView.model_validate(value).model_dump(mode='json',by_alias=True)==value


@pytest.mark.parametrize('stage',['context_route','context_answer','opportunity_plan','opportunity_structure','goal_edit'])
def test_default_local_configuration_constrains_every_downstream_stage(monkeypatch,stage):
    monkeypatch.setenv('CAREER_LLM_PROVIDER','local')
    settings=AISettings.from_env()
    assert settings.model=='deepseek-r1:1.5b'
    context=structure_input({},'internship_insights',[ResearchSource(source_id='synthetic',platform='other',url='https://example.test/report',evidence='Example interns report mentorship.')]) if stage=='opportunity_structure' else {}
    payload=AIAdapter(settings,None)._payload(AIInput(stage=stage,context=json.dumps(context),conversation=[{'role':'user','content':'Synthetic question'}]))
    format=payload['response_format']
    assert format['type']=='json_schema' and format['json_schema']['strict']
    assert format['json_schema']['schema']['additionalProperties'] is False


@pytest.mark.parametrize('parameter',['max_tokens','max_completion_tokens'])
def test_sdk_model_switch_preserves_request_shape(monkeypatch,parameter):
    monkeypatch.setenv('CAREER_LLM_PROVIDER','compatible')
    monkeypatch.setenv('CAREER_LLM_API_KEY','synthetic-key')
    monkeypatch.setenv('CAREER_LLM_BASE_URL','https://compatible.example.test/v1')
    monkeypatch.setenv('CAREER_LLM_MODEL','synthetic-other-model')
    monkeypatch.setenv('CAREER_LLM_TOKEN_PARAMETER',parameter)
    async def run():
        calls=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"Hello"}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            adapter=AIAdapter(AISettings.from_env(),http)
            await adapter.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hello'}]),Operation('synthetic','1','chat'),current_revision=lambda:'1')
            payload=json.loads(calls[0].content)
            assert payload['model']=='synthetic-other-model' and parameter in payload
            assert str(calls[0].url)=='https://compatible.example.test/v1/chat/completions'
    asyncio.run(run())


@pytest.mark.parametrize('envelope',[None,[],{'choices':[None]},{'choices':[{'finish_reason':'stop','message':[]}]},
    {'choices':[{'finish_reason':'stop','message':{'reasoning_content':'PRIVATE reasoning','content':None}}]}])
def test_malformed_sdk_envelopes_are_safe_terminal_errors(envelope):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=envelope))) as http:
            adapter=AIAdapter(AISettings(enabled=True,provider='local'),http)
            with pytest.raises(AIError) as caught:
                await adapter.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hello'}]),Operation('synthetic','1','chat'),current_revision=lambda:'1')
            assert caught.value.code=='invalid_output'
            assert 'PRIVATE' not in str(caught.value)
    asyncio.run(run())


@pytest.mark.parametrize('status',[200,400])
def test_career_reports_distinct_errors_for_oversized_success_and_rejection(status):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(1000):
                yield b'x'*1024
    async def run():
        stream=Stream()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(status,stream=stream))) as http:
            adapter=AIAdapter(AISettings(enabled=True,provider='local'),http)
            with pytest.raises(AIError) as caught:
                await adapter.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hello'}]),Operation('synthetic','1','chat'),current_revision=lambda:'1')
            assert caught.value.code==('output_limit' if status==200 else 'provider_configuration')
    asyncio.run(run())
