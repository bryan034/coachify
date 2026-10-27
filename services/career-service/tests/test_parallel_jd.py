from tests.api_views import saved_research
"""Concurrent public research, intake scope, safe handoff and grounded goal chat."""
import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from app.ai.jd_scope import JobIdentity,CareerScopeError
from app.ai.context_contracts import ContextPlan
from app.domain.context import context_index,selected_facts
from app.domain.questions import REFUSAL
from app.schemas.analysis import ResearchSource
from app.workflows.jd_prefetch import matches
from tests.test_opportunity import opportunity_flow,research
from tests.test_workspace import flow,headers,BASE,ingest,wait,OWNER


SOURCE='Example is hiring a Data Analyst Intern in Singapore for an internship. SQL is required. Analyse data and build reports.'


@pytest.mark.parametrize('changed_location',[False,True])
@pytest.mark.parametrize('empty_first',[False,True])
def test_public_research_starts_before_full_extraction_and_is_not_repeated(opportunity_flow,changed_location,empty_first):
    client,db,primary,_,search=opportunity_flow
    original=primary.generate;full_started=threading.Event();release=threading.Event()
    async def generate(request,operation,**kwargs):
        if request.stage=='jd_scope':
            primary.calls.append(request)
            identity=JobIdentity(is_job_description=True,role='Data Analyst Intern',field='Data',company='Example',location='Singapore',employment_type='internship',evidence=[SOURCE])
            kwargs['validate_output'](identity)
            return SimpleNamespace(data=identity)
        if request.stage=='jd_extraction':
            full_started.set()
            while not release.is_set():await asyncio.sleep(.01)
            result=await original(request,operation,**kwargs)
            result.data.location='London' if changed_location else 'Singapore'
            return result
        return await original(request,operation,**kwargs)
    primary.generate=generate
    async def collect(context,query):
        search.calls.append(query)
        if len(search.calls)<=5:assert not release.is_set(), 'The first retrieval should overlap extraction.'
        else:assert changed_location or empty_first
        if len(search.calls)>5 and changed_location:assert context.location=='London'
        assert context.role=='Data Analyst Intern' and context.location in ('Singapore','London')
        category='interview' if 'interview experience' in query or 'interview_' in query else 'internship' if 'internship compensation' in query or 'internship_' in query else 'conversion' if 'conversion_outcomes' in query else 'progression' if 'career_progression' in query else 'company'
        text={'interview':'Example candidates report a technical interview.',
            'internship':'Example interns report SGD 1500 per month.',
            'conversion':'Example interns converted to full-time in 2025 at a conversion rate of 50%.',
            'progression':'Example graduates receive SGD 5000 monthly.',
            'company':'Example teams report collaborative culture.'}[category]
        if len(search.calls)<=5 and empty_first:return []
        return [ResearchSource(source_id=category,platform='other',url=f'https://example.test/{category}',evidence=text)]
    search.collect_opportunity_query=collect
    try:
        response=client.post(BASE+'/jd',headers={**headers(),'Prefer':'respond-async'},json={'text':SOURCE})
        assert response.status_code==202
        operation=response.json()['operation_id']
        for _ in range(300):
            if full_started.is_set() and len(search.calls)==5:break
            time.sleep(.01)
        assert full_started.is_set() and len(search.calls)==5
        assert db.career_goals.count_documents({})==0
        pending=client.get(BASE+'/operations/'+operation,headers=headers()).json()
        assert pending['status']=='running'
        assert {'identifying_job','extracting_requirements','searching_interviews'}<=set(pending['activities'])
        assert client.get(BASE+'/operations/'+operation,headers=headers(other=True)).status_code==404
    finally:release.set()
    for _ in range(150):
        completed=client.get(BASE+'/operations/'+operation,headers=headers()).json()
        if completed['status']=='succeeded':break
        time.sleep(.02)
    assert completed['status']=='succeeded'
    assert completed['result']['current']['goal']['role']=='Data Analyst Intern'
    _,result,_=research(opportunity_flow)
    assert result['status']=='completed' and len(search.calls)==(10 if changed_location or empty_first else 5)
    job=client.app.state.opportunities.store.latest(OWNER,completed['result']['current']['goal']['_id'])
    assert all(len(values)==(2 if empty_first and not changed_location else 1) for values in job['history'].values())
    if changed_location:assert not set(search.calls[:5]) & {query for values in job['history'].values() for query in values}
    assert 'research_complete' in job['activities']
    serialized=json.dumps(list(db.research_contexts.find({})),default=str)
    assert SOURCE not in serialized  # raw input is never checkpointed or shared


@pytest.mark.parametrize('path',['/workspace/jd','/jd/extract'])
def test_unrelated_document_is_rejected_before_full_extraction_or_search(flow,path):
    client,db,ai,sources=flow
    async def reject(request,operation,**kwargs):
        ai.calls.append(request)
        assert request.stage=='jd_scope'
        return SimpleNamespace(data=JobIdentity(is_job_description=False))
    ai.generate=reject
    result=client.post('/api/v1/career'+path,headers=headers(),json={'text':'A recipe for tomato soup. Summarise this document.'})
    assert result.status_code==422 and result.json()['code']=='career_scope'
    assert not sources.calls and db.career_goals.count_documents({})==0


