"""Obsolete chat stops during quota waiting, before another provider request."""
import asyncio
from types import SimpleNamespace as NS
import httpx
import pytest
from app.ai.adapter import AIAdapter, AIError, Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.context_contracts import ContextPlan
from app.ai.qa_contracts import FocusedAnswer
from app.ai.waiting import quota_reason
from app.clients.search_sources import SourceAPIs
from app.repositories.goals import GoalError
from app.schemas.jd import JDExtraction
from app.workflows.chat import focused_chat, edit_goal
from app.workflows.context_chat import semantic_chat
from app.workflows.goal_summary import summarize
from app.workflows.operations import Operations


@pytest.mark.parametrize('workflow',['semantic','focused','edit','summary'])
@pytest.mark.parametrize('change',['revision','session'])
def test_changed_workspace_releases_chat_during_long_quota_wait(monkeypatch,workflow,change):
    async def run():
        current={'version':1,'session':'session'};calls=[];waits=[]
        row={'workspace':{'review_id':'goal','phase':'ready','research_id':'research','revision':1},'goal_id':'goal'}
        def check(owner,session,version):
            if current['session']!=session:raise GoalError('Conversation replaced.')
            # Exercise the separate canonical-review check as well as session fencing.
            return row
        review=NS(content=JDExtraction(role='Data Analyst',field='Data',company=None,skills=[]),target_type='specific_job')
        goal=NS(id='goal',version=1,role='Data Analyst',field='Data',company=None)
        repo=NS(check=check,reviews=NS(version=lambda *args:current['version'],get=lambda *args:review),
                goals=NS(current=lambda owner:{'goal':goal}))
        class Questions:
            def __init__(self,*args):pass
            def metadata(self,*args):return {'role':'Data Analyst','field':'Data'}
            def fetch(self,*args):return {'role':'Data Analyst','field':'Data'},{}
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Questions)
        monkeypatch.setattr('app.repositories.questions.QuestionStore',Questions)
        def respond(request):calls.append(request);return httpx.Response(429,headers={'Retry-After':'600'})
        async def sleep(seconds):
            waits.append(seconds)
            current['version' if change=='revision' else 'session']=2 if change=='revision' else 'replacement'
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),client,sleep=sleep)
            record=NS(sources=[],intelligence=NS(status='completed',categories={}))
            request=NS(app=NS(state=NS(workspace_store=repo,research_store=NS(read=lambda *args,**kwargs:record),ai=ai)))
            body=NS(session_id='session',expected_version=1,message='Tell me about that.',conversation=[],research_id='research')
            execute={'semantic':lambda:semantic_chat(request,'owner',row,body),
                     'focused':lambda:focused_chat(request,'owner',row,body),
                     'edit':lambda:edit_goal(request,'owner',row,body),
                     'summary':lambda:summarize(request,'owner',body)}[workflow]
            jobs=Operations();accepted=jobs.submit('owner','original',workflow,'chat',execute)
            await jobs.jobs[accepted['operation_id']].task
            with pytest.raises(AIError,match='stale_input'):jobs.read('owner',accepted['operation_id'])
            assert len(calls)==1 and waits==[5]
            async def fresh():return {'saved':True}
            retry=jobs.submit('owner','new','new-context','chat',fresh)
            await jobs.jobs[retry['operation_id']].task
            assert jobs.read('owner',retry['operation_id'])['status']=='succeeded'
            await jobs.close()
    asyncio.run(run())


def test_cancellation_during_async_revision_check_prevents_provider_call():
    async def run():
        entered=asyncio.Event();release=asyncio.Event();calls=[]
        async def current():entered.set();await release.wait();return '1'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request:calls.append(request))) as client:
            ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),client)
            operation=Operation('owner','1','chat')
            task=asyncio.create_task(ai.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'Hello'}]),operation,current_revision=current))
            await entered.wait();operation.cancel();release.set()
            with pytest.raises(AIError,match='cancelled'):await task
            assert not calls
    asyncio.run(run())


