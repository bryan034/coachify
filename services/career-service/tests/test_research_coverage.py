"""Useful-source retention, bounded follow-ups and explicit research outcomes."""
import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest
from app.ai.adapter import AIError
from app.ai.opportunity_contracts import StructuredFindings,Triage
from app.clients.search_sources import SourceAPIs
from app.schemas.analysis import ResearchContext,ResearchSource
from app.workflows.opportunity.domain import validate_claims
from app.workflows.opportunity.sources import retain_useful
from app.workflows.opportunity.topics import policy,settled
from tests.test_opportunity import opportunity_flow,research,RUN_SEARCHES
from tests.test_workspace import ingest


def test_pages_rejected_at_triage_are_never_read_and_better_second_results_are(opportunity_flow):
    flow=opportunity_flow;search=flow[4];collect=search.collect_opportunity_query
    primary=flow[2];generate=primary.generate;triaged=[]
    async def sources(context,query,max_sources=5):
        values=await collect(context,query);followup='additional' in query
        return [values[0].model_copy(update={'url':values[0].url+f'/{followup}/{i}',
            'title':'Useful account' if followup else 'Unrelated listing',
            'evidence':values[0].evidence if followup else 'An unrelated company advert.'}) for i in range(max_sources)]
    async def evaluate(request,operation,**kwargs):
        if request.stage=='opportunity_triage':
            data=json.loads(request.context);triaged.append(data)
            assert all(set(page)<={'ref','url','title','description','published_date'} for page in data['pages'])
            output=Triage(pages=[{'ref':page['ref'],'topics':[t for t in data['topics'] if t in page['url']]}
                for page in data['pages'] if page['title']=='Useful account'])
            kwargs['validate_output'](output)
            return SimpleNamespace(data=output)
        return await generate(request,operation,**kwargs)
    search.collect_opportunity_query=sources;primary.generate=evaluate
    ingest(flow);_,result,_=research(flow)
    assert len(search.calls)==RUN_SEARCHES and result['status']=='completed'
    assert any(page['title']=='Unrelated listing' for data in triaged for page in data['pages'])
    read=[s for call in primary.calls if call.stage=='opportunity_structure' for s in json.loads(call.context)['sources']]
    assert read and all(s['title']=='Useful account' for s in read)
    assert all(c['outcome']=='findings_found' and c['findings'] for c in result['categories'].values())
    assert all(s['title']=='Useful account' for s in result['sources'])
    job=flow[1].research_contexts.find_one({'kind':'opportunity_job'})
    assert all(len(ids)<=policy(topic).max_urls for topic,ids in job['read'].items())


def test_a_factual_topic_backed_by_two_sites_is_not_searched_again(opportunity_flow):
    flow=opportunity_flow;search=flow[4];collect=search.collect_opportunity_query
    primary=flow[2];generate=primary.generate
    async def two_sites(context,query,max_sources=5):
        first=(await collect(context,query))[0]
        return [first.model_copy(update={'url':f'https://site{i}.example/{first.source_id}'}) for i in range(2)]
    async def evaluate(request,operation,**kwargs):
        data=json.loads(request.context) if request.stage=='opportunity_structure' else {}
        if data.get('category')!='internship_insights':return await generate(request,operation,**kwargs)
        passages=[p for p in data['evidence'] if 'SGD 1500' in p['text']][:2]
        output=StructuredFindings(findings=[{'field':'compensation','value':p['text'],'refs':[p['source_ref']],'quotes':[p['text']],
            'confidence':'medium','evidence_type':'candidate_reported','scope':'exact'} for p in passages])
        kwargs['validate_output'](output)
        return SimpleNamespace(data=output)
    search.collect_opportunity_query=two_sites;primary.generate=evaluate
    ingest(flow);_,result,_=research(flow)
    pay=[f for f in result['categories']['internship_insights']['findings'] if f['field']=='compensation']
    assert pay and len({sid for f in pay for sid in f['source_ids']})>=2
    assert len([q for q in search.calls if q.endswith('compensation')])==1
    assert len([q for q in search.calls if q.endswith('benefits')])==2


