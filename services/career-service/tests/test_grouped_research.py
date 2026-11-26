"""Grouped first searches, run-wide triage, ranked gap searches and usage counters."""
import asyncio
import json
import pytest
from types import SimpleNamespace

from app.ai.adapter import record_usage
from app.ai.metrics import observe_usage,usage_counts,usage_observer
from app.ai.opportunity_config import OpportunitySettings
from app.schemas.opportunity import CATEGORIES
from app.workflows.opportunity.engine import MODEL_TOKENS,RESERVED_TOKENS,SEARCH_TOKENS,OpportunityEngine
from app.workflows.opportunity.topics import GROUPS,gap_rank
from tests.test_opportunity import opportunity_flow,query_group,research
from tests.test_workspace import ingest


def test_gap_searches_reserve_factual_topics_without_findings_first():
    engine=object.__new__(OpportunityEngine);engine.settings=OpportunitySettings(run_searches=2)
    reservations=[];searched=[]
    def reserve(*args):
        reservations.append(1)
        return len(reservations)<=2
    engine.store=SimpleNamespace(reserve_search=reserve)
    async def search_topic(job_id,topic,query):searched.append((topic,query))
    engine.search_topic=search_topic
    job={'_id':'synthetic','worker_token':'synthetic','public':{'company':'Example','role':'Analyst'},'history':{},'read':{},'queries':{}}
    findings=[SimpleNamespace(field='benefits')]
    asyncio.run(engine.search_gaps(job,['mentorship','benefits','compensation'],findings))
    assert sorted(['mentorship','benefits','compensation'],key=lambda t:gap_rank(t,findings))==['compensation','benefits','mentorship']
    assert [topic for topic,_ in searched]==['compensation','benefits']
    assert dict(searched)['compensation']=='Example Analyst intern salary per month'


def test_gap_searches_skip_topics_without_queries_or_read_allowance():
    engine=object.__new__(OpportunityEngine);engine.settings=OpportunitySettings()
    reservations=[]
    engine.store=SimpleNamespace(reserve_search=lambda *args:reservations.append(1) or True)
    searched=[]
    async def search_topic(job_id,topic,query):searched.append(topic)
    engine.search_topic=search_topic
    job={'_id':'synthetic','worker_token':'synthetic','public':{'company':'Example','role':'Analyst'},
         'history':{'compensation':['first','second']},'read':{'benefits':['a','b','c','d','e']},'queries':{}}
    asyncio.run(engine.search_gaps(job,['compensation','benefits','mentorship'],[]))
    assert searched==['mentorship'] and len(reservations)==1


def test_a_page_found_by_two_groups_is_triaged_and_read_once(opportunity_flow):
    flow=opportunity_flow;search=flow[4];collect=search.collect_opportunity_query;primary=flow[2]
    shared='https://example.test/compensation+conversion_rate/shared'
    async def sources(context,query,**kwargs):
        values=await collect(context,query,**kwargs)
        if query_group(query) in ('pay','conversion'):return [values[0].model_copy(update={'url':shared})]
        return values
    search.collect_opportunity_query=sources
    ingest(flow);_,result,_=research(flow)
    assert result['status']=='completed'
    assert len([page for data in primary.triaged for page in data['pages'] if page['url']==shared])==1
    reads=[json.loads(call.context)['category'] for call in primary.calls if call.stage=='opportunity_structure'
           and any(source['url']==shared for source in json.loads(call.context)['sources'])]
    assert len(reads)==1
    job=flow[1].research_contexts.find_one({'kind':'opportunity_job'})
    assert set(job['group_history'])==set(GROUPS) and job['metrics']['research_search']['searches']==job['searches_used']


