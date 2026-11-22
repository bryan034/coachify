from tests.api_views import saved_research
"""Five-category durable research, strict citations and isolated provider fixtures."""
import asyncio
import json
import os
import time
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.main import create_app
from app.ai.adapter import AIAdapter, Operation
from app.ai.errors import AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.routing import ModelRouter,opportunity_models
from app.ai.opportunity_contracts import QueryPlan,StructuredFindings,Triage,structure_input
from app.schemas.opportunity import CATEGORIES,Summary,OpportunityReport,CategoryResult
from app.schemas.analysis import ResearchSource,ResearchContext
from app.repositories.goals import GoalError,now
from app.workflows.opportunity.domain import validate_claims,public_opportunity
from app.workflows.opportunity.topics import ALTERNATE,CANDIDATES_PER_SEARCH,GROUP_CANDIDATES,GROUP_TERMS,GROUPS,TERMS,TOPIC_GROUP,TOPICS,category_topics,owner,policy
from app.ai.opportunity_config import OpportunitySettings

RUN_SEARCHES=OpportunitySettings().run_searches
from tests.test_workspace import AI,OWNER,OTHER,headers,BASE,ingest

class Primary(AI):
    def __init__(self):super().__init__();self.company='Example';self.quota=False;self.invalid=False;self.wait=False;self.triaged=[]
    async def generate(self,request,operation,**kwargs):
        if request.stage=='opportunity_triage':
            data=json.loads(request.context);self.triaged.append(data)
            # Metadata names the topic a page was found for; pages without one look relevant to every topic.
            output=Triage(pages=[{'ref':page['ref'],'topics':[t for t in data['topics'] if t in page['url']] or list(data['topics'])} for page in data['pages']])
            if kwargs.get('validate_output'):kwargs['validate_output'](output)
            return SimpleNamespace(data=output)
        if request.stage=='opportunity_structure':
            self.calls.append(request);data=json.loads(request.context)
            while self.wait:await asyncio.sleep(.02)
            if self.quota:self.quota=False;raise AIError('rate_limited',limit_scope='provider',retry_after=1)
            text=data['evidence'][0]['text']
            output=StructuredFindings(findings=[{'field':data['allowed_fields'][0],'value':'invented' if self.invalid else text,'refs':[0],'quotes':['fabricated excerpt' if self.invalid else text],'confidence':'medium','evidence_type':'candidate_reported','scope':'exact','conflict_group':None}])
            if kwargs.get('validate_output'):kwargs['validate_output'](output)
            return SimpleNamespace(data=output)
        result=await super().generate(request,operation,**kwargs)
        if request.stage=='jd_extraction':result.data.company=self.company;result.data.role='Data Analyst Intern';result.data.employment_type='internship'
        return result

class ContextModel:
    def __init__(self):self.calls=[]
    async def generate(self,request,operation,**kwargs):
        self.calls.append(request);data=json.loads(request.context)
        if request.stage=='opportunity_plan':
            public=data.get('opportunity',data);base=' '.join(str(public.get(k) or '') for k in ('company','role','location'))
            output=QueryPlan(**{g:f'{base} {g} group' for g in GROUPS})
        else:raise AssertionError(request.stage)
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return SimpleNamespace(data=output)

def query_topic(query):
    matches=[t for t in TOPICS if query.endswith(' '+t) or query.endswith(' '+TERMS[t]) or (t in ALTERNATE and query.endswith(' '+ALTERNATE[t]))]
    return max(matches,key=lambda t:len(t),default=None)

def query_group(query):
    return next((g for g in GROUPS if query.endswith(f' {g} group') or query.endswith(' '+GROUP_TERMS[g])),None)

def refresh_searches(category):
    own=category_topics(category)
    return len({TOPIC_GROUP[t] for t in own})+2*len(own)