def test_settling_needs_distinct_agreeing_sites_and_reviews_need_more():
    def finding(field,sid,conflict=None):
        return SimpleNamespace(field=field,source_ids=[sid],conflict_group=conflict)
    sources=[ResearchSource(source_id=str(i),platform='other',url=f'https://site{i}.example/page') for i in range(5)]
    same=[ResearchSource(source_id=str(i),platform='other',url=f'https://www.one.example/{i}') for i in range(2)]
    assert settled('compensation',[finding('compensation','0'),finding('compensation','1')],sources)
    assert not settled('compensation',[finding('compensation','0'),finding('compensation','1')],same)
    assert not settled('compensation',[finding('compensation','0','pay'),finding('compensation','1','pay')],sources)
    assert not settled('mentorship',[finding('mentorship',str(i)) for i in range(3)],sources)
    assert settled('mentorship',[finding('mentorship',str(i)) for i in range(4)],sources)


def test_relevant_sources_without_supported_facts_have_distinct_outcome(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];generate=primary.generate
    async def evaluate(request,operation,**kwargs):
        if request.stage=='opportunity_structure':
            return SimpleNamespace(data=StructuredFindings(findings=[],relevant_refs=[0]))
        return await generate(request,operation,**kwargs)
    primary.generate=evaluate;ingest(flow);_,result,_=research(flow)
    assert result['status']=='completed' and result['sources']
    assert all(c['outcome']=='information_not_found' and not c['findings'] for c in result['categories'].values())


def test_a_round_that_fails_validation_moves_on_to_the_next_search(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];generate=primary.generate;failed=[]
    async def evaluate(request,operation,**kwargs):
        if request.stage=='opportunity_structure' and json.loads(request.context)['category']=='interview_intelligence' and not failed:
            failed.append(True);raise AIError('invalid_output',True,reason='provenance')
        return await generate(request,operation,**kwargs)
    primary.generate=evaluate;ingest(flow);_,result,_=research(flow)
    interview=result['categories']['interview_intelligence']
    assert failed and interview['status']=='completed' and interview['outcome']=='findings_found' and interview['findings']


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


def test_each_topic_keeps_its_own_best_sources_and_only_the_cited_passages():
    sources=[ResearchSource(source_id=str(i),platform='other',url=f'https://site{i%4}.example/{i}',evidence=f'Report {i}. Unrelated filler text.') for i in range(12)]
    findings=[]
    def add(field,i,scope='exact'):
        output=StructuredFindings(findings=[dict(field=field,value=f'Report {i}.',refs=[i],quotes=[f'Report {i}.'],
            confidence='medium',evidence_type='candidate_reported',scope=scope)])
        findings.extend(validate_claims(output,'internship_insights',sources))
    for i in range(5):add('compensation',i,'general' if i==0 else 'exact')
    for i in range(5,12):add('mentorship',i)
    kept,retained=retain_useful('internship_insights',findings,sources)
    cited={}
    for f in kept:cited.setdefault(f.field,set()).update(f.source_ids)
    assert cited['compensation']=={'1','2'}
    assert len(cited['mentorship'])==4
    assert {s.source_id for s in retained}==cited['compensation']|cited['mentorship']
    assert all(s.evidence==f'Report {s.source_id}.' for s in retained)


def test_relevant_pages_without_findings_keep_only_a_short_excerpt():
    sources=[ResearchSource(source_id=str(i),platform='other',url=f'https://example.test/{i}',evidence='Detailed report. '*200) for i in range(5)]
    kept,retained=retain_useful('internship_insights',[],sources,{'0','1','2','3'})
    assert not kept and len(retained)==3 and all(len(s.evidence)<=600 for s in retained)


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


