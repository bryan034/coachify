"""Synthetic overview and public follow-up tests; no credentials or database."""
import asyncio
import json
from types import SimpleNamespace as NS
import pytest
from app.ai.adapter import AIError
from app.ai.context_contracts import ContextPlan
from app.ai.goal_summary import GoalSummary
from app.ai.qa_contracts import FocusedAnswer
from app.schemas.analysis import ResearchSource
from app.repositories.goals import GoalError
from app.workflows.activity import activity_observer
from app.workflows.goal_summary import summarize
from app.workflows.context_chat import semantic_chat
from app.workflows.operations import Operations


def environment(reply='An interview is reported.',references=('research_0',)):
    goal=NS(id='goal',role='Analyst',field='Data',company='Example',location=None)
    record=NS(sources=[ResearchSource(source_id='s1',platform='other',url='https://example.test/job',evidence='The internship is in Singapore.')],
              intelligence=NS(status='completed',categories={'interviews':NS(status='completed',findings=[NS(source_ids=['s1'],value='An interview is reported.')])}))
    checks=[]
    def check(*args):
        checks.append(args)
        return {'workspace':{'phase':'ready','research_id':'research','review_id':'review'},'goal_id':'goal'}
    calls=[]
    async def generate(request,operation,**kwargs):
        calls.append(request)
        output=GoalSummary(blocks=[{'text':reply,'references':list(references)}])
        kwargs['validate_output'](output)
        return NS(data=output)
    repo=NS(check=check,goals=NS(current=lambda owner:{'goal':goal}))
    state=NS(workspace_store=repo,research_store=NS(read=lambda *args:record),ai=NS(generate=generate))
    return NS(app=NS(state=state)),NS(session_id='session',expected_version=1,research_id='research'),checks,calls,record


def test_overview_uses_structured_data_and_restores_verified_links():
    async def run():
        request,body,checks,calls,_=environment()
        result=await summarize(request,'owner',body)
        assert '[Source](<https://example.test/job>)' in result['reply']
        assert len(checks)==3 and calls[0].stage=='goal_summary'
        context=json.loads(calls[0].context)
        assert context['goal']['role']=='Analyst' and context['categories']['interviews']['findings'][0]['reference']=='research_0'
        assert 'owner' not in context and 'Singapore' not in calls[0].context
    asyncio.run(run())


@pytest.mark.parametrize('ref',['missing_fact','https://untrusted.test','s999'])
def test_overview_rejects_invented_sources(ref):
    async def run():
        request,body,*_=environment(references=(ref,))
        with pytest.raises(AIError):await summarize(request,'owner',body)
    asyncio.run(run())


def test_overview_rejects_a_result_for_a_replaced_goal():
    async def run():
        request,body,checks,*_=environment()
        original=request.app.state.workspace_store.check
        def check(*args):
            if checks:raise GoalError('Goal changed')
            return original(*args)
        request.app.state.workspace_store.check=check
        with pytest.raises(GoalError):await summarize(request,'owner',body)
    asyncio.run(run())


@pytest.mark.parametrize('topic,clarification,search',[('role',None,True),('off_topic',None,False),('role','Which location?',False),('edit',None,False)])
def test_followup_is_scoped_cited_and_never_exports_conversation(monkeypatch,topic,clarification,search):
    async def run():
        request,body,checks,calls,record=environment()
        searches=[];events=[]
        async def collect(context,query):
            searches.append(query)
            return record.sources
        async def generate(payload,operation,**kwargs):
            calls.append(payload)
            output=ContextPlan(topic=topic,missing=True,research_focus='location',clarification=clarification,
                resolved_question='Where is this internship located?') if payload.stage=='context_route' else FocusedAnswer(reply='The internship is in Singapore.',references=['web0'])
            kwargs['validate_output'](output)
            return NS(data=output)
        class Store:
            def __init__(self,*args):pass
            def fetch(self,*args):return {'role':'Analyst','field':'Data','company':'Example'},{}
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
        request.app.state.ai=NS(generate=generate)
        request.app.state.research_client=NS(collect_query=collect)
        body.message='Where is the internship? My email is private@example.test'
        body.conversation=[]
        token=activity_observer.set(events.append)
        try:result=await semantic_chat(request,'owner',{'workspace':{}},body)
        finally:activity_observer.reset(token)
        assert bool(searches)==search
        if search:
            assert 'Example Analyst' in searches[0] and 'location' in searches[0]
            assert 'private' not in searches[0] and '@' not in searches[0]
            assert 'https://example.test/job' in result.reply
            assert events==['understanding_question','searching_question','answering_question']
            assert len(checks)>=3
    asyncio.run(run())


def test_summary_remount_reuses_the_same_operation():
    async def run():
        jobs=Operations();calls=[]
        async def execute():calls.append(1);return {'reply':'Saved overview'}
        first=jobs.submit('owner','key1','snapshot','summary',execute)
        await asyncio.sleep(0)
        second=jobs.submit('owner','key2','snapshot','summary',execute)
        assert first['operation_id']==second['operation_id'] and second['status']=='succeeded'
        assert calls==[1]
        await jobs.close()
    asyncio.run(run())


def test_overview_requires_citations_for_retained_findings():
    async def run():
        request,body,_,_,record=environment('A claim without its citation.',references=('goal',))
        record.intelligence.categories={'interviews':NS(findings=[NS(source_ids=['s1'])])}
        with pytest.raises(AIError):await summarize(request,'owner',body)
    asyncio.run(run())


def test_public_search_quota_resumes_without_repeating_successful_retrieval(monkeypatch):
    from app.clients.search_sources import SourceRateLimit
    from app.workflows.goal_question import research_question
    from app.ai.waiting import quota_progress
    async def run():
        request,_,_,_,record=environment()
        calls=[];waits=[];checks=[]
        async def collect(context,query):
            calls.append(query)
            if len(calls)==1:raise SourceRateLimit(1)
            return record.sources
        async def pause(seconds):waits.append(seconds)
        async def check():checks.append(1)
        request.app.state.research_client=NS(collect_query=collect)
        monkeypatch.setattr('app.workflows.goal_question.asyncio.sleep',pause)
        progress=[];token=quota_progress.set(progress.append)
        try:facts,links=await research_question(request,{'role':'Analyst','field':'Data','company':'Example'},'location',check)
        finally:quota_progress.reset(token)
        assert len(calls)==2 and calls[0]==calls[1] and waits==[1]
        assert progress==[1,None] and len(checks)==3
        assert facts[0]['ref']=='web0' and links['web0'][0]['source_id']=='s1'
    asyncio.run(run())


def test_summary_reconnects_to_an_unfinished_snapshot():
    async def run():
        jobs=Operations();gate=asyncio.Event()
        async def execute():await gate.wait();return {'reply':'Overview'}
        first=jobs.submit('owner','key1','snapshot','summary',execute)
        second=jobs.submit('owner','key2','snapshot','summary',execute)
        assert first['operation_id']==second['operation_id']
        await jobs.close()
    asyncio.run(run())
