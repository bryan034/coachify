"""Atomic 7k rolling Groq admission, actual usage reconciliation and provider isolation."""
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.ai.adapter import AIAdapter,AIError
from app.ai.config import AISettings
from app.ai.usage import UserTokenUsage,UserQuotaExceeded,input_tokens,consumed_tokens
from app.repositories.goals import now
from app.main import create_app


def settings():return AISettings(enabled=True,model='fixture',api_key='fixture')
def reply(total=200):return httpx.Response(200,json={'usage':{'prompt_tokens':100,'completion_tokens':total-100,'total_tokens':total},'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]})
def clock():
    stamp=[now().replace(microsecond=0)]
    return stamp,UserTokenUsage(clock=lambda:stamp[0])


def test_rolling_allowance_blocks_at_7000_and_only_until_enough_usage_expires():
    stamp,usage=clock();usage.record('alice',7000)
    stamp[0]+=timedelta(seconds=10);usage.record('alice',7000)
    stamp[0]+=timedelta(seconds=10)
    with pytest.raises(UserQuotaExceeded) as error:usage.check('alice')
    assert error.value.retry_after==50  # Dropping only the first entry still leaves 7000.
    usage.check('bob')
    stamp[0]+=timedelta(seconds=50);usage.check('alice')


def test_admission_reserves_capacity_and_reconciles_to_actual_usage():
    async def run():
        stamp,usage=clock();usage.record('alice',6999);calls=[]
        def handler(req):calls.append(req);return reply()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(),client,usage_store=usage)
            payload={'messages':[{'role':'user','content':'Hi'}],'max_completion_tokens':4096}
            with pytest.raises(AIError) as error:await adapter._complete(payload,owner='alice')
            assert error.value.limit_scope=='user' and error.value.retry_after==60 and calls==[]
            assert await adapter._complete(payload,owner='bob')=='{}'
            assert sum(v['tokens'] for v in usage.local[usage.key('bob')])==200
            stamp[0]+=timedelta(seconds=60)
            assert await adapter._complete(payload,owner='alice')=='{}'
            assert sum(v['tokens'] for v in usage.local[usage.key('alice')])==200
    asyncio.run(run())


@pytest.mark.parametrize('count,allowed',[(6872,True),(6873,False)])
def test_input_token_boundary_is_checked_before_network(count,allowed,monkeypatch):
    monkeypatch.setattr('app.ai.adapter.input_tokens',lambda _:count)
    async def run():
        calls=[]
        def handler(req):calls.append(req);return reply()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(),client)
            if allowed:assert await adapter._complete({'messages':[]},owner='alice')=='{}'
            else:
                with pytest.raises(AIError) as error:await adapter._complete({'messages':[]},owner='alice')
                assert error.value.code=='input_limit' and error.value.input_count==6873
            assert len(calls)==int(allowed)
    asyncio.run(run())


def test_input_count_includes_messages_and_schema_but_not_output_allowance():
    payload={'messages':[{'role':'system','content':'Instructions'},{'role':'user','content':'JD'}]}
    base=input_tokens(payload)
    assert input_tokens({**payload,'max_completion_tokens':4096})==base
    assert input_tokens({**payload,'response_format':{'type':'json_schema','schema':{'properties':{'skills':{'type':'array'}}}}})>base


def test_actual_totals_count_reasoning_once_and_missing_usage_uses_observed_output():
    raw=json.dumps({'usage':{'prompt_tokens':100,'completion_tokens':200,'total_tokens':300,'completion_tokens_details':{'reasoning_tokens':150}}})
    assert consumed_tokens(raw,999)==300
    observed=json.dumps({'choices':[{'message':{'content':'A short reply'}}]})
    assert 100<consumed_tokens(observed,100)<120
    assert consumed_tokens('{',100)==100


def test_every_correction_retry_checks_the_same_user_allowance():
    async def run():
        stamp,usage=clock();calls=[]
        def handler(req):
            calls.append(req);usage.record('alice',7000)
            return httpx.Response(503)
        async def no_sleep(_):pass
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(),client,sleep=no_sleep,usage_store=usage)
            with pytest.raises(AIError) as error:await adapter._complete({'messages':[]},owner='alice')
            assert error.value.limit_scope=='user' and len(calls)==1
    asyncio.run(run())


