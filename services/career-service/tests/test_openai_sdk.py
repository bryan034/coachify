"""SDK transport retains the application's validation, privacy and retry bounds."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest
from openai import AsyncOpenAI
from app.ai.adapter import AIAdapter, AIError, Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.schemas.workspace import WorkspaceView


def test_browser_fixture_is_an_actual_canonical_api_response():
    path=Path(__file__).resolve().parents[3]/'apps/frontend/tests/fixtures/career-workspace.json'
    value=json.loads(path.read_text())
    assert WorkspaceView.model_validate(value).model_dump(mode='json',by_alias=True)==value


@pytest.mark.parametrize('stage',['context_route','context_answer','opportunity_plan','opportunity_structure','goal_edit'])
def test_default_local_configuration_constrains_every_downstream_stage(monkeypatch,stage):
    monkeypatch.setenv('CAREER_LLM_PROVIDER','local')
    settings=AISettings.from_env()
    assert settings.model=='deepseek-r1:1.5b'
    payload=AIAdapter(settings,None)._payload(AIInput(stage=stage,context='{}',conversation=[{'role':'user','content':'Synthetic question'}]))
    format=payload['response_format']
    assert format['type']=='json_schema' and format['json_schema']['strict']
    assert format['json_schema']['schema']['additionalProperties'] is False


@pytest.mark.parametrize('parameter',['max_tokens','max_completion_tokens'])
def test_sdk_model_switch_preserves_request_shape_and_does_not_own_http_client(monkeypatch,parameter):
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
            assert isinstance(adapter.sdk,AsyncOpenAI) and adapter.sdk.max_retries==0
            await adapter.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hello'}]),Operation('synthetic','1','chat'),current_revision=lambda:'1')
            payload=json.loads(calls[0].content)
            assert payload['model']=='synthetic-other-model' and parameter in payload
            assert str(calls[0].url)=='https://compatible.example.test/v1/chat/completions'
            await adapter.sdk.close()
            assert not http.is_closed
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
def test_sdk_streams_are_bounded_and_closed(status):
    class Stream(httpx.AsyncByteStream):
        count=0
        closed=False
        async def __aiter__(self):
            for _ in range(1000):
                self.count+=1
                yield b'x'*1024
        async def aclose(self):self.closed=True
    async def run():
        stream=Stream()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(status,stream=stream))) as http:
            adapter=AIAdapter(AISettings(enabled=True,provider='local'),http)
            with pytest.raises(AIError) as caught:
                await adapter.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hello'}]),Operation('synthetic','1','chat'),current_revision=lambda:'1')
            assert caught.value.code==('output_limit' if status==200 else 'provider_configuration')
            assert stream.closed and stream.count<=(129 if status==200 else 17)
    asyncio.run(run())


def test_compressed_sdk_rejections_keep_safe_codes_without_double_decoding():
    import gzip
    async def run():
        raw=json.dumps({'error':{'code':'model_not_found','message':'PRIVATE provider text'}}).encode()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(404,
                headers={'content-encoding':'gzip'},content=gzip.compress(raw)))) as http:
            adapter=AIAdapter(AISettings(enabled=True,provider='local'),http)
            with pytest.raises(AIError) as caught:
                await adapter.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hello'}]),Operation('synthetic','1','chat'),current_revision=lambda:'1')
            assert caught.value.code=='model_unavailable'
            assert caught.value.__context__ is None
    asyncio.run(run())
