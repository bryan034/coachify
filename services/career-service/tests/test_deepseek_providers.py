"""Synthetic local/cloud inference and public-only DeepSeek Search integration."""
import asyncio
import json
from types import SimpleNamespace as NS
import httpx
import pytest
from pydantic import ValidationError
from app.ai.adapter import AIAdapter,Operation,AIError
from app.ai.config import AISettings
from app.ai.context_contracts import ContextPlan
from app.ai.qa_contracts import FocusedAnswer
from app.ai.contracts import AIInput
from app.clients.deepseek_search import DeepSeekSearch
from app.clients.search_sources import SourceAPIs,SourceRateLimit
from app.repositories.goals import GoalError
from app.schemas.analysis import ResearchContext
from app.workflows.context_chat import semantic_chat
from tests.test_goal_chat_presentation import environment


@pytest.mark.parametrize('provider',['local','deepseek'])
def test_provider_configuration_and_real_adapter_payload(monkeypatch,provider):
    monkeypatch.setenv('CAREER_LLM_PROVIDER',provider)
    monkeypatch.setenv('AI_ENABLED','true')
    monkeypatch.setenv('CAREER_LLM_API_KEY','' if provider=='local' else 'synthetic-cloud-key')
    monkeypatch.setenv('GEMINI_API_KEY','must-not-be-reused')
    settings=AISettings.from_env()
    assert settings.response_mode==('json_schema_strict' if provider=='local' else 'json_object')
    async def run():
        calls=[]
        def handler(request):
            calls.append(request)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{
                'content':json.dumps({'status':'answered','reply':'SQL is required.','references':['f1']}),
                'reasoning_content':'PRIVATE model reasoning'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            request=AIInput(stage='context_answer',context='{"facts":[{"ref":"f1","data":{"name":"SQL"}}]}',conversation=[{'role':'user','content':'What is required?'}])
            result=await AIAdapter(settings,client).generate(request,Operation('owner','1',request.stage),current_revision=lambda:'1')
        assert result.data.reply=='SQL is required.' and len(calls)==1
        payload=json.loads(calls[0].content)
        if provider=='local':
            assert payload['response_format']['type']=='json_schema'
            assert payload['response_format']['json_schema']['strict'] is True
            assert str(calls[0].url)=='http://host.docker.internal:11434/v1/chat/completions'
            assert 'authorization' not in calls[0].headers and 'thinking' not in payload
        else:
            assert payload['response_format']=={'type':'json_object'}
            assert 'JSON schema:' in payload['messages'][0]['content']
            assert str(calls[0].url)=='https://api.deepseek.com/v1/chat/completions'
            assert calls[0].headers['authorization']=='Bearer synthetic-cloud-key'
            assert payload['thinking']=={'type':'disabled'}
    asyncio.run(run())


def test_local_settings_are_explicit_and_cloud_credentials_never_use_brave_or_gemini(monkeypatch):
    with pytest.raises(ValidationError):AISettings(provider='deepseek',base_url='http://localhost:11434/v1')
    with pytest.raises(ValidationError):AISettings(provider='local',base_url='http://user:secret@localhost/v1')
    monkeypatch.setenv('CAREER_LLM_PROVIDER','deepseek')
    monkeypatch.setenv('AI_ENABLED','true')
    monkeypatch.setenv('GEMINI_API_KEY','synthetic-gemini')
    with pytest.raises(ValueError):AISettings.from_env()
    monkeypatch.setenv('CAREER_RESEARCH_PROVIDER','deepseek')
    monkeypatch.setenv('BRAVE_API_KEY','synthetic-brave')
    assert not SourceAPIs.from_environment(None).configured
    monkeypatch.setenv('CAREER_RESEARCH_API_KEY','synthetic-search')
    source=SourceAPIs.from_environment(None)
    assert isinstance(source,DeepSeekSearch) and source.configured
    assert source.for_opportunity() is source
    assert source.cache_policy!=SourceAPIs(None).cache_policy


def test_local_timeout_and_context_defaults_are_independent_of_cloud(monkeypatch):
    monkeypatch.setenv('CAREER_LLM_PROVIDER','local')
    monkeypatch.setenv('AI_ENABLED','true')
    monkeypatch.setenv('AI_TIMEOUT_SECONDS','60')
    monkeypatch.delenv('CAREER_LOCAL_TIMEOUT_SECONDS',raising=False)
    monkeypatch.setenv('AI_CONTEXT_TOKENS','')  # Compose delegates to provider defaults.
    local=AISettings.from_env()
    assert local.timeout_seconds==45 and local.context_tokens==16384
    monkeypatch.setenv('CAREER_LOCAL_TIMEOUT_SECONDS','240')
    assert AISettings.from_env().timeout_seconds==240
    monkeypatch.setenv('CAREER_LOCAL_TIMEOUT_SECONDS','301')
    with pytest.raises(ValueError,match='CAREER_LOCAL_TIMEOUT_SECONDS'):AISettings.from_env()
    monkeypatch.setenv('CAREER_LLM_PROVIDER','deepseek')
    monkeypatch.setenv('CAREER_LLM_API_KEY','synthetic')
    cloud=AISettings.from_env()
    assert cloud.timeout_seconds==60 and cloud.context_tokens==65536
    with pytest.raises(ValidationError):AISettings(provider='deepseek',timeout_seconds=180)


@pytest.mark.parametrize('first_failure',[False,True])
def test_local_model_calls_are_serialized_and_release_slot_on_failure(first_failure):
    async def run():
        entered,release=asyncio.Event(),asyncio.Event();calls=[];active=0;peak=0
        async def handler(request):
            nonlocal active,peak
            active+=1;peak=max(peak,active);calls.append(request)
            try:
                if len(calls)==1:
                    entered.set();await release.wait()
                    if first_failure:raise httpx.ReadTimeout('synthetic timeout')
                return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"Hello"}'}}]})
            finally:active-=1
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(AISettings(enabled=True,provider='local',model='synthetic'),client)
            request=AIInput(stage='chat',conversation=[{'role':'user','content':'Hello'}])
            tasks=[asyncio.create_task(adapter.generate(request,Operation(owner,'1','chat'),current_revision=lambda:'1')) for owner in ('first','second','third')]
            try:
                await asyncio.wait_for(entered.wait(),2);await asyncio.sleep(0)
                assert len(calls)==1
            finally:release.set()
            results=await asyncio.gather(*tasks,return_exceptions=True)
        assert peak==1 and len(calls)==3
        assert all(result.data.reply=='Hello' for result in results[1:])
        if first_failure:assert isinstance(results[0],AIError) and results[0].code=='timeout'
        else:assert results[0].data.reply=='Hello'
    asyncio.run(run())


