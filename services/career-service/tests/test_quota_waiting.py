"""Quota pauses use fake transports/clocks; no live AI calls or credentials."""
import asyncio
import httpx
import pytest
from app.ai.adapter import AIAdapter, AIError, Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.waiting import quota_progress
from app.workflows.operations import Operations
from app.workflows.operations import OperationConflict
from app.repositories.goals import GoalError


def test_repeated_quota_waits_resume_same_call_outside_active_timeout():
    async def run():
        calls, waits, states = [], [], []
        clock = [0]
        def respond(request):
            calls.append(request.content)
            if len(calls) == 1: return httpx.Response(429, headers={'Retry-After':'2'})
            return httpx.Response(200, json={'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},
                'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"Hello","suggested_roles":[]}'}}]})
        async def sleep(seconds):
            waits.append(seconds)
            clock[0] += seconds
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            ai = AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture',timeout_seconds=1),client,
                           sleep=sleep,clock=lambda:clock[0])
            context = quota_progress.set(states.append)
            try:
                operation=Operation('alice','1','chat')
                result=await ai.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hi'}]),operation,current_revision=lambda:'1')
            finally: quota_progress.reset(context)
        assert result.data.reply == 'Hello' and operation.status == 'succeeded'
        assert waits == [2] and states == [2,None]
        assert len(calls) == 2 and calls[0] == calls[1]
    asyncio.run(run())


@pytest.mark.parametrize('cancel',[True,False])
def test_cancel_or_replace_during_wait_prevents_another_provider_call(cancel):
    async def run():
        entered=asyncio.Event(); calls=[]; revision=['1']
        def respond(request):
            calls.append(request)
            return httpx.Response(429,headers={'Retry-After':'60'})
        async def sleep(_):
            entered.set()
            if cancel: await asyncio.Event().wait()
            else: revision[0]='2'
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),client,sleep=sleep)
            context=quota_progress.set(lambda _:None)
            operation=Operation('alice','1','chat')
            task=asyncio.create_task(ai.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hi'}]),operation,current_revision=lambda:revision[0]))
            quota_progress.reset(context)
            await entered.wait()
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError): await task
                assert operation.status == 'cancelled'
            else:
                with pytest.raises(AIError,match='stale_input'): await task
            assert len(calls)==1
    asyncio.run(run())


def test_permanent_errors_do_not_wait():
    async def run():
        def respond(_): return httpx.Response(401)
        async def sleep(_): pytest.fail('Permanent failures must not wait.')
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),client,sleep=sleep)
            context=quota_progress.set(lambda _:None)
            try:
                with pytest.raises(AIError,match='provider_auth'):
                    await ai.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hi'}]),Operation('alice','1','chat'),current_revision=lambda:'1')
            finally: quota_progress.reset(context)
    asyncio.run(run())


def test_operations_are_owner_scoped_idempotent_and_cancel_on_shutdown():
    async def run():
        jobs=Operations(); entered=asyncio.Event(); finished=asyncio.Event(); calls=[]
        async def execute():
            calls.append(1); quota_progress.get()(10); entered.set()
            await finished.wait()
            return {'answer':'Done'}
        first=jobs.submit('alice','key','digest','jd',execute)
        await entered.wait()
        assert jobs.read('alice',first['operation_id'])['status']=='waiting_quota'
        assert jobs.submit('alice','key','digest','jd',execute)['operation_id']==first['operation_id']
        with pytest.raises(GoalError): jobs.read('bob',first['operation_id'])
        with pytest.raises(GoalError): jobs.submit('alice','key','different','jd',execute)
        finished.set(); await jobs.jobs[first['operation_id']].task
        assert jobs.read('alice',first['operation_id'])['result']=={'answer':'Done'}
        assert calls==[1]
        async def pending(): await asyncio.Event().wait()
        second=jobs.submit('alice','next','digest','jd',pending)
        task=jobs.jobs[second['operation_id']].task
        await asyncio.sleep(0)
        await jobs.close()
        assert task.cancelled() and not jobs.jobs
    asyncio.run(run())



def test_wait_longer_than_the_active_deadline_still_allows_completion():
    async def run():
        calls=[]
        def respond(request):
            calls.append(1)
            if len(calls)==1:return httpx.Response(429,headers={'Retry-After':'1'})
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"Resumed","suggested_roles":[]}'}}]})
        async def sleep(_): await asyncio.sleep(1.05)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture',timeout_seconds=1),client,sleep=sleep)
            context=quota_progress.set(lambda _:None)
            try:
                result=await ai.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hi'}]),Operation('alice','1','chat'),current_revision=lambda:'1')
            finally:quota_progress.reset(context)
        assert result.data.reply=='Resumed' and len(calls)==2
    asyncio.run(run())


def test_reopening_the_same_jd_reattaches_during_a_long_quota_wait():
    async def run():
        jobs=Operations();entered=asyncio.Event();release=asyncio.Event();calls=[]
        async def execute():
            calls.append(1);quota_progress.get()(600);entered.set()
            await release.wait();return {'goal':'synthetic'}
        first=jobs.submit('alice','first-key','same-jd','jd',execute)
        await entered.wait()
        reopened=jobs.submit('alice','remounted-key','same-jd','jd',execute)
        assert reopened['operation_id']==first['operation_id']
        assert reopened['status']=='waiting_quota' and 590<=reopened['retry_after']<=600
        with pytest.raises(OperationConflict) as error:jobs.submit('alice','different-key','other-jd','jd',execute)
        assert error.value.code=='operation_in_progress'
        with pytest.raises(OperationConflict) as error:jobs.submit('alice','remounted-key','other-jd','jd',execute)
        assert error.value.code=='operation_key_reused'
        with pytest.raises(GoalError):jobs.read('bob',first['operation_id'])
        release.set();await jobs.jobs[first['operation_id']].task
        assert jobs.submit('alice','remounted-key','same-jd','jd',execute)['result']=={'goal':'synthetic'}
        assert calls==[1]
        await jobs.close()
    asyncio.run(run())
