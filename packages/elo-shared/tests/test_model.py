"""Synthetic model endpoints for independent Assessment/Roadmap configuration."""
import asyncio
import json
import httpx
import pytest
from pydantic import BaseModel
from elo_shared import runtime
from elo_shared.runtime import Model, Problem

class Answer(BaseModel):
    reply:str

@pytest.mark.parametrize('prefix',['ASSESSMENT','ROADMAP'])
@pytest.mark.parametrize('provider',['local','gemini','deepseek'])
def test_model_endpoint_json_contract_and_credential_isolation(monkeypatch,prefix,provider):
    base={'local':'http://host.docker.internal:11434/v1','gemini':'https://generativelanguage.googleapis.com/v1beta/openai','deepseek':'https://api.deepseek.com/v1'}[provider]
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv(prefix+'_LLM_BASE_URL',base)
    monkeypatch.setenv(prefix+'_LLM_MODEL','elo-deepseek-r1:1.5b' if provider=='local' else 'synthetic-cloud-model')
    monkeypatch.setenv(prefix+'_LLM_ALLOW_HTTP','true' if provider=='local' else 'false')
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
        if provider=='local':
            assert 'authorization' not in request.headers
            assert payload['model']=='elo-deepseek-r1:1.5b' and model.timeout==180
        else:assert request.headers['authorization']=='Bearer preserved-cloud-key' and model.timeout==55
        if provider=='gemini':
            assert payload['response_format']['type']=='json_schema' and payload['reasoning_effort']=='minimal'
        else:
            assert payload['response_format']=={'type':'json_object'}
            assert 'JSON schema:' in payload['messages'][0]['content']
        assert ('thinking' in payload)==(provider=='deepseek')
    asyncio.run(run())

@pytest.mark.parametrize('prefix',['ASSESSMENT','ROADMAP'])
def test_development_http_requires_explicit_permission_and_local_model(monkeypatch,prefix):
    monkeypatch.setenv(prefix+'_LLM_BASE_URL','http://host.docker.internal:11434/v1')
    monkeypatch.setenv(prefix+'_LLM_ALLOW_HTTP','true')
    monkeypatch.setenv('APP_ENV','production')
    with pytest.raises(ValueError,match='HTTPS'):Model(None,prefix)
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv(prefix+'_LLM_API_KEY','')
    monkeypatch.setenv(prefix+'_LLM_MODEL','elo-deepseek-r1:1.5b')
    assert Model(None,prefix).configured
    monkeypatch.setenv(prefix+'_LLM_MODEL','')
    assert not Model(None,prefix).configured

def test_local_model_serializes_calls(monkeypatch):
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('ASSESSMENT_LLM_BASE_URL','http://host.docker.internal:11434/v1')
    monkeypatch.setenv('ASSESSMENT_LLM_ALLOW_HTTP','true')
    monkeypatch.setenv('ASSESSMENT_LLM_MODEL','elo-deepseek-r1:1.5b')
    async def run():
        entered,release=asyncio.Event(),asyncio.Event();calls=[]
        async def handler(request):
            calls.append(request)
            if len(calls)==1:entered.set();await release.wait()
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"OK"}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            model=Model(client,'ASSESSMENT')
            tasks=[asyncio.create_task(model.generate(Answer,'Answer.',{})) for _ in range(2)]
            try:
                await asyncio.wait_for(entered.wait(),2);await asyncio.sleep(0)
                assert len(calls)==1
            finally:release.set()
            assert all(result.reply=='OK' for result in await asyncio.gather(*tasks))
    asyncio.run(run())


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

class Reply(BaseModel):
    value:str
def overloaded_model(monkeypatch,outcomes):
    monkeypatch.setenv('ROADMAP_LLM_API_KEY','synthetic-key');monkeypatch.setenv('ROADMAP_LLM_BASE_URL','https://provider.example/v1');monkeypatch.setenv('ROADMAP_LLM_MODEL','synthetic-model')
    calls=[];pauses=[]
    async def pause(seconds):pauses.append(seconds)
    monkeypatch.setattr(runtime.asyncio,'sleep',pause)
    def handler(request):
        calls.append(request);status=outcomes[min(len(calls)-1,len(outcomes)-1)]
        if status==200:return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"value":"ok"}'}}]})
        return httpx.Response(status,json={'error':{'status':'UNAVAILABLE','message':'High demand.'}})
    return Model(httpx.AsyncClient(transport=httpx.MockTransport(handler)),'ROADMAP'),calls,pauses

def test_an_overloaded_provider_is_retried_with_bounded_pauses(monkeypatch):
    model,calls,pauses=overloaded_model(monkeypatch,[503,503,200])
    assert asyncio.run(model.generate(Reply,'Reply.',{})).value=='ok'
    assert len(calls)==3 and pauses==list(runtime.OVERLOAD_DELAYS)

def test_lasting_overload_reports_a_busy_model_with_a_saved_delay(monkeypatch):
    model,calls,pauses=overloaded_model(monkeypatch,[503])
    with pytest.raises(Problem) as failure:asyncio.run(model.generate(Reply,'Reply.',{}))
    assert len(calls)==3 and pauses==list(runtime.OVERLOAD_DELAYS)
    assert (failure.value.code,failure.value.status,failure.value.retry_after)==('model_busy',503,runtime.OVERLOAD_RETRY_AFTER)
    assert 'busy' in failure.value.detail and 'High demand' not in failure.value.detail

@pytest.mark.parametrize('status',[400,401,403,404,500])
def test_other_provider_rejections_are_not_retried(monkeypatch,status):
    model,calls,pauses=overloaded_model(monkeypatch,[status])
    with pytest.raises(Problem) as failure:asyncio.run(model.generate(Reply,'Reply.',{}))
    assert len(calls)==1 and pauses==[] and failure.value.code=='model_provider'