@pytest.mark.parametrize('change',['stale','cancelled','snapshot'])
def test_local_queue_fences_versions_cancellation_and_submitted_snapshot(change):
    async def run():
        entered,release=asyncio.Event(),asyncio.Event();calls=[];clock_calls=[];revision='1'
        async def handler(request):
            calls.append(request)
            if len(calls)==1:entered.set();await release.wait()
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"reply":"Hello"}'}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(AISettings(enabled=True,provider='local'),client,clock=lambda:clock_calls.append(1) or 0)
            first=asyncio.create_task(adapter.generate(AIInput(stage='chat',conversation=[{'role':'user','content':'First'}]),Operation('first','1','chat'),current_revision=lambda:'1'))
            await asyncio.wait_for(entered.wait(),2)
            count=len(clock_calls)
            request=AIInput(stage='chat',conversation=[{'role':'user','content':'Queued original'}]);operation=Operation('second','1','chat')
            queued=asyncio.create_task(adapter.generate(request,operation,current_revision=lambda:revision))
            await asyncio.sleep(0)
            assert len(clock_calls)==count  # No inference deadline starts in the queue.
            if change=='stale':revision='2'
            elif change=='cancelled':operation.cancel()
            else:request.conversation[0].content='Mutated after submission'
            release.set();await first
            if change in ('stale','cancelled'):
                with pytest.raises(AIError,match='stale_input' if change=='stale' else 'cancelled'):await queued
                assert len(calls)==1
            else:
                assert (await queued).data.reply=='Hello'
                assert 'Queued original' in calls[1].content.decode() and 'Mutated after submission' not in calls[1].content.decode()
    asyncio.run(run())


