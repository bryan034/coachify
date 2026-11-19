"""Synthetic research routing: chat search decisions and Opportunity availability."""
import asyncio
import json
from types import SimpleNamespace as NS
import pytest
from app.ai.adapter import AIError
from app.ai.context_contracts import ContextPlan
from app.ai.qa_contracts import FocusedAnswer
from app.clients.search_sources import SourceAPIs
from app.workflows.context_chat import semantic_chat
from tests.test_goal_chat_presentation import environment


@pytest.mark.parametrize('topic,clarification',[('off_topic',None),('edit',None),('role','Which role detail do you mean?')])
def test_unrelated_edit_and_ambiguous_questions_never_search(monkeypatch,topic,clarification):
    async def run():
        request,body,*_=environment();body.conversation=[];body.message='A synthetic question'
        class Store:
            def __init__(self,*args):pass
            def save_question(self,*args):pass
            def fetch(self,*args):return {'role':'Analyst','field':'Data'},{}
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
        async def search(*args):pytest.fail('This route must not search.')
        async def generate(payload,operation,**kwargs):
            assert payload.stage=='context_route'
            return NS(data=ContextPlan(topic=topic,clarification=clarification,research_focus='interviews',resolved_question='Public role question'))
        request.app.state.research_client=NS(collect_query=search)
        request.app.state.ai=NS(generate=generate)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert (result is None)==(topic=='edit')
    asyncio.run(run())


def test_configured_brave_search_enables_opportunity_pipeline():
    from app.ai.opportunity_config import OpportunitySettings
    from app.workflows.opportunity.engine import availability_issues
    from app.schemas.opportunity_api import OpportunityView
    ai=NS(settings=NS(enabled=True,provider='compatible'),context_enabled=True)
    assert availability_issues(OpportunitySettings(),ai,SourceAPIs(None,brave_key='synthetic'))==[]
    assert availability_issues(OpportunitySettings(),ai,SourceAPIs(None))==['brave_not_configured']
    view=OpportunityView(available=False,availability_issues=['model_not_configured','search_not_configured'],
        job_id=None,career_target_id='0'*24,status='failed')
    assert view.availability_issues==['model_not_configured','search_not_configured']


@pytest.mark.parametrize('missing,not_found',[(True,False),(False,True)])
@pytest.mark.parametrize('repair',[False,True])
def test_saved_goal_questions_automatically_search_when_more_information_is_needed(monkeypatch,missing,not_found,repair):
    async def run():
        request,body,*_=environment();body.message='PRIVATE question about this role';body.conversation=[]
        class Store:
            def __init__(self,*args):pass
            def save_question(self,*args):pass
            def fetch(self,*args):return {'role':'Analyst','field':'Data','company':'Public Example','location':'Singapore'},{}
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
        monkeypatch.setattr('app.workflows.context_chat.selected_facts',lambda *args:([],{},False) if missing else ([{'ref':'f1','data':{'name':'SQL'}}],{'f1':[]},False))
        searches=[];answers=[];repaired=False
        async def collect(context,query):
            searches.append(query)
            return [SourceAPIs.source('brave','https://public.test/interviews','Interview','The role has an online interview.')]
        request.app.state.research_client=NS(collect_query=collect)
        async def generate(payload,operation,**kwargs):
            nonlocal repaired
            if payload.stage=='context_route':output=ContextPlan(topic='interview_process',missing=missing,resolved_question='What are the interview stages?')
            else:
                answers.append(json.loads(payload.context))
                output=FocusedAnswer(status='not_found',reply='Not saved.') if not_found and len(answers)==1 else FocusedAnswer(reply='Online interview [web0].',references=['web0'])
                if output.status=='answered' and repair and not repaired:
                    repaired=True
                    raise AIError('invalid_output',True,reason='schema_validation')
            if kwargs.get('validate_output'):kwargs['validate_output'](output)
            return NS(data=output)
        request.app.state.ai=NS(generate=generate)
        from app.ai.recovery import recover_responses
        token=recover_responses.set(True)
        try:result=await semantic_chat(request,'owner',{'workspace':{}},body)
        finally:recover_responses.reset(token)
        assert 'https://public.test/interviews' in result.reply
        assert len(searches)==1 and 'Public Example' in searches[0] and 'PRIVATE' not in searches[0]
        assert len(answers)==(2 if not_found else 1)+int(repair)
    asyncio.run(run())


