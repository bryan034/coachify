"""Gemini requests have bounded context/output, without a local minute quota."""
import asyncio
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.ai.adapter import AIAdapter, AIError
from app.ai.config import GeminiSettings
from app.ai.contracts import AIInput
from app.ai.usage import input_tokens
from app.main import create_app


def test_input_count_includes_messages_and_schema_but_not_output_allowance():
    payload={'messages':[{'role':'system','content':'Instructions'},{'role':'user','content':'JD'}]}
    base=input_tokens(payload)
    assert input_tokens({**payload,'max_tokens':4096})==base
    assert input_tokens({**payload,'response_format':{'type':'json_schema','schema':{'properties':{'skills':{'type':'array'}}}}})>base


def test_large_requests_repeat_without_local_token_admission_or_output_reduction():
    async def run():
        calls=[]
        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(GeminiSettings(enabled=True,api_key='fixture'),client)
            request=AIInput(stage='context_answer',context=json.dumps({'facts':['x '*9000]}),
                conversation=[{'role':'user','content':'Explain these career requirements.'}])
            payload=adapter._payload(request)
            assert input_tokens(payload)>8000
            assert await asyncio.gather(*(adapter._complete(payload,owner='alice') for _ in range(4)))==['{}']*4
        assert len(calls)==4 and all(call==payload for call in calls)
        assert payload['max_tokens']==768
    asyncio.run(run())


def test_gemini_provider_quota_is_still_enforced_without_immediate_retry():
    async def run():
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(429,headers={'Retry-After':'3'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(GeminiSettings(enabled=True,api_key='fixture'),client)
            with pytest.raises(AIError) as error:await adapter._complete({'model':'fixture','messages':[]},owner='alice')
            assert error.value.limit_scope=='provider' and error.value.provider=='gemini'
            assert error.value.retry_after==3 and len(calls)==1
    asyncio.run(run())


@pytest.mark.parametrize('code,scope,status,fragment',[
    ('input_limit',None,422,'configured model context'),
    ('rate_limited','provider',429,'AI provider')])
def test_api_explains_context_and_provider_limits(code,scope,status,fragment):
    def profile(req):return httpx.Response(200,json={'id':'synthetic','email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    def processor(*args):raise AIError(code,limit_scope=scope,input_count=4100,retry_after=23 if scope else None,provider='gemini')
    upstream=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile))
    with TestClient(create_app(profile_client=upstream,processor=processor)) as client:
        response=client.post('/api/v1/career/imports/url',headers={'Authorization':'Bearer synthetic'},json={'url':'https://example.test/job'})
        assert response.status_code==status and fragment in response.json()['detail']
        if scope:
            assert response.json()['limit_scope']==scope
            assert response.json()['retry_after']==23 and response.headers['Retry-After']=='23'
        else:assert 'Retry-After' not in response.headers