class Search:
    brave_mode='llm_context';provider='brave';backend='brave'
    def __init__(self):self.calls=[];self.fail=None;self.empty=False;self.active=0;self.maximum=0
    async def collect_opportunity_query(self,context,query,max_sources=5):
        self.calls.append(query);self.active+=1;self.maximum=max(self.maximum,self.active)
        group=query_group(query);topic=None if group else query_topic(query)
        category=owner(topic) if topic else owner(GROUPS[group][0]) if group else next((c for c in CATEGORIES if c in query),'company_intelligence')
        tagged=f'{query} {category}'
        try:
            await asyncio.sleep(.03)
            if self.fail and self.fail in tagged:raise GoalError('Brave access unavailable.',503)
            if self.empty:return []
            text='Example candidates report a technical interview.' if 'interview_' in tagged else 'Example interns report SGD 1500 per month.' if 'internship_' in tagged else 'Example interns converted to full-time in 2025 at a conversion rate of 50%.' if 'conversion_outcomes' in tagged else 'Example graduate analysts receive SGD 5000 monthly.' if 'career_progression' in tagged else 'Example teams report a collaborative company culture.'
            slug='-'.join(query.split()[-2:])
            # The page URL names the topics it covers, which the synthetic triage reads.
            covers='+'.join(GROUPS[group]) if group else topic or 'general'
            return [ResearchSource(source_id=slug,platform='other',url=f'https://example.test/{covers}/{slug}',title='Example public report',evidence=text,reliability='anecdotal')]
        finally:self.active-=1

