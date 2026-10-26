"""Provider retry behaviour and task output caps."""
import asyncio
import httpx
import pytest
from app.ai.adapter import AIAdapter,AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput


def test_provider_429_has_no_automatic_retry_or_subsequent_local_block():
    async def invoke():
        calls=[]
        def handler(req):
            calls.append(req)
            if len(calls)==1:return httpx.Response(429,headers={'Retry-After':'17'})
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),client)
            with pytest.raises(AIError) as error:await adapter._complete({'messages':[]},owner='alice')
            assert len(calls)==1 and error.value.limit_scope=='provider' and error.value.retry_after==17
            assert await adapter._complete({'messages':[]},owner='alice')=='{}'
            assert len(calls)==2
    asyncio.run(invoke())


def test_provider_5xx_retry_is_not_blocked_by_local_token_allowances():
    async def invoke():
        calls=[]
        def handler(req):
            calls.append(req)
            if len(calls)==1:return httpx.Response(503)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]})
        async def no_sleep(_):pass
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),client,sleep=no_sleep)
            assert await adapter._complete({'messages':[],'max_completion_tokens':4096},owner='alice')=='{}'
            assert len(calls)==2
    asyncio.run(invoke())


def test_old_quota_environment_settings_are_ignored(monkeypatch):
    for key in ('AI_TOKENS_PER_MINUTE','AI_REQUESTS_PER_MINUTE','AI_CONCURRENCY'):
        monkeypatch.setenv(key,'1')
    settings=AISettings.from_env()
    assert not {'tokens_per_minute','requests_per_minute','concurrency'} & AISettings.model_fields.keys()


@pytest.mark.parametrize('stage,expected',[('workspace_chat',1024),('jd_chat',1024),('interview_synthesis',2048),('jd_extraction',4096)])
def test_task_output_caps_respect_the_configured_ceiling(stage,expected):
    if stage=='jd_extraction':request=AIInput(stage=stage,source_text='SQL required')
    elif stage=='interview_synthesis':request=AIInput(stage=stage,public_context={'role':'Analyst','field':'Data'},sources=[])
    else:request=AIInput(stage=stage,conversation=[{'role':'user','content':'Explain SQL'}],context='{}')
    for configured in (4096,512):
        adapter=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture',max_output_tokens=configured),None)
        assert adapter._payload(request)['max_completion_tokens']==min(configured,expected)
