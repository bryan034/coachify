from tests.api_views import saved_research
"""Gemini query planning and useful-source coverage; synthetic public API fixtures."""
import json
from types import SimpleNamespace
from urllib.parse import parse_qs
import asyncio
import httpx
import pytest
from app.ai.adapter import AIAdapter,AIError,Operation
from app.ai.config import GeminiSettings
from app.ai.contracts import AIInput
from app.ai.research_planning import ResearchPlan,ResearchAssessment
from app.ai.routing import ModelRouter
from app.ai.usage import input_tokens
from app.clients.search_sources import SourceAPIs
from app.schemas.analysis import ResearchSource,ResearchContext
from tests.test_workspace import flow,ingest,wait,TEXT


def source(name,useful=True,url=None,evidence=None):
    return ResearchSource(source_id=name,platform='other',title=('Useful ' if useful else 'Generic ')+name,
        url=url or f'https://example.test/{name}',evidence=evidence or (TEXT+' Public report '+name if useful else 'Browse our jobs and create a candidate account. '+name))


class Search:
    brave_mode='search'
    cache_policy='synthetic-planned-research'
    def __init__(self,batches):self.batches=batches;self.calls=[]
    async def collect_query(self,context,query):
        self.calls.append(query)
        return self.batches[min(len(self.calls)-1,len(self.batches)-1)]


class Gemini:
    def __init__(self,quota=False):self.calls=[];self.quota=quota
    async def generate(self,request,operation,**kwargs):
        self.calls.append(request)
        if request.stage=='research_plan':
            assert request.public_context and not request.conversation and not request.context
            result=ResearchPlan(queries=['Analyst interview process rounds','Analyst technical interview experiences','Analyst coding assessment stages'])
        else:
            assert request.stage=='research_assess'
            if self.quota:self.quota=False;raise AIError('rate_limited',limit_scope='provider',retry_after=1)
            result=ResearchAssessment(useful_sources=[{'ref':f's{i}','quote':v.evidence[:120]} for i,v in enumerate(request.sources) if v.title.startswith('Useful')],
                                      next_queries=['Analyst technical interview experiences'])
        if kwargs.get('validate_output'):kwargs['validate_output'](result)
        return SimpleNamespace(data=result)


def configure(flow,batches,quota=False):
    search=Search(batches);gemini=Gemini(quota)
    flow[0].app.state.research_client=search
    flow[0].app.state.ai=ModelRouter(flow[2],gemini)
    return search,gemini


def test_search_planning_payloads_are_public_bounded_and_country_matches_address():
    async def run():
        seen=[]
        def provider(req):
            data=json.loads(req.content);seen.append(data)
            assert req.url.host=='generativelanguage.googleapis.com'
            output={'queries':['DBS technology internship Singapore interview process']} if len(seen)==1 else {'useful_sources':[{'ref':'s0','quote':TEXT}],'next_queries':[]}
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
        context=ResearchContext(company='DBS Bank Ltd',role='Internship',field='Technology and AI & Data Science',location='DBS Asia Central, Singapore')
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            adapter=AIAdapter(GeminiSettings(enabled=True,api_key='fixture'),client)
            for stage in ('research_plan','research_assess'):
                request=AIInput(stage=stage,public_context=context,sources=[source('a')]*5 if stage=='research_assess' else [],research_hints=['Python','Machine learning'])
                await adapter.generate(request,Operation('owner','1',stage),current_revision=lambda:'1')
        assert all(input_tokens(v)<4000 for v in seen)
        assert all('source_ids' not in v['messages'][1]['content'] and 'conversation' not in v['messages'][1]['content'] for v in seen)
        calls=[]
        def search(req):
            calls.append(req)
            assert req.url.path.endswith('/llm/context')
            assert req.url.params['country']=='ALL' and req.url.params['maximum_number_of_urls']=='6'
            assert req.url.params['q']=='DBS technology internship Singapore interview process'
            return httpx.Response(200,json={'grounding':{'generic':[]},'sources':{}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(search)) as client:
            assert await SourceAPIs(client,brave_key='fixture').collect_query(context,'DBS technology internship Singapore interview process')==[]
        assert len(calls)==1
    asyncio.run(run())


def test_research_expands_past_irrelevant_and_duplicate_results_until_three_useful_sources(flow):
    a,b,c=source('a'),source('b'),source('c')
    duplicate=source('repost',url='https://another.test/repost',evidence=a.evidence)
    search,gemini=configure(flow,[[source(f'noise{i}',False) for i in range(4)]+[a],[duplicate,b,c]])
    assert ingest(flow).status_code==202
    current=wait(flow)
    assert len(search.calls)==2 and len(set(search.calls))==2
    assert {s['source_id'] for s in saved_research(flow,current)['sources']}=={'a','b','c'}
    assert current['coverage'][-1]['useful_sources']==3 and not current['coverage'][-1]['limit_reached']
    assert len([v for v in gemini.calls if v.stage=='research_assess'])==2
    # Adequate public research is reused without new searches for the same context.
    ingest(flow,'Another source JD. SQL is required.');wait(flow)
    assert len(search.calls)==2


def test_repeated_single_source_does_not_fake_three_sources_or_repeat_assessment(flow):
    search,gemini=configure(flow,[[source('a')]])
    ingest(flow);current=wait(flow)
    assert len(search.calls)==3 and len(set(search.calls))==3
    assert len(saved_research(flow,current)['sources'])==1
    assert current['coverage'][-1]['useful_sources']==1 and current['coverage'][-1]['limit_reached']
    assert len([v for v in gemini.calls if v.stage=='research_assess'])==1
    assert all('Analyst' in q for q in search.calls)


def test_no_useful_evidence_finishes_as_no_findings_without_synthesis(flow):
    search,gemini=configure(flow,[[source('noise',False)]])
    ingest(flow);current=wait(flow)
    assert len(search.calls)==2 and saved_research(flow,current)['research_status']=='no_findings'
    assert saved_research(flow,current)['sources']==[] and current['coverage'][-1]['useful_sources']==0
    assert not any(v.stage=='interview_synthesis' for v in flow[2].calls)


def test_assessment_quota_resumes_without_repeating_successful_search(flow):
    search,gemini=configure(flow,[[source('a'),source('b'),source('c')]],quota=True)
    ingest(flow);current=wait(flow)
    assert current['coverage'][-1]['useful_sources']==3
    assert len(search.calls)==1
    assert len([v for v in gemini.calls if v.stage=='research_assess'])==2


def test_partial_evidence_is_reused_instead_of_repeating_exhausted_searches(flow):
    search,_=configure(flow,[[source('a')]])
    ingest(flow);first=wait(flow)
    assert len(search.calls)==3 and first['coverage'][-1]['limit_reached']
    ingest(flow,'Another source JD. SQL is required.');second=wait(flow)
    assert len(search.calls)==3 and second['research_id']==first['research_id']


def test_later_search_timeout_keeps_assessed_evidence_and_opens_chat(flow):
    search,_=configure(flow,[[source('a')]])
    original=search.collect_query
    async def collect(context,query):
        if search.calls:raise TimeoutError()
        return await original(context,query)
    search.collect_query=collect
    ingest(flow);current=wait(flow)
    assert [s['source_id'] for s in saved_research(flow,current)['sources']]==['a']
    assert current['coverage'][-1]['status']=='unavailable'
