"""Useful-source retention, bounded follow-ups and explicit research outcomes."""
import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest
from app.ai.adapter import AIError
from app.ai.opportunity_contracts import StructuredFindings
from app.clients.search_sources import SourceAPIs
from app.schemas.analysis import ResearchContext,ResearchSource
from app.workflows.opportunity.domain import validate_claims
from app.workflows.opportunity.sources import retain_useful
from tests.test_opportunity import opportunity_flow,research
from tests.test_workspace import ingest


def test_three_irrelevant_results_do_not_block_better_followup_sources(opportunity_flow):
    flow=opportunity_flow;search=flow[4];collect=search.collect_opportunity_query
    primary=flow[2];generate=primary.generate
    async def sources(context,query):
        values=await collect(context,query);followup='additional' in query
        return [values[0].model_copy(update={'source_id':str(i),'url':values[0].url+f'/{followup}/{i}',
            'title':'Useful account' if followup else 'Unrelated listing',
            'evidence':values[0].evidence if followup else 'An unrelated company advert.'}) for i in range(3)]
    async def evaluate(request,operation,**kwargs):
        if request.stage=='opportunity_structure':
            data=json.loads(request.context)
            if all(s['title']=='Unrelated listing' for s in data['sources']):
                return SimpleNamespace(data=StructuredFindings(findings=[],relevant_refs=[]))
        return await generate(request,operation,**kwargs)
    search.collect_opportunity_query=sources;primary.generate=evaluate
    ingest(flow);_,result,_=research(flow)
    assert len(search.calls)==10 and result['status']=='completed'
    assert all(c['outcome']=='findings_found' and c['findings'] for c in result['categories'].values())
    assert all(s['title']=='Useful account' for s in result['sources'])
    job=flow[1].research_contexts.find_one({'kind':'opportunity_job'})
    assert all(len(v)==6 for v in job['evidence'].values())
    assert all(len(v)<=3 for v in job['retained_sources'].values())


def test_relevant_sources_without_supported_facts_have_distinct_outcome(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];generate=primary.generate
    async def evaluate(request,operation,**kwargs):
        if request.stage=='opportunity_structure':
            return SimpleNamespace(data=StructuredFindings(findings=[],relevant_refs=[0]))
        return await generate(request,operation,**kwargs)
    primary.generate=evaluate;ingest(flow);_,result,_=research(flow)
    assert result['status']=='completed' and result['sources']
    assert all(c['outcome']=='information_not_found' and not c['findings'] for c in result['categories'].values())


@pytest.mark.parametrize('code,outcome',[('invalid_output','validation_failed'),('unavailable','provider_failed'),('timeout','provider_failed')])
def test_category_failures_explain_validation_vs_provider(opportunity_flow,code,outcome):
    flow=opportunity_flow;primary=flow[2];generate=primary.generate
    async def fail(request,operation,**kwargs):
        if request.stage=='opportunity_structure' and json.loads(request.context)['category']=='interview_intelligence':
            raise AIError(code,True,reason='provenance' if code=='invalid_output' else None)
        return await generate(request,operation,**kwargs)
    primary.generate=fail;ingest(flow);_,result,_=research(flow)
    assert result['categories']['interview_intelligence']['outcome']==outcome
    assert result['categories']['interview_intelligence']['status']=='failed'
    assert any(c['findings'] for c in result['categories'].values())


def test_retained_sources_prioritise_coverage_and_keep_citations_complete():
    fields=['projects','mentorship','benefits','work_life_balance']
    sources=[ResearchSource(source_id=str(i),platform='other',url=f'https://example.test/{i}',evidence=f'Report {i}.') for i in range(4)]
    findings=[]
    for i,field in enumerate(fields):
        output=StructuredFindings(findings=[dict(field=field,value=f'Report {i}.',refs=[i],quotes=[f'Report {i}.'],
            confidence='low' if i==0 else 'medium',evidence_type='candidate_reported',scope='general' if i==0 else 'exact')])
        findings.extend(validate_claims(output,'internship_insights',sources))
    selected,retained=retain_useful('internship_insights',findings,sources)
    assert {s.source_id for s in retained}=={'1','2','3'}
    assert {f.field for f in selected}==set(fields[1:])
    assert all(set(f.source_ids)<={s.source_id for s in retained} for f in selected)


def test_opportunity_keeps_longer_brave_excerpts_without_full_page_fetching():
    text='Internship account. '+('Detailed project and mentorship information. '*120)+' End of account.'
    async def run():
        def handler(request):
            assert request.url.path=='/res/v1/llm/context'
            return httpx.Response(200,json={'grounding':{'generic':[{'url':'https://example.test/account','snippets':[text]}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sources=await SourceAPIs(client,brave_key='synthetic').collect_opportunity_query(ResearchContext(role='Intern',field='Data'),'internship account')
        assert len(sources)==1 and 2400<len(sources[0].evidence)<=8000
        assert 'End of account.' in sources[0].evidence
    asyncio.run(run())


def test_failed_category_refresh_keeps_previously_validated_findings(opportunity_flow):
    from tests.test_workspace import headers
    flow=opportunity_flow;ingest(flow);workspace,first,path=research(flow)
    primary=flow[2];generate=primary.generate
    async def fail(request,operation,**kwargs):
        if request.stage=='opportunity_structure' and json.loads(request.context)['category']=='company_intelligence':
            raise AIError('unavailable',True)
        return await generate(request,operation,**kwargs)
    primary.generate=fail
    response=flow[0].post(path,headers=headers(),json={'expected_version':workspace['current']['goal']['version'],
        'expected_selection_version':workspace['current']['selection_version'],'refresh':True,'category':'company_intelligence'})
    assert response.status_code==202
    _,refreshed,_=research(flow)
    result=refreshed['categories']['company_intelligence']
    assert result['status']=='partial' and result['outcome']=='provider_failed'
    assert result['findings']==first['categories']['company_intelligence']['findings']
    assert set(result['source_ids'])<={s['source_id'] for s in refreshed['sources']}