def test_truncated_paid_response_counts_usage_and_provider_429_does_not():
    async def run():
        stamp,usage=clock();calls=[]
        def handler(req):
            calls.append(req)
            if len(calls)==1:return httpx.Response(200,json={'usage':{'prompt_tokens':100,'completion_tokens':1000,'total_tokens':1100},'choices':[{'finish_reason':'length','message':{'content':'{'}}]})
            return httpx.Response(429,headers={'Retry-After':'15'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(),client,usage_store=usage)
            with pytest.raises(AIError,match='incomplete_output'):await adapter._complete({'messages':[]},owner='alice')
            with pytest.raises(AIError) as error:await adapter._complete({'messages':[]},owner='alice')
            assert error.value.limit_scope=='provider' and error.value.retry_after==15
            assert sum(v['tokens'] for v in usage.local[usage.key('alice')])==1100
    asyncio.run(run())


@pytest.mark.parametrize('code,scope,status,fragment',[('input_limit',None,422,'7,000'),('rate_limited','user',429,'7,000-token'),('rate_limited','provider',429,'AI provider')])
def test_api_explains_input_vs_user_and_provider_limits(code,scope,status,fragment):
    def profile(req):return httpx.Response(200,json={'id':'synthetic','email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    def processor(*args):raise AIError(code,limit_scope=scope,input_count=4100,retry_after=23 if scope else None)
    upstream=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile))
    with TestClient(create_app(profile_client=upstream,processor=processor)) as client:
        response=client.post('/api/v1/career/imports/url',headers={'Authorization':'Bearer synthetic'},json={'url':'https://example.test/job'})
        assert response.status_code==status and fragment in response.json()['detail']
        if scope:
            assert response.json()['limit_scope']==scope
            assert response.json()['retry_after']==23 and response.headers['Retry-After']=='23'
        else:assert 'Retry-After' not in response.headers


def test_mongodb_usage_is_shared_atomic_and_isolated_by_user():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB')
    client=MongoClient(uri);db=client['coachify_usage_test_'+uuid4().hex]
    try:
        stamp=now().replace(microsecond=0);first=UserTokenUsage(db,clock=lambda:stamp);second=UserTokenUsage(db,clock=lambda:stamp)
        with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(lambda _:first.record('alice',1000),range(8)))
        with pytest.raises(UserQuotaExceeded) as error:second.check('alice')
        assert error.value.retry_after==60
        second.check('bob')
        row=db.ai_user_usage.find_one({});assert sum(v['tokens'] for v in row['entries'])==8000 and len(row['entries'])==8
        assert 'alice' not in str(row) and 'prompt' not in str(row)
        assert any(v.get('expireAfterSeconds')==0 for v in db.ai_user_usage.index_information().values())
        UserTokenUsage(db,clock=lambda:stamp+timedelta(seconds=60)).check('alice')
    finally:client.drop_database(db.name);client.close()


@pytest.mark.parametrize('failure,charged',[(httpx.ConnectError,False),(httpx.ReadTimeout,True)])
def test_unknown_network_usage_conservatively_counts_possible_paid_completion(failure,charged):
    async def run():
        stamp,usage=clock()
        def handler(req):raise failure('Synthetic network failure',request=req)
        payload={'messages':[{'role':'user','content':'Hello'}],'max_completion_tokens':4096}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(settings(),client,usage_store=usage)
            with pytest.raises(httpx.HTTPError):await adapter._complete(payload,owner='alice')
        entries=usage.local.get(usage.key('alice'),[])
        assert sum(v['tokens'] for v in entries)==(input_tokens(payload)+4096 if charged else 0)
    asyncio.run(run())


def test_gemini_large_input_bypasses_groq_cap_and_exhausted_ledger():
    from app.ai.config import GeminiSettings
    from app.ai.contracts import AIInput
    async def run():
        stamp,usage=clock();usage.record('alice',7000);calls=[]
        def handler(request):calls.append(request);return reply()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(GeminiSettings(enabled=True,api_key='fixture'),client,usage_store=usage)
            request=AIInput(stage='context_answer',context=json.dumps({'facts':['x '*5000]}),conversation=[{'role':'user','content':'Explain these facts.'}])
            payload=adapter._payload(request)
            assert input_tokens(payload)>4000
            assert await adapter._complete(payload,owner='alice')=='{}'
            assert len(calls)==1
            assert sum(v['tokens'] for v in usage.local[usage.key('alice')])==7000
            primary=AIAdapter(settings(),client,usage_store=usage)
            with pytest.raises(AIError) as error:
                await primary._complete({'messages':[{'role':'user','content':'Hi'}]},owner='alice')
            assert error.value.limit_scope=='user' and len(calls)==1
    asyncio.run(run())


def test_gemini_provider_quota_is_still_enforced():
    from app.ai.config import GeminiSettings
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(429,headers={'Retry-After':'3'}))) as client:
            adapter=AIAdapter(GeminiSettings(enabled=True,api_key='fixture'),client)
            with pytest.raises(AIError) as error:await adapter._complete({'messages':[]},owner='alice')
            assert error.value.limit_scope=='provider' and error.value.retry_after==3
    asyncio.run(run())


def test_concurrent_requests_cannot_overshoot_7000_and_refund_unused_capacity():
    stamp,usage=clock()
    def admit(_):
        try:return usage.reserve('alice',1000,2000)
        except UserQuotaExceeded:return None
    with ThreadPoolExecutor(max_workers=8) as pool:tickets=list(pool.map(admit,range(8)))
    accepted=[v for v in tickets if v]
    assert len(accepted)==2 and sum(v['tokens'] for v in usage.local[usage.key('alice')])==6000
    usage.settle('alice',accepted[0],1200)
    assert usage.reserve('alice',1000,1500)
    assert sum(v['tokens'] for v in usage.local[usage.key('alice')])==6700
    with pytest.raises(UserQuotaExceeded) as error:usage.reserve('alice',500,500)
    assert error.value.retry_after<=60


def test_reservations_are_atomic_across_mongodb_replicas_and_survive_restart():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB')
    client=MongoClient(uri);db=client['coachify_reservations_test_'+uuid4().hex]
    try:
        stamp=now();stores=[UserTokenUsage(db,clock=lambda:stamp) for _ in range(8)]
        def reserve(index):
            try:return stores[index].reserve('alice',1000,2000)
            except UserQuotaExceeded:return None
        with ThreadPoolExecutor(max_workers=8) as pool:tickets=list(pool.map(reserve,range(8)))
        assert len([v for v in tickets if v])==2
        restarted=UserTokenUsage(db,clock=lambda:stamp)
        with pytest.raises(UserQuotaExceeded):restarted.reserve('alice',1000,2000)
        restarted.settle('alice',next(v for v in tickets if v),500)
        assert restarted.reserve('alice',1000,2000)
        assert sum(v['tokens'] for v in db.ai_user_usage.find_one({'_id':restarted.key('alice')})['entries'])==6500
    finally:client.drop_database(db.name);client.close()
