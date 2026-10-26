"""Regression for provider JSON failure followed by a client-side deadline."""
import asyncio
import json
import logging
import httpx
import pytest
from fastapi.testclient import TestClient
from app.ai.adapter import AIAdapter, AIError, Operation, record_usage
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.main import create_app


def settings(**values):
    return AISettings(enabled=True,model='openai/gpt-oss-120b',api_key='synthetic',max_output_tokens=512,**values)


@pytest.mark.parametrize('stage',['jd_extraction','jd_chat','jd_edit'])
@pytest.mark.parametrize('provider,model,base_url,expected',[
    ('groq','openai/gpt-oss-120b','https://api.groq.com/openai/v1','low'),
    ('groq','openai/gpt-oss-20b','https://api.groq.com/openai/v1','low'),
    ('groq','other-model','https://api.groq.com/openai/v1',None),
    ('compatible','openai/gpt-oss-120b','https://compatible.example.test/v1',None),
    ('groq','openai/gpt-oss-120b','https://compatible.example.test/v1',None),
])
def test_low_reasoning_is_scoped_to_supported_groq_jd_calls(stage,provider,model,base_url,expected):
    adapter=AIAdapter(AISettings(provider=provider,model=model,base_url=base_url),None)
    request=AIInput(stage=stage,source_text='SQL required') if stage=='jd_extraction' else AIInput(
        stage=stage,context='{}',conversation=[{'role':'user','content':'Explain SQL'}])
    payload=adapter._payload(request)
    assert payload.get('reasoning_effort')==expected
    assert payload['max_completion_tokens']==(1024 if stage=='jd_chat' else 4096)


def test_non_jd_tasks_keep_existing_reasoning_settings():
    adapter=AIAdapter(settings(),None)
    payload=adapter._payload(AIInput(stage='chat',conversation=[{'role':'user','content':'Hi'}]))
    assert 'reasoning_effort' not in payload


@pytest.mark.parametrize('timeout,expected_calls',[(20,1),(45,2)])
def test_json_correction_requires_enough_remaining_time(timeout,expected_calls):
    async def invoke():
        now=[0.0];calls=[]
        def handler(req):
            calls.append(json.loads(req.content))
            if len(calls)==1:
                now[0]+=9.0
                return httpx.Response(400,json={'error':{'code':'json_validate_failed',
                    'message':'PRIVATE PROVIDER ERROR','failed_generation':'PRIVATE TRUNCATED JSON'}})
            now[0]+=10.675
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(
                {'role':'Analyst','field':'Data','company':None,'skills':[]})}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(timeout_seconds=timeout),client,clock=lambda:now[0])
            op=Operation('owner','1','jd_extraction')
            pending=adapter.generate(AIInput(stage='jd_extraction',source_text='SQL required'),op,current_revision=lambda:'1')
            if timeout==20:
                with pytest.raises(AIError,match='timeout'): await pending
                assert op.status=='failed'
            else:
                result=await pending
                assert result.data.role=='Analyst' and op.status=='succeeded'
            assert len(calls)==expected_calls
            assert 'PRIVATE' not in json.dumps(calls)
    asyncio.run(invoke())


@pytest.mark.parametrize('code,detail',[
    ('timeout','time limit'),('incomplete_output','before it was complete'),
    ('output_limit','response size'),('unavailable','temporarily unavailable')])
def test_specific_failure_messages_reach_api(code,detail):
    def profile(req):
        return httpx.Response(200,json={'id':'synthetic-account','email_verified':True}
            if req.url.path.endswith('/session') else {'onboarding_complete':True})
    def processor(*args): raise AIError(code,True)
    upstream=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile))
    with TestClient(create_app(profile_client=upstream,processor=processor)) as client:
        response=client.post('/api/v1/career/imports/url',headers={'Authorization':'Bearer synthetic'},json={'url':'https://example.test/job'})
        assert response.status_code==503
        assert response.json()['code']==code and detail in response.json()['detail']
        assert 'The assistant could not complete this turn' not in response.text
        assert response.headers['Cache-Control']=='no-store'


def test_usage_identifies_reasoning_cached_input_and_output_truncation(caplog):
    raw=json.dumps({'usage':{'prompt_tokens':2422,'completion_tokens':4096,'total_tokens':6518,
        'completion_tokens_details':{'reasoning_tokens':3000,'private':'SECRET'},
        'prompt_tokens_details':{'cached_tokens':128}},
        'choices':[{'finish_reason':'length','message':{'content':'PRIVATE JD'}}]}).encode()
    with caplog.at_level(logging.INFO,logger='uvicorn.error.ai_usage'):
        record_usage(raw,'jd_extraction',1,1)
    assert '"reasoning_tokens":3000' in caplog.text
    assert '"cached_tokens":128' in caplog.text
    assert 'finish_reason=length' in caplog.text
    assert 'SECRET' not in caplog.text and 'PRIVATE' not in caplog.text


def test_edit_followup_is_not_started_near_deadline():
    async def invoke():
        now=[0.0];calls=[]
        def handler(req):
            calls.append(req)
            now[0]+=9
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(
                {'reply':'Propose a change','edit_requested':True})}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(timeout_seconds=20),client,clock=lambda:now[0])
            op=Operation('owner','1','jd_chat')
            with pytest.raises(AIError,match='timeout'):
                await adapter.generate(AIInput(stage='jd_chat',context='{}',conversation=[{'role':'user','content':'Add Python'}]),op,current_revision=lambda:'1')
            assert len(calls)==1 and op.status=='failed'
    asyncio.run(invoke())