def test_usage_counters_include_cached_and_reasoning_tokens():
    usage={'prompt_tokens':900,'completion_tokens':100,'total_tokens':1000,'prompt_tokens_details':{'cached_tokens':600},
           'completion_tokens_details':{'reasoning_tokens':40},'cost':'not-a-count'}
    assert usage_counts(usage)=={'prompt_tokens':900,'completion_tokens':100,'total_tokens':1000,'cached_tokens':600,'reasoning_tokens':40}
    assert usage_counts(None)=={} and usage_counts({'prompt_tokens':-1})=={}
    seen=[];token=usage_observer.set(seen.append)
    try:
        record_usage(json.dumps({'usage':usage,'choices':[{'finish_reason':'stop'}]}),'opportunity_plan',1,1)
        observe_usage({'prompt_tokens':50,'completion_tokens':5,'total_tokens':55})
    finally:usage_observer.reset(token)
    assert seen[0]['cached_tokens']==600 and seen[0]['reasoning_tokens']==40
    assert seen[1]=={'prompt_tokens':50,'completion_tokens':5,'total_tokens':55}


def test_first_gap_round_shares_remaining_searches_by_category_topics():
    engine=object.__new__(OpportunityEngine);engine.settings=OpportunitySettings(run_searches=25)
    job={'requested':list(CATEGORIES),'group_history':{group:['query'] for group in GROUPS}}
    shares={c:engine.gap_share(job,c)[1] for c in CATEGORIES}
    assert shares=={'interview_intelligence':6,'internship_insights':4,'career_progression':3,'conversion_outcomes':3,'company_intelligence':2}
    assert engine.gap_share({'requested':['company_intelligence'],'group_history':{'culture':['query']}},'company_intelligence')==('gap_searches.company_intelligence',24)


def test_a_category_share_caps_its_reservations_but_not_the_run(opportunity_flow):
    store=opportunity_flow[0].app.state.opportunities.store
    store.rows.insert_one({'_id':'synthetic-share','worker_token':'synthetic','searches_used':0})
    share=('gap_searches.interview_intelligence',1)
    assert store.reserve_search('synthetic-share','synthetic',3,share)
    assert not store.reserve_search('synthetic-share','synthetic',3,share)
    assert store.reserve_search('synthetic-share','synthetic',3,('gap_searches.company_intelligence',1))
    assert store.reserve_search('synthetic-share','synthetic',3)
    assert not store.reserve_search('synthetic-share','synthetic',3)
    assert store.rows.find_one({'_id':'synthetic-share'})['searches_used']==3


def test_shared_topic_survives_extraction_by_its_first_category(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];generate=primary.generate
    async def extract(request,operation,**kwargs):
        result=await generate(request,operation,**kwargs)
        if request.stage=='opportunity_structure':
            if json.loads(request.context)['category']=='internship_insights':
                result.data.findings[0].field='work_life_balance'
            else:result.data.findings=[]
        return result
    primary.generate=extract
    ingest(flow);workspace,result,_=research(flow)
    assert result['status']=='completed' and workspace['phase']=='ready',(result['status'],workspace['phase'],workspace.get('error_code'))
    ids=[]
    for category in ('internship_insights','company_intelligence'):
        shared=[f for f in result['categories'][category]['findings'] if f['field']=='work_life_balance']
        assert shared;ids+=[f['finding_id'] for f in shared]
    assert len(set(ids))==len(ids)


def test_failed_report_checks_are_logged_by_location_without_values():
    from datetime import datetime,timezone
    from pydantic import ValidationError
    from app.ai.recovery import validation_detail
    from app.schemas.opportunity import Finding
    with pytest.raises(ValidationError) as caught:
        Finding.model_validate({'finding_id':'f0123456789abcdef','field':'difficulty','value':'Synthetic private value','confidence':'medium',
            'evidence_type':'candidate_reported','source_ids':['s'],'quotes':['Synthetic private quote'],'scope':'exact',
            'last_verified_at':datetime.now(timezone.utc),'round_name':'Synthetic round'})
    detail=validation_detail(caught.value)
    assert detail==[{'model':'Finding','loc':'','type':'value_error','msg':'Value error, A round name needs its round number.'}]
    assert 'Synthetic' not in str(detail) and validation_detail(ValueError('plain')) is None