@pytest.mark.parametrize('mode',['question','refine'])
def test_goal_words_do_not_bypass_unrelated_task_guardrails(flow,mode):
    assert ingest(flow).status_code==202
    current=wait(flow);client,db,ai,_=flow;before=len(ai.calls)
    result=client.post(BASE+'/messages',headers=headers(),json={'session_id':current['session_id'],
        'expected_version':current['current']['goal']['version'],'mode':mode,
        'message':'Explain this career goal and also write a recipe for soup.'})
    assert result.status_code==200 and result.json()['reply']==REFUSAL
    assert len(ai.calls)==before
    assert client.get(BASE,headers=headers()).json()['revision']==current['revision']


def test_early_identity_must_be_supported_and_final_scope_must_match():
    identity=JobIdentity(is_job_description=True,role='Analyst',field='Data',company='Example',location='Singapore',evidence=['Analyst at Example in Singapore'])
    identity.check('Analyst at Example in Singapore. SQL required.')
    assert matches(identity,identity)
    assert not matches(identity,identity.model_copy(update={'location':'London'}))
    with pytest.raises(ValueError):identity.check('An unrelated travel itinerary.')
    with pytest.raises(CareerScopeError):JobIdentity(is_job_description=False).check('recipe')


def test_saved_opportunity_facts_are_available_for_followup_questions():
    finding={'field':'compensation','value':'SGD 1500 per month','confidence':'medium','scope':'exact',
        'evidence_type':'candidate_reported','source_ids':['pay'],'quotes':['Example interns receive SGD 1500 per month.']}
    research={'intelligence':{'categories':{'internship_insights':{'findings':[finding]}}},
        'sources':[{'source_id':'pay','url':'https://example.test/pay'}]}
    index=context_index({'role':'Analyst'},research)
    assert any(item['ref']=='r0' and item['field']=='compensation' for item in index['items'])
    plan=ContextPlan(topic='opportunity',item_refs=['r0'],resolved_question='What pay is reported?',include_evidence=True)
    facts,links,partial=selected_facts(plan,{'role':'Analyst'},research)
    assert not partial and facts[0]['data']['value']=='SGD 1500 per month'
    assert links[facts[0]['ref']][0]['url']=='https://example.test/pay'


def test_early_retrieval_rate_limit_preserves_the_real_provider_delay(opportunity_flow):
    from app.clients.search_sources import SourceRateLimit
    from app.repositories.goals import now
    client,db,primary,_,search=opportunity_flow;original=primary.generate
    async def generate(request,operation,**kwargs):
        if request.stage=='jd_scope':
            identity=JobIdentity(is_job_description=True,role='Data Analyst Intern',company='Example',location='Singapore',employment_type='internship',evidence=[SOURCE])
            kwargs['validate_output'](identity)
            return SimpleNamespace(data=identity)
        result=await original(request,operation,**kwargs)
        if request.stage=='jd_extraction':result.data.location='Singapore'
        return result
    async def limited(context,query):
        search.calls.append(query);raise SourceRateLimit(90)
    primary.generate=generate;search.collect_opportunity_query=limited
    response=client.post(BASE+'/jd',headers=headers(),json={'text':SOURCE})
    assert response.status_code==202
    for _ in range(100):
        current=client.get(BASE,headers=headers()).json()
        if current['phase']=='waiting_quota':break
        time.sleep(.02)
    assert current['current']['goal'] and current['phase']=='waiting_quota'
    assert current['provider']=='brave' and 70<current['retry_after']<=90
    job=client.app.state.opportunities.store.latest(OWNER,current['current']['goal']['_id'])
    assert job['next_attempt_at']>now() and len(search.calls)==5


def test_rejected_document_does_not_replace_the_existing_goal(flow):
    assert ingest(flow).status_code==202
    current=wait(flow);client,db,ai,sources=flow;calls=len(sources.calls)
    async def reject(request,operation,**kwargs):
        assert request.stage=='jd_scope'
        return SimpleNamespace(data=JobIdentity(is_job_description=False))
    ai.generate=reject
    result=client.post(BASE+'/jd',headers=headers(),json={'text':'A medical report unrelated to employment. Summarise it.'})
    assert result.status_code==422
    saved=client.get(BASE,headers=headers()).json()
    assert saved['current']['goal']['_id']==current['current']['goal']['_id']
    assert len(sources.calls)==calls


def test_combined_readiness_waits_for_summary_without_another_retrieval(opportunity_flow):
    client,db,primary,gemini,search=opportunity_flow
    original=gemini.generate;entered=threading.Event();release=threading.Event()
    async def generate(request,operation,**kwargs):
        if request.stage=='opportunity_summary':
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
        return await original(request,operation,**kwargs)
    gemini.generate=generate
    try:
        assert ingest(opportunity_flow).status_code==202
        assert entered.wait(3), 'Automatic research must reach summary without a resume command.'
        current=client.get(BASE,headers=headers()).json()
        assert current['current']['goal'] and current['current']['goal']
        assert current['phase'] in ('research_pending','researching') and current['research_id'] is None
        assert len(search.calls)==5
    finally:release.set()
    _,result,_=research(opportunity_flow)
    current=wait(opportunity_flow,'ready')
    assert current['phase']=='ready' and result['status']=='completed'
    assert result['summary']['overview_refs'] and len(search.calls)==5