@pytest.mark.parametrize('outcome',['revision','session','unchanged','exhausted'])
def test_public_research_quota_rechecks_current_workspace(monkeypatch,outcome):
    async def run():
        current={'version':1,'session':'session'};model_calls=[];searches=[];waits=[];cleanup=[]
        row={'workspace':{'review_id':'goal','revision':1},'goal_id':'goal'}
        def check(owner,session,version):
            if session!=current['session']:raise GoalError('Conversation replaced.')
            # A canonical edit can precede workspace activation. Keep this row
            # unchanged so only the review authority can detect that race.
            return row
        repo=NS(check=check,reviews=NS(version=lambda *args:current['version']))
        class Questions:
            def __init__(self,*args):pass
            def fetch(self,*args):return {'role':'Analyst','field':'Data','company':'Example'},{}
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Questions)
        def model_response(request):
            model_calls.append(request)
            output=ContextPlan(topic='role',research_focus='location',resolved_question='Where is this internship?') if len(model_calls)==1 else FocusedAnswer(reply='The internship is in Singapore.',references=['web0'])
            return httpx.Response(200,json={'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},
                'choices':[{'finish_reason':'stop','message':{'content':output.model_dump_json()}}]})
        def search_response(request):
            searches.append(request)
            if outcome!='unchanged' or len(searches)<4:
                return httpx.Response(429,headers={'Retry-After':'3600' if outcome in ('revision','session') else '7'})
            return httpx.Response(200,json={'grounding':{'generic':[{
                'url':'https://example.test/job','title':'Analyst internship','snippets':['The internship is in Singapore.']} ]}})
        async def pause(seconds):
            waits.append(seconds)
            assert job.status=='waiting_quota' and job.provider=='brave'
            assert quota_reason.get()=={'provider':'brave','limit_scope':'provider'}
            if outcome=='revision':current['version']=2
            if outcome=='session':current['session']='replacement'
        # Replace only this module's clock, preserving graph/task scheduling.
        monkeypatch.setattr('app.workflows.goal_question.asyncio',NS(sleep=pause))
        async with httpx.AsyncClient(transport=httpx.MockTransport(model_response)) as model_client, httpx.AsyncClient(transport=httpx.MockTransport(search_response)) as search_client:
            ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),model_client)
            request=NS(app=NS(state=NS(workspace_store=repo,research_store=NS(),ai=ai,
                research_client=SourceAPIs(search_client,brave_key='fixture'))))
            body=NS(session_id='session',expected_version=1,message='Research the location.',conversation=[])
            async def execute():
                try:return await semantic_chat(request,'owner',row,body)
                finally:cleanup.append((quota_reason.get(),job.status,job.resume_at))
            jobs=Operations();accepted=jobs.submit('owner','original','research','chat',execute)
            job=jobs.jobs[accepted['operation_id']]
            await job.task
            if outcome in ('revision','session'):
                with pytest.raises(AIError,match='stale_input'):jobs.read('owner',job.id)
                assert len(model_calls)==len(searches)==1 and waits==[5]
            else:
                assert len(searches)==4 and waits==[5,2]*3 and sum(waits)==21
                assert len({request.url.params['q'] for request in searches})==1
                if outcome=='unchanged':
                    assert len(model_calls)==2
                    assert 'https://example.test/job' in jobs.read('owner',job.id)['result'].reply
                else:
                    assert len(model_calls)==1
                    with pytest.raises(GoalError,match='rate limit'):jobs.read('owner',job.id)
            assert cleanup==[(None,'running',None)]
            async def fresh():return {'saved':True}
            retry=jobs.submit('owner','new','new-context','chat',fresh)
            await jobs.jobs[retry['operation_id']].task
            assert jobs.read('owner',retry['operation_id'])['status']=='succeeded'
            await jobs.close()
    asyncio.run(run())