def test_cross_category_extraction_keeps_grounded_interview_rounds():
    from app.ai.opportunity_contracts import ReferencedFindings,findings_schema,structure_input
    from app.schemas.analysis import ResearchSource
    from app.workflows.opportunity.topics import TOPICS
    text='Round 2 Technical interview tests SQL joins.'
    context=structure_input({},'internship_insights',[
        ResearchSource(source_id='synthetic',platform='other',url='https://example.test/round',evidence=text)],fields=list(TOPICS))
    output=ReferencedFindings(findings=[{'field':'interview_questions','value':'SQL joins','evidence_ref':0,
        'confidence':'medium','evidence_type':'candidate_reported','scope':'exact','round_number':2,'round_name':'Technical interview'}])
    assert 'round_number' in findings_schema(context)['$defs']['ReferencedClaim']['properties']
    assert output.to_domain(context).findings[0].round_number==2


def test_later_gap_round_cannot_spend_another_categorys_first_share(opportunity_flow):
    engine=opportunity_flow[0].app.state.opportunities
    job={'_id':'synthetic-fair','worker_token':'synthetic','public':{'company':'Example','role':'Analyst'},
         'requested':list(CATEGORIES),'group_history':{g:['query'] for g in GROUPS},'searches_used':7}
    engine.store.rows.insert_one(job)
    shares={c:engine.gap_share(job,c)[1] for c in CATEGORIES}
    assert sum(shares.values())==18
    for _ in range(shares['interview_intelligence']):
        assert engine.store.reserve_search(job['_id'],job['worker_token'],25,engine.gap_share(job,'interview_intelligence'))
    searched=[]
    async def search_topic(job_id,topic,query):searched.append(topic)
    engine.search_topic=search_topic
    asyncio.run(engine.search_gaps(job,['difficulty'],[]))
    assert not searched
    engine.store.rows.update_one({'_id':job['_id']},{'$set':{'gap_complete.company_intelligence':True}})
    asyncio.run(engine.search_gaps(job,['difficulty'],[]))
    assert searched==['difficulty']


def test_prefetch_usage_is_carried_into_the_durable_job(opportunity_flow):
    from app.ai.jd_scope import JobIdentity
    from app.ai.opportunity_contracts import QueryPlan
    from app.workflows.jd_prefetch import prefetch
    flow=opportunity_flow;ingest(flow);workspace,_,_=research(flow)
    class AI:
        async def generate(self,*args,**kwargs):
            observe_usage({'prompt_tokens':100,'completion_tokens':10,'total_tokens':110})
            return SimpleNamespace(data=QueryPlan(**{g:f'Example Analyst {g}' for g in GROUPS}))
    class Search:
        async def collect_opportunity_query(self,*args,**kwargs):
            observe_usage({'prompt_tokens':200,'completion_tokens':20,'total_tokens':220,'prompt_tokens_details':{'cached_tokens':50}})
            return []
    engine=SimpleNamespace(ai=AI(),source=Search(),slots=asyncio.Semaphore(3),settings=OpportunitySettings())
    seed=asyncio.run(prefetch(engine,JobIdentity(is_job_description=True,role='Analyst',company='Example'),'synthetic-owner','revision'))
    assert seed['metrics']['research_search']['searches']==len(GROUPS)
    assert seed['metrics']['research_search']['prompt_tokens']==200*len(GROUPS)
    assert seed['metrics']['research_search']['cached_tokens']==50*len(GROUPS)
    from app.schemas.analysis import CareerGoal
    goal=CareerGoal.model_validate(workspace['current']['goal'])
    store=flow[0].app.state.opportunities.store
    row=store.start('synthetic-owner',goal,0,'synthetic-session','synthetic-run','synthetic-prefetch',{'refresh':True,'category':None},seed)
    assert row['metrics']==seed['metrics']


def test_provider_failure_releases_unprocessed_page_claims(opportunity_flow):
    from app.ai.errors import AIError
    flow=opportunity_flow;primary=flow[2];generate=primary.generate
    async def extract(request,operation,**kwargs):
        if request.stage=='opportunity_structure' and json.loads(request.context)['category']=='internship_insights':
            raise AIError('unavailable',True)
        return await generate(request,operation,**kwargs)
    primary.generate=extract
    ingest(flow);research(flow)
    job=flow[1].research_contexts.find_one({'kind':'opportunity_job'})
    assert 'internship_insights' not in job.get('claimed',{}).values()