def test_metered_search_charges_the_current_account_before_any_provider_request(tmp_path,monkeypatch):
    import httpx
    from elo_shared.model_budget import budget_owner
    from app.clients.search_sources import SearchAllowanceExceeded
    from app.repositories.goals import GoalError
    monkeypatch.setenv('MODEL_BUDGET_PATH',str(tmp_path/'usage.sqlite3'))
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'grounding':{'generic':[]},'sources':{}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source=SourceAPIs(client,brave_key='synthetic',metered=True,searches_per_account=1)
            with pytest.raises(GoalError,match='attributed'):await source.search('public interview stages')
            with budget_owner('owner'):
                assert await source.search('public interview stages')==[]
                with pytest.raises(SearchAllowanceExceeded) as denied:await source.search('public interview stages')
            assert denied.value.limit_scope=='user' and 'daily research search allowance' in denied.value.message
            with budget_owner('another-owner'):await source.search('public interview stages')
    asyncio.run(run())
    assert len(calls)==2


def test_chat_does_not_wait_on_a_daily_search_allowance(monkeypatch):
    from app.clients.search_sources import SearchAllowanceExceeded
    from app.workflows.goal_question import research_question
    from app.ai.waiting import quota_progress
    async def run():
        async def collect(context,query):raise SearchAllowanceExceeded('owner',3600)
        request=NS(app=NS(state=NS(research_client=NS(collect_question_query=collect))))
        async def check():pass
        token=quota_progress.set(lambda _:pytest.fail('A daily allowance must not start a provider wait.'))
        try:
            with pytest.raises(SearchAllowanceExceeded):
                await research_question(request,{'role':'Analyst','field':'Data','location':'Singapore'},'interviews',check,query='Analyst interviews')
        finally:quota_progress.reset(token)
    asyncio.run(run())


@pytest.mark.parametrize('cap,workflow,expected',[(None,'collect_query',6),(None,'collect_discovery_query',5),
    (None,'collect_opportunity_query',5),(4,'collect_query',4),(4,'collect_discovery_query',4),(4,'collect_opportunity_query',4)])
def test_url_cap_only_lowers_each_workflows_built_in_limit(cap,workflow,expected):
    import httpx
    from app.schemas.analysis import ResearchContext
    params=[]
    def handler(request):
        params.append(dict(request.url.params))
        return httpx.Response(200,json={'grounding':{'generic':[]},'sources':{}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source=SourceAPIs(client,brave_key='synthetic',max_urls=cap)
            await getattr(source,workflow)(ResearchContext(role='Analyst',field='Data',location='Singapore'),'Analyst interviews')
    asyncio.run(run())
    assert params[0]['maximum_number_of_urls']==str(expected)


@pytest.mark.parametrize('name,value',[('CAREER_RESEARCH_MAX_URLS_PER_SEARCH','0'),('CAREER_RESEARCH_MAX_URLS_PER_SEARCH','7'),
    ('CAREER_RESEARCH_SEARCHES_PER_ACCOUNT_PER_DAY','-1'),('CAREER_RESEARCH_SEARCHES_PER_ACCOUNT_PER_DAY','many')])
def test_invalid_research_limits_fail_at_startup(monkeypatch,name,value):
    monkeypatch.setenv(name,value)
    with pytest.raises(ValueError,match=name):SourceAPIs.from_environment(None)


def test_blank_research_limits_mean_unlimited_searches_and_built_in_urls(monkeypatch):
    monkeypatch.setenv('CAREER_RESEARCH_SEARCHES_PER_ACCOUNT_PER_DAY','')
    monkeypatch.delenv('CAREER_RESEARCH_MAX_URLS_PER_SEARCH',raising=False)
    source=SourceAPIs.from_environment(None)
    assert source.metered and source.searches_per_account is None and source.max_urls is None