@pytest.fixture
def opportunity_flow():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000);db=mongo['elo_opportunity_test_'+uuid4().hex];primary=Primary();context_model=ContextModel();search=Search()
    def profile(req):return httpx.Response(200,json={'id':OTHER if req.headers.get('Authorization')=='Bearer other' else OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    try:
        with TestClient(create_app(database=db,ai=ModelRouter(primary,context_model),research_client=search,profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as client:
            yield client,db,primary,context_model,search
    finally:mongo.drop_database(db.name);mongo.close()

def research(flow,finished=True):
    client=flow[0]
    for _ in range(200):
        w=client.get(BASE,headers=headers()).json();goal=w.get('current',{}).get('goal')
        if goal:
            path=f"/api/v1/career/goals/{goal['_id']}/opportunity-research";response=client.get(path,headers=headers())
            value=response.json()
            if value.get('job_id') and (not finished or value.get('finished')):
                w=client.get(BASE,headers=headers()).json()
                if finished and w['phase'] in ('research_pending','researching'):time.sleep(.01);continue
                return w,value,path
        time.sleep(.04)
    pytest.fail('Research did not finish: '+str(value))

def test_parallel_categories_persist_cited_summary_and_legacy_chat_compatibility(opportunity_flow):
    flow=opportunity_flow;assert ingest(flow).status_code==202
    workspace,result,path=research(flow)
    assert result['status']=='completed',result
    assert result['available'] and result['availability_issues']==[]
    assert set(result['categories'])==set(CATEGORIES)
    assert all(v['findings'] for v in result['categories'].values())
    calls=flow[4].calls
    assert flow[4].maximum>=2 and len(calls)==RUN_SEARCHES==len(set(calls))
    assert {query_group(q) for q in calls[:len(GROUPS)]}==set(GROUPS)
    assert all(query_topic(q) for q in calls[len(GROUPS):])
    assert workspace['phase']=='ready' and workspace['research_id']
    assert 'process' not in saved_research(flow,workspace) and 'skills' not in saved_research(flow,workspace)
    assert workspace['current']['goal']['employment_type']=='internship'
    assert result['summary']['overview_refs']
    assert flow[1].interview_research.count_documents({'intelligence':{'$ne':None}})==1
    assert flow[0].get(path,headers=headers(other=True)).status_code==404
    body={'expected_version':workspace['current']['goal']['version'],'expected_selection_version':workspace['current']['selection_version'],'refresh':True,'category':'company_intelligence'}
    key=str(uuid4());assert flow[0].post(path,headers=headers(key),json=body).status_code==202
    _,refreshed,_=research(flow)
    # Only the refreshed category's group searches again, then each of its own topics twice.
    own=category_topics('company_intelligence');refresh=flow[4].calls[RUN_SEARCHES:]
    assert query_group(refresh[0])=='culture' and len(refresh)==refresh_searches('company_intelligence')
    assert {query_topic(q) for q in refresh[1:]}==set(own)
    assert refreshed['categories']['internship_insights']['findings']==result['categories']['internship_insights']['findings']
    assert flow[0].post(path,headers=headers(key),json=body).status_code==202
    assert len(flow[4].calls)==RUN_SEARCHES+refresh_searches('company_intelligence')
    assert flow[0].post(path,headers=headers(key),json={**body,'category':'internship_insights'}).status_code==409


def test_category_failure_preserves_other_results_and_reports_partial(opportunity_flow):
    flow=opportunity_flow;flow[4].fail='internship_insights';ingest(flow)
    _,result,_=research(flow)
    assert result['status']=='partial'
    assert result['categories']['internship_insights']['status']=='failed'
    assert result['categories']['company_intelligence']['findings']
    assert result['categories']['interview_intelligence']['findings']


def test_general_target_researches_all_five_with_explicit_general_context(opportunity_flow):
    flow=opportunity_flow;flow[2].company=None;ingest(flow)
    workspace,result,_=research(flow)
    assert len(flow[4].calls)==RUN_SEARCHES and saved_research(flow,workspace)['intelligence']['opportunity_id'] is None
    assert all(category['status']=='completed' for category in result['categories'].values())
    assert all(finding['scope']=='general' and finding['confidence']=='low' for category in result['categories'].values() for finding in category['findings'])


def test_empty_evidence_is_completed_with_missing_fields_not_provider_failure(opportunity_flow):
    flow=opportunity_flow;flow[4].empty=True;ingest(flow)
    _,result,_=research(flow)
    assert result['status']=='completed'
    assert all(not v['findings'] and v['missing_fields'] for v in result['categories'].values())


def test_cache_reuses_same_material_context_across_replacement_goals(opportunity_flow):
    flow=opportunity_flow;ingest(flow);research(flow);before=len(flow[4].calls)
    ingest(flow,'SQL is required. Another source document.');_,result,_=research(flow)
    assert result['status']=='completed' and len(flow[4].calls)==before


def test_invalid_claim_repairs_are_bounded_and_no_unvalidated_facts_persist(opportunity_flow):
    flow=opportunity_flow;flow[2].invalid=True;ingest(flow)
    _,result,_=research(flow)
    assert result['status']=='failed'
    assert all(not c['findings'] for c in result['categories'].values())
    # Each round with evidence makes one call and one repair.
    rounds=[json.loads(v.context)['category'] for v in flow[2].calls if v.stage=='opportunity_structure']
    assert set(rounds)==set(CATEGORIES)
    assert all(rounds.count(c)%2==0 and rounds.count(c)<=2*(OpportunitySettings().topic_searches+1) for c in CATEGORIES)


def test_quota_resume_does_not_repeat_paid_retrieval(opportunity_flow):
    flow=opportunity_flow;flow[2].quota=True;ingest(flow)
    _,result,_=research(flow)
    assert result['status']=='completed' and len(flow[4].calls)==RUN_SEARCHES==len(set(flow[4].calls))


def test_reasoning_and_planning_use_strict_json_schema():
    context=structure_input({},'internship_insights',[ResearchSource(source_id='synthetic',platform='other',url='https://example.test/intern',evidence='Example interns report SGD 1500 per month.')])
    adapter=AIAdapter(AISettings(enabled=True,api_key='fixture',max_output_tokens=4096),None)
    for stage in ('opportunity_structure','opportunity_plan'):
        payload=adapter._payload(AIInput(stage=stage,context=json.dumps(context)))
        assert payload['model']=='openai/gpt-4o-mini' and payload['response_format']['type']=='json_schema'
        assert 'max_tokens' in payload and 'max_completion_tokens' not in payload
        assert payload['response_format']['json_schema']['name']==stage


def test_forged_quotes_refs_and_unbacked_value_are_rejected():
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/report',evidence='Interns receive SGD 1500 per month.')
    base={'field':'compensation','value':'SGD 1500 per month','refs':[0],'quotes':[source.evidence],'confidence':'low','evidence_type':'candidate_reported','scope':'exact'}
    assert validate_claims(StructuredFindings(findings=[base]),'internship_insights',[source])
    for change in ({'refs':[1]},{'value':'SGD 9000'},{'quotes':['SGD 9000']}):
        with pytest.raises(AIError):validate_claims(StructuredFindings(findings=[{**base,**change}]),'internship_insights',[source])


def test_expired_category_refresh_does_not_repeat_fresh_categories(opportunity_flow):
    from bson import ObjectId
    flow=opportunity_flow;ingest(flow);workspace,first,_=research(flow)
    identifier=workspace['research_id']
    flow[1].interview_research.update_one({'_id':ObjectId(identifier)},{'$set':{'intelligence.categories.company_intelligence.expires_at':now()-timedelta(seconds=1)}})
    ingest(flow,'SQL is required. Equivalent new source.');_,second,_=research(flow)
    assert len(flow[4].calls)==RUN_SEARCHES+refresh_searches('company_intelligence')
    assert second['categories']['internship_insights']['findings']==first['categories']['internship_insights']['findings']


def test_durable_restart_reuses_completed_searches(opportunity_flow):
    from app.workflows.opportunity.engine import OpportunityEngine
    flow=opportunity_flow;client=flow[0];flow[2].wait=True;search=flow[4];collect=search.collect_opportunity_query;gate=asyncio.Event()
    async def held(context,query,**kwargs):
        if not query_group(query):await gate.wait()
        return await collect(context,query,**kwargs)
    search.collect_opportunity_query=held;ingest(flow)
    for _ in range(100):
        job=flow[1].research_contexts.find_one({'kind':'opportunity_job'}) or {}
        if len(job.get('group_history',{}))==len(GROUPS) and job.get('run_triaged'):break
        time.sleep(.02)
    assert len(job.get('group_history',{}))==len(GROUPS)
    previous=client.app.state.opportunities
    client.portal.call(previous.close)
    flow[2].wait=False
    async def restart():
        gate.set()
        value=OpportunityEngine(client.app,flow[1],previous.settings,previous.ai)
        client.app.state.opportunities=value
        value.launch(job['_id'])
    client.portal.call(restart)
    _,result,_=research(flow)
    # Gap searches cancelled by the shutdown keep their reservations, so the run may finish under its allowance.
    calls=flow[4].calls
    assert result['status']=='completed' and len(calls)==len(set(calls))<=RUN_SEARCHES
    assert sorted(query_group(q) for q in calls if query_group(q))==sorted(GROUPS)


def test_employee_pay_is_qualified_for_an_internship_and_conflicts_stay_separate():
    evidence='Example full-time employees report SGD 5000 monthly; another report says SGD 6000 monthly.'
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/report',evidence=evidence)
    output=StructuredFindings(findings=[{'field':'compensation','value':value,'refs':[0],'quotes':[evidence],'confidence':'high','evidence_type':'candidate_reported','scope':'exact','conflict_group':'salary'} for value in ('SGD 5000 monthly','SGD 6000 monthly')])
    result=validate_claims(output,'internship_insights',[source],{'company':'Example','employment_type':'internship'})
    assert len(result)==2 and all(f.scope=='related_employment' and f.confidence=='low' for f in result)
    assert [f.value for f in result]==['SGD 5000 monthly','SGD 6000 monthly']


@pytest.mark.skipif(os.getenv('OPPORTUNITY_LIVE_TEST')!='1',reason='Opt-in only: consumes configured live provider requests')
def test_optional_live_provider_contract_smoke():
    from app.ai.opportunity_config import OpportunitySettings
    from app.clients.search_sources import SourceAPIs
    async def run():
        settings=OpportunitySettings.from_env();primary=AISettings.from_env();context_model=primary
        assert settings.enabled and primary.enabled and primary.api_key.get_secret_value().strip(),'Configure the research providers before opting into live checks.'
        async with httpx.AsyncClient(trust_env=False) as client:
            router=opportunity_models(AIAdapter(primary,client),None,context_model,settings,client)
            public={'company':None,'role':'Software engineering intern','field':'Software','location':'Singapore','employment_type':'internship','recruitment_year':now().year}
            plan=await router.generate(AIInput(stage='opportunity_plan',context=json.dumps(public)),Operation('live-public-smoke','public','opportunity_plan'),current_revision=lambda:'public')
            source=SourceAPIs.from_environment(client).for_opportunity()
            assert source.configured and source.provider=='brave'
            results=await source.collect_opportunity_query(ResearchContext(role=public['role'],field='Software',location='Singapore'),plan.data.interview_intelligence[0] if plan.data.interview_intelligence else 'software engineering internship Singapore interview process')
            assert isinstance(results,list)
            if results:
                context=structure_input(public,'interview_intelligence',results[:1])
                def validate(output):validate_claims(output,'interview_intelligence',results[:1],public)
                await router.generate(AIInput(stage='opportunity_structure',context=json.dumps(context)),Operation('live-public-smoke','public','opportunity_structure'),current_revision=lambda:'public',validate_output=validate)
    asyncio.run(run())


def test_public_context_omits_private_inputs_and_url_access_parameters(documents):
    from app.schemas.analysis import CareerGoal
    goal=CareerGoal.model_validate(documents['goal'])
    goal.job_url='https://example.test/jobs?access_token=synthetic-private#private'
    goal.interests=['synthetic-private'];goal.preferences=['synthetic-private']
    public,context=public_opportunity(goal)
    assert public['job_url']=='https://example.test/jobs'
    assert 'synthetic-private' not in json.dumps(public)
    assert public_opportunity(goal)[1].reuse_key()==context.reuse_key()
    goal.employment_type='internship'
    assert public_opportunity(goal)[1].reuse_key()!=context.reuse_key()


def test_duplicate_claims_merge_real_citations_without_averaging():
    from app.workflows.opportunity.domain import dedupe_findings
    text='Interns receive SGD 1500 monthly.'
    a=ResearchSource(source_id='a',platform='other',url='https://example.test/a',evidence=text)
    b=a.model_copy(update={'source_id':'b','url':'https://example.test/b'})
    claims=StructuredFindings(findings=[{'field':'compensation','value':'SGD 1500 monthly','refs':[i],'quotes':[text],'confidence':'low','evidence_type':'candidate_reported','scope':'exact'} for i in (0,1)])
    result=dedupe_findings('internship_insights',validate_claims(claims,'internship_insights',[a,b]))
    assert len(result)==1 and set(result[0].source_ids)=={'a','b'} and result[0].value=='SGD 1500 monthly'


@pytest.mark.parametrize('quota_followup',[False,True])
def test_second_search_evidence_reaches_reasoner_without_discarding_first_findings(opportunity_flow,quota_followup):
    flow=opportunity_flow;search=flow[4];original_search=search.collect_opportunity_query;primary=flow[2];original_generate=primary.generate
    paused=set()
    async def collect(context,query,**kwargs):
        values=await original_search(context,query,**kwargs)
        if not query_group(query):
            return [values[0].model_copy(update={'evidence':values[0].evidence+' A followup report adds detail.'})]
        return values
    async def generate(request,operation,**kwargs):
        if request.stage!='opportunity_structure':return await original_generate(request,operation,**kwargs)
        primary.calls.append(request);data=json.loads(request.context);text=data['evidence'][0]['text']
        if quota_followup and 'followup' in text and data['category'] not in paused:
            paused.add(data['category'])
            raise AIError('rate_limited',limit_scope='user',retry_after=1)
        output=StructuredFindings(findings=[{'field':data['allowed_fields'][0],'value':text,'refs':[0],'quotes':[text],'confidence':'low','evidence_type':'candidate_reported','scope':'exact'}])
        kwargs['validate_output'](output)
        return SimpleNamespace(data=output)
    search.collect_opportunity_query=collect;primary.generate=generate
    ingest(flow);_,result,_=research(flow)
    assert len(search.calls)==RUN_SEARCHES==len(set(search.calls))
    evaluations=[json.loads(call.context) for call in primary.calls if call.stage=='opportunity_structure']
    assert len(paused)==(len(CATEGORIES) if quota_followup else 0)
    first=[data['category'] for data in evaluations if 'followup' not in data['evidence'][0]['text']]
    assert len(first)==len(set(first))
    for key,category in result['categories'].items():
        assert any('followup' in f['value'] for f in category['findings'])
        assert key not in first or any('followup' not in f['value'] for f in category['findings'])


def test_workspace_reports_quota_wait_instead_of_research_unavailable(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];original=primary.generate;paused=False
    async def generate(request,operation,**kwargs):
        nonlocal paused
        if request.stage=='opportunity_structure' and json.loads(request.context)['category']=='interview_intelligence' and not paused:
            paused=True
            raise AIError('rate_limited',limit_scope='user',retry_after=2)
        return await original(request,operation,**kwargs)
    primary.generate=generate;ingest(flow)
    for _ in range(100):
        workspace=flow[0].get(BASE,headers=headers()).json()
        if workspace['phase']=='waiting_quota':break
        time.sleep(.02)
    assert workspace['phase']=='waiting_quota'
    assert workspace['error_code']=='rate_limited' and 'resume automatically' in workspace['error']
    assert 1<=workspace['retry_after']<=2
    _,result,_=research(flow)
    assert result['finished'] and result['status']=='completed'


def test_global_validation_failure_reports_specific_code_and_ends_workspace_spinner(opportunity_flow,caplog):
    flow=opportunity_flow;engine=flow[0].app.state.opportunities;original=engine.generate
    async def generate(job,stage,data,validate=None):
        if stage=='opportunity_plan':raise ValueError('PRIVATE_SYNTHETIC_PROVIDER_CONTENT')
        return await original(job,stage,data,validate)
    engine.generate=generate;ingest(flow)
    workspace,result,_=research(flow)
    assert result['finished'] and result['error_code']=='research_validation_failed'
    workspace=flow[0].get(BASE,headers=headers()).json()
    assert workspace['phase']=='research_failed' and workspace['error_code']=='research_validation_failed'
    assert 'PRIVATE_SYNTHETIC' not in caplog.text


def test_quota_pause_does_not_reset_the_invalid_response_repair_budget(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];primary.invalid=True;original=primary.generate;attempts={}
    async def generate(request,operation,**kwargs):
        if request.stage=='opportunity_structure':
            category=json.loads(request.context)['category'];attempts[category]=attempts.get(category,0)+1
            if attempts[category]==2:raise AIError('rate_limited',limit_scope='user',retry_after=1)
        return await original(request,operation,**kwargs)
    primary.generate=generate;ingest(flow)
    _,result,_=research(flow)
    assert result['finished'] and result['status']=='failed'
    # A pause after the first invalid response keeps the round to one call and one repair.
    assert all(count%2==1 for count in attempts.values()) and set(attempts)==set(CATEGORIES)
    assert all(v['error_code']=='invalid_output' for v in result['categories'].values())


def test_one_invalid_citation_does_not_discard_independently_supported_findings():
    from app.workflows.opportunity.domain import supported_claims
    text='Example candidates report a technical interview.'
    source=ResearchSource(source_id='s1',platform='other',url='https://example.test/report',evidence=text)
    good={'field':'recruitment_stages','value':'technical interview','refs':[0],'quotes':[text],'confidence':'medium','evidence_type':'candidate_reported','scope':'exact'}
    output=StructuredFindings(findings=[good,{**good,'quotes':['fabricated source quote']}])
    findings,rejected=supported_claims(output,'interview_intelligence',[source])
    assert rejected==1 and len(findings)==1 and findings[0].value=='technical interview'
    assert findings[0].quotes==[text]


def test_topics_read_and_keep_sources_within_their_policy(opportunity_flow):
    flow=opportunity_flow;search=flow[4];collect=search.collect_opportunity_query
    async def many(context,query,max_sources=5):
        first=(await collect(context,query))[0]
        return [first.model_copy(update={'url':first.url+f'/{i}'}) for i in range(max_sources)]
    search.collect_opportunity_query=many
    ingest(flow);_,result,_=research(flow)
    assert result['status']=='completed' and len(search.calls)==RUN_SEARCHES
    job=flow[1].research_contexts.find_one({'kind':'opportunity_job'})
    # The grouped round reads one search's allowance per topic, so unsettled topics still run gap searches.
    assert {query_topic(q) for q in search.calls[len(GROUPS):]}<=set(job['history'])
    assert all(len(job['evidence'][t])<=GROUP_CANDIDATES+CANDIDATES_PER_SEARCH*2 for t in TOPICS if t in job['evidence'])
    assert all(policy(t).urls_per_search<=len(ids)<=policy(t).max_urls for t,ids in job['read'].items())
    assert set(job['read'])=={t for c in CATEGORIES for t in category_topics(c)}
    for key,category in result['categories'].items():
        cited={f['field']:set() for f in category['findings']}
        for f in category['findings']:cited[f['field']].update(f['source_ids'])
        assert all(len(ids)<=policy(field).keep for field,ids in cited.items())
        assert category['searches']<=len({TOPIC_GROUP[t] for t in category_topics(key)})+2*len(category_topics(key))
