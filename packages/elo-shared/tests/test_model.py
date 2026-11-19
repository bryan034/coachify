"""Synthetic model endpoints for independent Assessment/Roadmap configuration."""
import asyncio
import json
import httpx
import pytest
from pydantic import BaseModel
from elo_shared.runtime import Model

class Answer(BaseModel):
    reply:str


@pytest.mark.parametrize('prefix', ['ASSESSMENT', 'ROADMAP'])
@pytest.mark.parametrize('embedded_status,code,status', [(429, 'model_quota', 429), (402, 'model_provider', 503),
    (401, 'model_provider', 503), (400, 'model_provider', 503), (503, 'model_provider', 503)])
def test_embedded_provider_errors_do_not_spend_schema_retries(monkeypatch, prefix, embedded_status, code, status):
    from elo_shared.runtime import Problem
    monkeypatch.setenv(prefix + '_LLM_API_KEY', 'synthetic-key')
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={'error': {'code': embedded_status, 'message': 'PRIVATE provider prose'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(Problem) as caught:
                await Model(client, prefix).generate(Answer, 'Answer.', {})
        assert caught.value.code == code and caught.value.status == status
        assert caught.value.retry_after == (30 if embedded_status == 429 else None)
        assert 'PRIVATE' not in caught.value.detail and len(calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize('prefix', ['ASSESSMENT', 'ROADMAP'])
def test_embedded_rate_limit_keeps_provider_cooldown(monkeypatch, prefix):
    from elo_shared.runtime import Problem
    monkeypatch.setenv(prefix + '_LLM_API_KEY', 'synthetic-key')
    async def run():
        def handler(request):
            return httpx.Response(200, headers={'retry-after': '600'}, json={'error': {'code': 429}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(Problem) as caught:
                await Model(client, prefix).generate(Answer, 'Answer.', {})
        assert caught.value.code == 'model_quota' and caught.value.retry_after == 600
    asyncio.run(run())

@pytest.mark.parametrize('prefix',['ASSESSMENT','ROADMAP'])
def test_model_endpoint_json_contract_and_credentials(monkeypatch,prefix):
    base='https://openrouter.ai/api/v1'
    monkeypatch.setenv(prefix+'_LLM_BASE_URL',base)
    monkeypatch.setenv(prefix+'_LLM_MODEL','synthetic-cloud-model')
    monkeypatch.setenv(prefix+'_LLM_API_KEY','preserved-cloud-key')
    async def run():
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"Synthetic answer"}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model=Model(client,prefix)
            assert (await model.generate(Answer,'Answer the question.',{'question':'Synthetic question'})).reply=='Synthetic answer'
        request=calls[0];payload=json.loads(request.content)
        assert str(request.url)==base+'/chat/completions'
        assert request.headers['authorization']=='Bearer preserved-cloud-key' and model.timeout==55
        assert payload['model']=='synthetic-cloud-model'
        assert payload['response_format']=={'type':'json_object'}
        assert 'JSON schema:' in payload['messages'][0]['content']
        assert 'reasoning_effort' not in payload and 'thinking' not in payload
    asyncio.run(run())

@pytest.mark.parametrize('prefix',['ASSESSMENT','ROADMAP'])
def test_development_http_is_only_for_explicit_fixtures_and_still_needs_a_key(monkeypatch,prefix):
    monkeypatch.setenv(prefix+'_LLM_BASE_URL','http://model-fixture:9000/v1')
    monkeypatch.setenv(prefix+'_LLM_ALLOW_HTTP','true')
    monkeypatch.setenv('APP_ENV','production')
    with pytest.raises(ValueError,match='HTTPS'):Model(None,prefix)
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv(prefix+'_LLM_ALLOW_HTTP','false')
    with pytest.raises(ValueError,match='HTTPS'):Model(None,prefix)
    monkeypatch.setenv(prefix+'_LLM_ALLOW_HTTP','true')
    monkeypatch.setenv(prefix+'_LLM_MODEL','synthetic-fixture-model')
    monkeypatch.setenv(prefix+'_LLM_API_KEY','')
    assert not Model(None,prefix).configured
    monkeypatch.setenv(prefix+'_LLM_API_KEY','synthetic-fixture-key')
    assert Model(None,prefix).configured


def test_callers_can_raise_the_output_limit_and_the_default_is_unchanged(monkeypatch):
    monkeypatch.setenv('ROADMAP_LLM_API_KEY','synthetic-key')
    async def run():
        calls=[]
        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"Synthetic answer"}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model=Model(client,'ROADMAP')
            await model.generate(Answer,'Answer.',{})
            await model.generate(Answer,'Answer.',{},max_tokens=24000)
        assert [call['max_tokens'] for call in calls]==[8192,24000]
    asyncio.run(run())


def test_token_parameter_can_be_selected_for_models_that_require_it(monkeypatch):
    monkeypatch.setenv('ROADMAP_LLM_API_KEY','synthetic-key')
    monkeypatch.setenv('ROADMAP_LLM_BASE_URL','https://api.openai.com/v1')
    monkeypatch.setenv('ROADMAP_LLM_TOKEN_PARAMETER','max_completion_tokens')
    async def run():
        calls=[]
        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"Synthetic answer"}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await Model(client,'ROADMAP').generate(Answer,'Answer.',{},max_tokens=24000)
            monkeypatch.setenv('ROADMAP_LLM_TOKEN_PARAMETER','temperature')
            with pytest.raises(ValueError):Model(client,'ROADMAP')
        assert calls[0]['max_completion_tokens']==24000 and 'max_tokens' not in calls[0]
    asyncio.run(run())


@pytest.mark.parametrize('prefix',['ASSESSMENT','ROADMAP'])
@pytest.mark.parametrize('base,override,expected',[
    ('https://openrouter.ai/api/v1','','synthetic-shared'),
    ('https://openrouter.ai/api/v1','synthetic-specific','synthetic-specific'),
    ('https://api.openai.com/v1','',''),
])
def test_adviser_models_use_shared_key_only_for_openrouter(monkeypatch,prefix,base,override,expected):
    monkeypatch.setenv(prefix+'_LLM_BASE_URL',base)
    monkeypatch.setenv(prefix+'_LLM_MODEL','@preset/synthetic')
    monkeypatch.setenv(prefix+'_LLM_API_KEY',override)
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic-shared')
    async def run():
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"OK"}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model=Model(client,prefix)
            assert model.configured is bool(expected)
            if expected:
                await model.generate(Answer,'Answer.',{})
                assert calls[0].headers['authorization']=='Bearer '+expected
                assert json.loads(calls[0].content)['model']=='@preset/synthetic'
            else:
                from elo_shared.runtime import Problem
                with pytest.raises(Problem):await model.generate(Answer,'Answer.',{})
                assert calls==[]
    asyncio.run(run())


@pytest.mark.parametrize('prefix', ['ASSESSMENT', 'ROADMAP'])
def test_worker_correlates_requests_and_records_prompt_and_schema_versions(monkeypatch, caplog, prefix):
    import logging
    from types import SimpleNamespace
    from elo_shared.runtime import MemoryStore, begin, run_operation
    class Body(BaseModel):
        expected_version: int
        mutation_id: str
    class Upstream:
        async def account(self, token): return {'id': 'owner'}
    monkeypatch.setenv(prefix + '_LLM_API_KEY', 'synthetic-key')
    async def run():
        store = MemoryStore()
        begin(store, 'owner', Body(expected_version=0, mutation_id='opaque-operation'), 'plan')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"reply":"ok"}'}}]}))) as client:
            model = Model(client, prefix)
            app = SimpleNamespace(state=SimpleNamespace(store=store, upstream=Upstream(), model=model, slots=asyncio.Semaphore(1)))
            async def worker(row, account):
                await model.generate(Answer, 'Fixed prompt.', {'question': 'private synthetic question'})
                await model.generate(Answer, 'Fixed prompt.', {'question': 'different private question'})
                return row
            await run_operation(app, 'owner', 'synthetic-token', worker)
        assert store.load('owner')['last_operation']['status'] == 'succeeded'
    with caplog.at_level(logging.INFO, logger='uvicorn.error.model_usage'):
        asyncio.run(run())
    events = [json.loads(record.getMessage().removeprefix('model_usage ')) for record in caplog.records if record.name == 'uvicorn.error.model_usage']
    assert len(events) == 2 and events[0]['operation_id'] == events[1]['operation_id']
    assert events[0]['operation_id'].startswith('sha256:')
    assert events[0]['prompt_version'] == events[1]['prompt_version'] and events[0]['prompt_version'].startswith('sha256:')
    assert events[0]['schema_version'] == events[1]['schema_version'] and events[0]['schema_version'].startswith('sha256:')
    assert 'opaque-operation' not in caplog.text and 'private synthetic question' not in caplog.text and 'Fixed prompt' not in caplog.text


@pytest.mark.parametrize('prefix', ['ASSESSMENT', 'ROADMAP'])
def test_schema_repair_charges_another_call_before_provider_dispatch(monkeypatch, tmp_path, prefix):
    from elo_shared.model_budget import budget_owner, reserve_provider_call
    from elo_shared.runtime import Problem
    monkeypatch.setenv(prefix + '_LLM_API_KEY', 'synthetic')
    monkeypatch.setenv('MODEL_BUDGET_PATH', str(tmp_path / 'usage.sqlite3'))
    monkeypatch.setenv('MODEL_BUDGET_OWNER_CALLS_PER_DAY', '1')
    calls = []
    def invalid(request):
        calls.append(request)
        return httpx.Response(200, json={'choices': [{'finish_reason':'stop', 'message':{'content':'{}'}}]})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(invalid)) as client:
            with budget_owner('owner'), pytest.raises(Problem) as denied:
                await Model(client, prefix, reserve_call=reserve_provider_call).generate(Answer, 'Answer.', {})
            assert denied.value.code == 'model_daily_allowance' and denied.value.status == 429
    asyncio.run(exercise())
    assert len(calls) == 1