def test_concurrent_gap_triage_reuses_run_wide_page_labels(opportunity_flow):
    from app.ai.opportunity_contracts import Triage
    from app.schemas.analysis import ResearchSource
    engine=opportunity_flow[0].app.state.opportunities
    job={'_id':'synthetic-triage','worker_token':'synthetic','public':{'company':'Example','role':'Analyst'}}
    engine.store.rows.insert_one(job)
    calls=[]
    async def generate(job,stage,data,validate=None):
        calls.append(data)
        await asyncio.sleep(.01)
        return Triage(pages=[{'ref':0,'topics':['compensation','conversion_salary']}])
    engine.generate=generate
    page=ResearchSource(source_id='synthetic-page',platform='other',url='https://example.test/pay',evidence='Example pay report.')
    async def triage():
        return await asyncio.gather(engine.triage(job,['compensation'],[page]),engine.triage(job,['conversion_salary'],[page]))
    results=opportunity_flow[0].portal.call(triage)
    assert len(calls)==1
    assert results==[{'synthetic-page':{'compensation'}},{'synthetic-page':{'conversion_salary'}}]


def budget_job(flow):
    return flow[1].research_contexts.find_one({'kind':'opportunity_job'})


def test_a_default_run_makes_every_group_search_and_one_follow_up_search(opportunity_flow):
    flow=opportunity_flow;engine=flow[0].app.state.opportunities;search=flow[4]
    engine.settings=engine.settings.model_copy(update={'run_searches':OpportunitySettings().run_searches})
    ingest(flow);workspace,result,_=research(flow)
    groups=[query_group(q) for q in search.calls]
    assert sorted(g for g in groups if g)==sorted(GROUPS) and groups.count(None)==1
    assert result['status']=='completed' and workspace['phase']=='ready'


def test_research_stops_searching_within_the_token_budget_and_finishes_in_one_run(opportunity_flow):
    flow=opportunity_flow;search=flow[4];collect=search.collect_opportunity_query
    engine=flow[0].app.state.opportunities;budget=engine.settings.token_budget
    async def metered(context,query,**kwargs):
        observe_usage({'total_tokens':13000})
        return await collect(context,query,**kwargs)
    search.collect_opportunity_query=metered
    ingest(flow);workspace,result,_=research(flow)
    job=budget_job(flow)
    assert result['status'] in ('completed','partial') and workspace['phase']=='ready'
    assert job['tokens_used']==13000*len(search.calls)<=budget-RESERVED_TOKENS+SEARCH_TOKENS*OpportunitySettings().concurrency
    assert len(search.calls)<engine.settings.run_searches


def test_research_that_spends_its_budget_ends_partial_and_starts_no_more_model_calls(opportunity_flow):
    flow=opportunity_flow;engine=flow[0].app.state.opportunities;budget=100000;size=50000
    engine.settings=engine.settings.model_copy(update={'token_budget':budget})
    search=flow[4];collect=search.collect_opportunity_query;primary=flow[2];generate=primary.generate;stages=[]
    async def metered(context,query,**kwargs):
        observe_usage({'total_tokens':size})
        return await collect(context,query,**kwargs)
    async def model(request,operation,**kwargs):
        stages.append(request.stage)
        return await generate(request,operation,**kwargs)
    search.collect_opportunity_query=metered;primary.generate=model
    ingest(flow);workspace,result,_=research(flow)
    assert budget_job(flow)['tokens_used']<=budget-RESERVED_TOKENS+size*OpportunitySettings().concurrency
    assert not {'opportunity_triage','opportunity_structure','opportunity_skill_levels'}&set(stages)
    assert result['finished'] and result['status']=='partial' and workspace['research_id']==result['research_id']
    categories=result['categories'].values()
    assert not any(v['status']=='failed' for v in categories) and any(v['error_code']=='token_budget' for v in categories)