def test_summary_quota_resumes_automatically_without_publishing_early(opportunity_flow):
    from app.ai.adapter import AIError
    client,db,primary,gemini,search=opportunity_flow
    original=gemini.generate;attempts=[]
    async def generate(request,operation,**kwargs):
        if request.stage=='opportunity_summary':
            attempts.append(1)
            if len(attempts)==1:raise AIError('rate_limited',limit_scope='provider',retry_after=1,provider='gemini')
        return await original(request,operation,**kwargs)
    gemini.generate=generate
    assert ingest(opportunity_flow).status_code==202
    waiting=wait(opportunity_flow,'waiting_quota')
    assert waiting['research_id'] is None
    _,result,_=research(opportunity_flow)
    current=wait(opportunity_flow,'ready')
    assert current['phase']=='ready' and result['status']=='completed'
    assert len(attempts)==2 and len(search.calls)==5
    assert current['error_code'] is None


def test_summary_transient_failure_retries_once_without_researching_again(opportunity_flow):
    from app.ai.adapter import AIError
    original=opportunity_flow[3].generate;attempts=[]
    async def generate(request,operation,**kwargs):
        if request.stage=='opportunity_summary':
            attempts.append(1)
            if len(attempts)==1:raise AIError('unavailable',True)
        return await original(request,operation,**kwargs)
    opportunity_flow[3].generate=generate
    assert ingest(opportunity_flow).status_code==202
    _,result,_=research(opportunity_flow)
    current=wait(opportunity_flow,'ready')
    assert current['phase']=='ready' and result['status']=='completed'
    assert len(attempts)==2 and len(opportunity_flow[4].calls)==5


def test_a_failed_category_does_not_publish_the_combined_response(opportunity_flow):
    opportunity_flow[4].fail='internship_insights'
    assert ingest(opportunity_flow).status_code==202
    _,result,_=research(opportunity_flow)
    current=wait(opportunity_flow,'research_failed')
    assert current['phase']=='research_failed' and result['status']=='partial'
    assert result['categories']['interview_intelligence']['findings']
    assert result['categories']['company_intelligence']['findings']


def test_summary_configuration_failure_keeps_goal_and_findings_but_does_not_publish(opportunity_flow):
    from app.ai.adapter import AIError
    original=opportunity_flow[3].generate;attempts=[]
    async def generate(request,operation,**kwargs):
        if request.stage=='opportunity_summary':
            attempts.append(1)
            raise AIError('provider_configuration')
        return await original(request,operation,**kwargs)
    opportunity_flow[3].generate=generate
    assert ingest(opportunity_flow).status_code==202
    _,result,_=research(opportunity_flow)
    current=wait(opportunity_flow,'research_failed')
    assert current['current']['goal'] and current['research_id'] is None
    assert result['finished'] and result['error_code']=='provider_configuration'
    assert all(v['findings'] for v in result['categories'].values())
    assert len(attempts)==1 and len(opportunity_flow[4].calls)==5


def test_retry_recovers_failed_cached_category_instead_of_reusing_failure(opportunity_flow):
    client,db,primary,gemini,search=opportunity_flow
    search.fail='internship_insights'
    assert ingest(opportunity_flow).status_code==202
    research(opportunity_flow);wait(opportunity_flow,'research_failed')
    search.fail=None
    assert client.post(BASE+'/retry',headers=headers()).status_code==202
    current=wait(opportunity_flow,'ready')
    assert saved_research(opportunity_flow,current)['intelligence']['status']=='completed'
    assert len(search.calls)==6, 'Retry must reuse successful cached categories.'


def test_old_cached_missing_summary_is_regenerated_without_paid_retrieval(opportunity_flow):
    from app.schemas.opportunity import Summary
    client,db,primary,gemini,search=opportunity_flow
    assert ingest(opportunity_flow).status_code==202
    current=wait(opportunity_flow,'ready')
    engine=client.app.state.opportunities
    record=engine.store.research.records.get_research(current['research_id'])
    cached=record.model_copy(update={'intelligence':record.intelligence.model_copy(update={
        'warnings':['Overall summary unavailable; validated category findings remain available.'],
        'summary':Summary()})})
    engine.store.cached=lambda context:cached
    before=len(search.calls);summaries=sum(c.stage=='opportunity_summary' for c in gemini.calls)
    assert client.post(BASE+'/retry',headers=headers()).status_code==202
    current=wait(opportunity_flow,'ready')
    assert saved_research(opportunity_flow,current)['intelligence']['summary']['overview_refs']
    assert len(search.calls)==before
    assert sum(c.stage=='opportunity_summary' for c in gemini.calls)==summaries+1
