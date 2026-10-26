"""Official LLM Context envelope, bounded extraction and real-evidence source counts."""
import asyncio
from types import SimpleNamespace
import httpx
import pytest
from app.clients.search_sources import SourceAPIs,error_excerpt
from app.repositories.goals import GoalError
from app.ai.adapter import AIError
from app.ai.research_planning import ResearchAssessment
from app.workflows import research_search
from app.schemas.analysis import ResearchContext,ResearchSource


def test_llm_context_request_uses_its_own_parameters_and_extracts_content_not_metadata():
    async def run():
        calls=[]
        def handler(request):
            calls.append(request)
            assert request.method=='GET' and request.url.path=='/res/v1/llm/context'
            params=request.url.params
            assert params['country']=='ALL' and params['count']=='20'
            assert params['maximum_number_of_urls']=='5' and params['maximum_number_of_tokens']=='2048'
            assert params['maximum_number_of_tokens_per_url']=='512' and params['context_threshold_mode']=='balanced'
            assert 'extra_snippets' not in params and 'text_decorations' not in params
            assert request.headers['X-Subscription-Token']=='fixture'
            return httpx.Response(200,json={'grounding':{'generic':[
                {'url':'https://example.test/a','title':'Interview report','snippets':['Three interview rounds include an SQL assessment.']},
                {'url':'https://example.test/a','snippets':['A technical interview is reported.']},
                {'url':'https://example.test/empty','snippets':[]},
                {'url':'https://example.test/error','snippets':['Key not specified']},
                {'url':'https://example.test/b','snippets':['A behavioural interview is reported.']},
                {'url':'http://127.0.0.1/private','snippets':['An interview is reported.']}]},
                'sources':{'https://example.test/b':{'title':'Second interview report'},'https://example.test/empty':{'description':'Metadata is not evidence'}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sources=await SourceAPIs(client,brave_key='fixture').collect_query(ResearchContext(role='Analyst',field='Data',location='Singapore'),'Analyst Singapore interview')
        assert len(calls)==1 and len(sources)==2
        assert {s.url for s in sources}=={'https://example.test/a','https://example.test/b'}
        assert sources[1].title=='Second interview report'
        assert 'SQL assessment' in sources[0].evidence and len(sources[0].evidence)<=600
    asyncio.run(run())


@pytest.mark.parametrize('payload',[{'error':'key not specified'},{'message':'key not specified'},'key not specified',{}])
def test_error_envelopes_are_never_research_results(payload):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as client:
            with pytest.raises(GoalError):await SourceAPIs(client,brave_key='fixture').brave('Analyst interview')
    asyncio.run(run())


def test_empty_grounding_and_metadata_only_are_not_counted_as_sources():
    async def run():
        payload={'grounding':{'generic':[]},'sources':{'https://example.test/x':{'title':'Interview report'}}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _:httpx.Response(200,json=payload))) as client:
            assert await SourceAPIs(client,brave_key='fixture').brave('Analyst interview')==[]
    asyncio.run(run())


@pytest.mark.parametrize('content',['Key not specified','"API key not provided."','{"error":"key not specified"}','Error: authentication failed'])
def test_standalone_error_text_is_not_interview_evidence(content):
    assert error_excerpt(content)
    assert not error_excerpt('In the technical interview, explain how to handle an API key not specified by a client.')


@pytest.mark.parametrize('text,quote',[('Key not specified','Key not specified'),('An SQL assessment is reported.','Invented three interview rounds.')])
def test_useful_source_count_requires_a_real_supporting_quote(monkeypatch,text,quote):
    async def run():
        async def renew(*args):pass
        monkeypatch.setattr(research_search,'renew',renew)
        async def goal(state):return SimpleNamespace(id='0'*24,role='Analyst',field='Data',company=None,location=None,seniority_level=None)
        class AI:
            async def generate(self,request,operation,**kwargs):
                output=ResearchAssessment(useful_sources=[{'ref':'s0','quote':quote}])
                kwargs['validate_output'](output)
                return SimpleNamespace(data=output)
        workflow=SimpleNamespace(goal=goal,app=SimpleNamespace(state=SimpleNamespace(ai=AI())))
        source=ResearchSource(source_id='a',platform='other',url='https://example.test/report',evidence=text)
        state={'owner':'synthetic','sources':[source.model_dump(mode='json')],'latest_source_ids':['a']}
        with pytest.raises(AIError,match='invalid_output'):await research_search.assess(workflow,state)
    asyncio.run(run())


def test_interview_passage_after_long_navigation_is_preserved():
    from app.clients.search_sources import search_evidence
    passage='At Example Bank, Analyst candidates complete an SQL assessment followed by a technical interview.'
    result=search_evidence({'extra_snippets':['Browse vacancies and sign up for alerts. '*35+passage]})
    assert passage in result and len(result)<=600


def test_legacy_followup_search_keeps_company_and_location():
    async def run():
        async with httpx.AsyncClient() as client:
            provider=SourceAPIs(client,brave_key='fixture')
            context=ResearchContext(company='Example Bank',role='Analyst',field='Data',location='Singapore')
            for round in (0,1):
                query=provider.query(context,round)
                assert 'Example Bank' in query and 'Singapore' in query
    asyncio.run(run())


def test_assessment_keeps_complete_bounded_evidence():
    from app.ai.contracts import AIInput
    from app.ai.research_planning import planning_input
    text=('技術資料 '*75)+'Three interview rounds include an SQL assessment.'
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/report',evidence=text)
    request=AIInput(stage='research_assess',public_context=ResearchContext(role='Analyst',field='Data'),sources=[source])
    assert planning_input(request)['sources'][0]['excerpt']==text


def test_slow_round_stops_searching_with_time_left_for_synthesis(monkeypatch):
    from app.ai.recovery import validation_budget
    async def run():
        async def renew(*args):pass
        monkeypatch.setattr(research_search,'renew',renew)
        async def goal(state):return SimpleNamespace(id='0'*24,role='Analyst',field='Data',company=None,location=None,seniority_level=None)
        class AI:
            async def generate(self,request,operation,**kwargs):
                output=ResearchAssessment(useful_sources=[{'ref':'s0','quote':'An SQL assessment is reported.'}])
                kwargs['validate_output'](output)
                return SimpleNamespace(data=output)
        class Workspaces:
            def phase(self,*args,**kwargs):pass
        workflow=SimpleNamespace(goal=goal,app=SimpleNamespace(state=SimpleNamespace(ai=AI())),workspaces=Workspaces())
        source=ResearchSource(source_id='a',platform='other',url='https://example.test/report',evidence='An SQL assessment is reported.')
        state={'owner':'synthetic','session':'session','run':'run','sources':[source.model_dump(mode='json')],'latest_source_ids':['a']}
        async with asyncio.timeout(90) as budget:
            token=validation_budget.set(budget)
            try:result=await research_search.assess(workflow,state)
            finally:validation_budget.reset(token)
        assert result['search_exhausted'] and result['useful_source_ids']==['a']
        assert result['coverage'][0]['limit_reached']
    asyncio.run(run())