def test_only_transient_search_failures_are_retried():
    from app.clients.search_sources import SearchBackendError
    from app.repositories.goals import GoalError
    from app.workflows.opportunity.engine import transient
    def wrapped(cause):
        try:
            try:raise cause
            except type(cause):raise GoalError('Search failed.',503) from None
        except GoalError as error:return error
    assert transient(TimeoutError()) and transient(wrapped(httpx.ConnectError('down')))
    assert transient(SearchBackendError('unavailable','Search is down.'))
    assert not transient(SearchBackendError('access','Check access.'))
    assert not transient(GoalError('Search credentials need checking.',503))


def test_reads_take_a_topics_own_triaged_results_first_within_its_allowances():
    from app.workflows.opportunity.sources import choose_reads
    def page(name):return ResearchSource(source_id=name,platform='other',url=f'https://{name}.example/page',evidence='Synthetic page.')
    found={'compensation':[page(f'pay{i}') for i in range(4)],'benefits':[page(f'perk{i}') for i in range(3)]}
    flags={**{f'pay{i}':{'compensation'} for i in range(4)},'perk0':{'benefits','compensation'},'perk1':{'compensation'},'perk2':{'benefits'}}
    picks,reads=choose_reads(['compensation','benefits'],found,flags,{'compensation':['pay0']})
    assert reads['compensation']==['pay1','pay2','perk0','perk1']
    assert reads['benefits']==['perk0','perk2']
    assert {p.source_id for p in picks}=={'pay1','pay2','perk0','perk1','perk2'}
    _,reads=choose_reads(['compensation'],found,flags,{'compensation':['pay0','pay1','pay2','perk0']})
    assert reads['compensation']==['pay3']


def test_triage_sees_only_metadata_and_is_bound_to_the_request():
    from app.ai.opportunity_contracts import TRIAGE_PREVIEW,triage_input,triage_schema
    sources=[ResearchSource(source_id=str(i),platform='other',url=f'https://example.test/{i}',title=f'Page {i}',evidence='word '*400) for i in range(3)]
    context=triage_input({'company':'Example'},['compensation','mentorship'],sources)
    assert all(len(page['description'])<=TRIAGE_PREVIEW+1 for page in context['pages'])
    assert 'evidence' not in json.dumps(context['pages'])
    schema=triage_schema(context)
    page=schema['$defs']['PageTopics']['properties']
    assert page['ref']['enum']==[0,1,2] and page['topics']['items']['enum']==['compensation','mentorship']
    with pytest.raises(ValueError):triage_schema({**context,'topics':{'salary':'not a topic'}})


def test_a_page_read_for_one_category_can_back_another_categorys_topic(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];generate=primary.generate
    async def evaluate(request,operation,**kwargs):
        result=await generate(request,operation,**kwargs)
        data=json.loads(request.context) if request.stage=='opportunity_structure' else {}
        if data.get('category')=='internship_insights':
            assert 'company_culture' in data['allowed_fields']
            text=data['evidence'][0]['text']
            extra=StructuredFindings(findings=[{'field':'company_culture','value':text,'refs':[0],'quotes':[text],
                'confidence':'medium','evidence_type':'candidate_reported','scope':'exact'}])
            kwargs['validate_output'](extra)
            result.data.findings.extend(extra.findings)
        return result
    primary.generate=evaluate;ingest(flow);_,result,_=research(flow)
    culture=[f for f in result['categories']['company_intelligence']['findings'] if f['field']=='company_culture']
    assert any('SGD 1500' in f['value'] for f in culture)
    company=result['categories']['company_intelligence']
    assert all(sid in company['source_ids'] for f in culture for sid in f['source_ids'])
    assert not any(f['field']=='company_culture' for f in result['categories']['internship_insights']['findings'])


def test_an_unusable_triage_falls_back_to_each_topics_own_top_results(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];generate=primary.generate
    async def evaluate(request,operation,**kwargs):
        if request.stage=='opportunity_triage':raise AIError('invalid_output',True,reason='provenance')
        return await generate(request,operation,**kwargs)
    primary.generate=evaluate;ingest(flow);_,result,_=research(flow)
    assert result['status']=='completed'
    assert all(c['findings'] for c in result['categories'].values())