def results():return {'results':[
    {'url':'https://public.test/jobs/analyst?utm_source=search','title':'Analyst internship',
     'content':'SQL required. An interview includes a coding exercise.',
     'summary':'An unsupported generated summary.', 'date':'2026-01-01T00:00:00Z'},
    {'url':'https://missing.test','title':'No page content','content':'','summary':'This is not an original source quote.'},
    {'url':'http://127.0.0.1/private','content':'Private content.'},
    {'url':'https://unsafe.test?api_key=private','content':'Unsafe citation.'},
]}


@pytest.mark.parametrize('method',['collect_query','collect_opportunity_query','collect_discovery_query'])
def test_deepseek_search_normalizes_real_page_content_for_all_workflows(method):
    async def run():
        calls=[]
        def handler(request):calls.append(request);return httpx.Response(200,json=results())
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source=DeepSeekSearch(client,api_key='synthetic-search')
            values=await getattr(source,method)(ResearchContext(role='Analyst',field='Data'),'Example Analyst Singapore interview')
        assert len(values)==1 and values[0].url=='https://public.test/jobs/analyst'
        assert 'SQL required' in values[0].evidence and 'unsupported generated' not in values[0].evidence
        assert values[0].source_id.startswith('deepseek-')
        assert str(values[0].published_date)=='2026-01-01'
        request=calls[0];assert request.method=='POST' and str(request.url)=='https://api.deepseek.com/v1/tools/search'
        assert request.headers['authorization']=='Bearer synthetic-search'
        assert json.loads(request.content)['need_content'] is True
        if method=='collect_discovery_query':assert values[0].company is None
    asyncio.run(run())


@pytest.mark.parametrize('status,payload',[(401,{}),(403,{}),(402,{}),(500,{}),(200,{'error':{'message':'PRIVATE'}}),(200,{'results':{}})])
def test_search_failures_are_actionable_without_provider_prose(status,payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(status,json=payload))) as client:
            with pytest.raises(GoalError) as error:await DeepSeekSearch(client,api_key='synthetic').search('interview')
        assert error.value.status==503 and 'PRIVATE' not in str(error.value)
    asyncio.run(run())


def test_search_quota_and_query_response_bounds():
    async def run():
        calls=[]
        def handler(request):calls.append(request);return httpx.Response(429,headers={'retry-after':'12'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SourceRateLimit) as error:await DeepSeekSearch(client,api_key='synthetic').search('Public role '*30+'interview stages')
        assert error.value.retry_after==12 and error.value.provider=='deepseek'
        query=json.loads(calls[0].content)['query'];assert len(query)<=128 and query.endswith('interview stages')
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,content=b'x'*(256*1024+1)))) as client:
            with pytest.raises(GoalError,match='exceeded'):await DeepSeekSearch(client,api_key='synthetic').search('interview')
    asyncio.run(run())


@pytest.mark.parametrize('topic,clarification',[('off_topic',None),('edit',None),('role','Which role detail do you mean?')])
def test_unrelated_edit_and_ambiguous_questions_never_search(monkeypatch,topic,clarification):
    async def run():
        request,body,*_=environment();body.conversation=[];body.message='A synthetic question'
        class Store:
            def __init__(self,*args):pass
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


def test_deepseek_search_can_enable_opportunity_pipeline_without_brave_settings():
    from app.ai.opportunity_config import OpportunitySettings
    from app.workflows.opportunity.engine import availability_issues
    from app.schemas.opportunity_api import OpportunityView
    ai=NS(settings=NS(enabled=True,provider='local'),context_enabled=True)
    assert availability_issues(OpportunitySettings(),ai,DeepSeekSearch(None,api_key='synthetic'))==[]
    assert availability_issues(OpportunitySettings(),ai,DeepSeekSearch(None))==['search_not_configured']
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
            def fetch(self,*args):return {'role':'Analyst','field':'Data','company':'Public Example','location':'Singapore'},{}
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
        monkeypatch.setattr('app.workflows.context_chat.selected_facts',lambda *args:([{'ref':'f1','data':{'name':'SQL'}}],{'f1':[]},False))
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
