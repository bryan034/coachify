"""Three-category durable research, strict citations and isolated provider fixtures."""
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
from app.ai.adapter import AIAdapter,AIError,Operation
from app.ai.config import AISettings,GeminiSettings
from app.ai.contracts import AIInput
from app.ai.routing import ModelRouter,opportunity_models
from app.ai.opportunity_contracts import QueryPlan,Evaluation
from app.schemas.opportunity import CATEGORIES,Summary,OpportunityReport,CategoryResult
from app.schemas.analysis import ResearchSource,ResearchContext
from app.repositories.goals import GoalError,now
from app.workflows.opportunity.domain import validate_claims,public_opportunity
from tests.test_workspace import AI,OWNER,OTHER,headers,BASE,ingest

class Primary(AI):
    def __init__(self):super().__init__();self.company='Example';self.quota=False;self.invalid=False;self.wait=False
    async def generate(self,request,operation,**kwargs):
        if request.stage=='opportunity_evaluate':
            self.calls.append(request);data=json.loads(request.context)
            while self.wait:await asyncio.sleep(.02)
            if self.quota:self.quota=False;raise AIError('rate_limited',limit_scope='provider',retry_after=1)
            text=data['sources'][0]['excerpt']
            output=Evaluation(findings=[{'field':data['allowed_fields'][0],'value':'invented' if self.invalid else text,'refs':[0],'quotes':[text],'confidence':'medium','evidence_type':'candidate_reported','scope':'exact','conflict_group':None}])
            if kwargs.get('validate_output'):kwargs['validate_output'](output)
            return SimpleNamespace(data=output)
        result=await super().generate(request,operation,**kwargs)
        if request.stage=='jd_extraction':result.data.company=self.company;result.data.role='Data Analyst Intern';result.data.employment_type='internship'
        return result

class Gemini:
    def __init__(self):self.calls=[]
    async def generate(self,request,operation,**kwargs):
        self.calls.append(request);data=json.loads(request.context)
        if request.stage=='opportunity_plan':output=QueryPlan(**{k:[f'Example Analyst Singapore {k}'] for k in CATEGORIES})
        elif request.stage=='opportunity_summary':output=Summary(overview_refs=[data['validated_findings'][0]['id']])
        else:raise AssertionError(request.stage)
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return SimpleNamespace(data=output)

class Search:
    brave_mode='llm_context'
    def __init__(self):self.calls=[];self.fail=None;self.empty=False;self.active=0;self.maximum=0
    async def collect_opportunity_query(self,context,query):
        self.calls.append(query);self.active+=1;self.maximum=max(self.maximum,self.active)
        try:
            await asyncio.sleep(.03)
            if self.fail and self.fail in query:raise GoalError('Brave access unavailable.',503)
            if self.empty:return []
            text='Example candidates report a technical interview.' if 'interview_' in query else 'Example interns report SGD 1500 per month.' if 'internship_' in query else 'Example builds analytics software.'
            return [ResearchSource(source_id=query.split()[-1],platform='other',url='https://example.test/'+query.split()[-1],title='Example public report',evidence=text,reliability='anecdotal')]
        finally:self.active-=1

@pytest.fixture
def opportunity_flow():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000);db=mongo['coachify_opportunity_test_'+uuid4().hex];primary=Primary();gemini=Gemini();search=Search()
    def profile(req):return httpx.Response(200,json={'id':OTHER if req.headers.get('Authorization')=='Bearer other' else OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    try:
        with TestClient(create_app(database=db,ai=ModelRouter(primary,gemini),research_client=search,profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as client:
            yield client,db,primary,gemini,search
    finally:mongo.drop_database(db.name);mongo.close()

def research(flow,finished=True):
    client=flow[0]
    for _ in range(200):
        w=client.get(BASE,headers=headers()).json();goal=w.get('current',{}).get('goal')
        if goal:
            path=f"/api/v1/career/goals/{goal['_id']}/opportunity-research";response=client.get(path,headers=headers())
            value=response.json()
            if value.get('job_id') and (not finished or value.get('finished')):return w,value,path
        time.sleep(.04)
    pytest.fail('Research did not finish: '+str(value))

def test_parallel_categories_persist_cited_summary_and_legacy_chat_compatibility(opportunity_flow):
    flow=opportunity_flow;assert ingest(flow).status_code==202
    workspace,result,path=research(flow)
    assert result['status']=='completed',result
    assert result['available'] and result['availability_issues']==[]
    assert set(result['categories'])==set(CATEGORIES)
    assert all(v['findings'] for v in result['categories'].values())
    assert flow[4].maximum>=2 and len(flow[4].calls)==3
    assert workspace['phase']=='ready' and workspace['research']['process']['stages']
    assert result['research']['employment_type']=='internship'
    assert workspace['current']['goal']['employment_type']=='internship'
    assert result['research']['summary']['overview_refs']
    assert flow[1].interview_research.count_documents({'intelligence':{'$ne':None}})==1
    assert flow[0].get(path,headers=headers(other=True)).status_code==404
    body={'expected_version':workspace['current']['goal']['version'],'expected_selection_version':workspace['current']['selection_version'],'refresh':True,'category':'company_intelligence'}
    key=str(uuid4());assert flow[0].post(path,headers=headers(key),json=body).status_code==202
    _,refreshed,_=research(flow)
    assert len(flow[4].calls)==4
    assert refreshed['categories']['internship_insights']['findings']==result['categories']['internship_insights']['findings']
    assert flow[0].post(path,headers=headers(key),json=body).status_code==202
    assert len(flow[4].calls)==4
    assert flow[0].post(path,headers=headers(key),json={**body,'category':'internship_insights'}).status_code==409


def test_category_failure_preserves_other_results_and_reports_partial(opportunity_flow):
    flow=opportunity_flow;flow[4].fail='internship_insights';ingest(flow)
    _,result,_=research(flow)
    assert result['status']=='partial'
    assert result['categories']['internship_insights']['status']=='failed'
    assert result['categories']['company_intelligence']['findings']
    assert result['categories']['interview_intelligence']['findings']


def test_general_target_does_not_research_or_invent_employer_categories(opportunity_flow):
    flow=opportunity_flow;flow[2].company=None;ingest(flow)
    _,result,_=research(flow)
    assert len(flow[4].calls)==1 and result['research']['opportunity_id'] is None
    assert result['categories']['company_intelligence']['status']=='not_applicable'
    assert result['categories']['internship_insights']['status']=='not_applicable'


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
    assert len([v for v in flow[2].calls if v.stage=='opportunity_evaluate'])==6


def test_quota_resume_does_not_repeat_paid_retrieval(opportunity_flow):
    flow=opportunity_flow;flow[2].quota=True;ingest(flow)
    _,result,_=research(flow)
    assert result['status']=='completed' and len(flow[4].calls)==3


def test_provider_payloads_route_small_reasoning_schema_with_groq_guard():
    context={'category':'internship_insights','sources':[{'ref':0,'excerpt':'Example interns report SGD 1500 per month.'}],'allowed_fields':['compensation']}
    async def run():
        async with httpx.AsyncClient() as client:
            groq=AIAdapter(AISettings(enabled=True,model='openai/gpt-oss-120b',api_key='fixture'),client)
            payload=groq._payload(AIInput(stage='opportunity_evaluate',context=json.dumps(context)))
            from app.ai.usage import input_tokens
            assert input_tokens(payload)<4000 and payload['reasoning_effort']=='low'
            gemini=AIAdapter(GeminiSettings(enabled=True,model='gemini-3.5-flash',api_key='fixture'),client)
            assert gemini._payload(AIInput(stage='opportunity_plan',context='{}'))['model']=='gemini-3.5-flash'
    asyncio.run(run())


def test_forged_quotes_refs_and_unbacked_value_are_rejected():
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/report',evidence='Interns receive SGD 1500 per month.')
    base={'field':'compensation','value':'SGD 1500','refs':[0],'quotes':[source.evidence],'confidence':'low','evidence_type':'candidate_reported','scope':'exact'}
    assert validate_claims(Evaluation(findings=[base]),'internship_insights',[source])
    for change in ({'refs':[1]},{'value':'SGD 9000'},{'quotes':['SGD 9000']}):
        with pytest.raises(AIError):validate_claims(Evaluation(findings=[{**base,**change}]),'internship_insights',[source])


def test_expired_category_refresh_does_not_repeat_fresh_categories(opportunity_flow):
    from bson import ObjectId
    flow=opportunity_flow;ingest(flow);workspace,first,_=research(flow)
    identifier=workspace['research']['_id']
    flow[1].interview_research.update_one({'_id':ObjectId(identifier)},{'$set':{'intelligence.categories.company_intelligence.expires_at':now()-timedelta(seconds=1)}})
    ingest(flow,'SQL is required. Equivalent new source.');_,second,_=research(flow)
    assert len(flow[4].calls)==4
    assert second['categories']['internship_insights']['findings']==first['categories']['internship_insights']['findings']


def test_durable_restart_reuses_completed_searches(opportunity_flow):
    from app.workflows.opportunity.engine import OpportunityEngine
    flow=opportunity_flow;client=flow[0];flow[2].wait=True;ingest(flow)
    for _ in range(100):
        job=flow[1].research_contexts.find_one({'kind':'opportunity_job'}) or {}
        if len(job.get('history',{}))==3:break
        time.sleep(.02)
    assert len(job.get('history',{}))==3
    previous=client.app.state.opportunities
    client.portal.call(previous.close)
    flow[2].wait=False
    async def restart():
        value=OpportunityEngine(client.app,flow[1],previous.settings,previous.ai)
        client.app.state.opportunities=value
        value.launch(job['_id'])
    client.portal.call(restart)
    _,result,_=research(flow)
    assert result['status']=='completed' and len(flow[4].calls)==3


def test_employee_pay_is_qualified_for_an_internship_and_conflicts_stay_separate():
    evidence='Example full-time employees report SGD 5000 monthly; another report says SGD 6000 monthly.'
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/report',evidence=evidence)
    output=Evaluation(findings=[{'field':'compensation','value':value,'refs':[0],'quotes':[evidence],'confidence':'high','evidence_type':'candidate_reported','scope':'exact','conflict_group':'salary'} for value in ('SGD 5000','SGD 6000')])
    result=validate_claims(output,'internship_insights',[source],{'company':'Example','employment_type':'internship'})
    assert len(result)==2 and all(f.scope=='related_employment' and f.confidence=='low' for f in result)
    assert [f.value for f in result]==['SGD 5000','SGD 6000']


@pytest.mark.skipif(os.getenv('OPPORTUNITY_LIVE_TEST')!='1',reason='Opt-in only: consumes configured live provider requests')
def test_optional_live_provider_contract_smoke():
    from app.ai.opportunity_config import OpportunitySettings
    from app.clients.search_sources import SourceAPIs
    async def run():
        settings=OpportunitySettings.from_env();primary=AISettings.from_env();gemini=GeminiSettings.from_env()
        assert settings.enabled and primary.enabled and gemini.api_key.get_secret_value().strip(),'Configure the research providers before opting into live checks.'
        async with httpx.AsyncClient(trust_env=False) as client:
            router=opportunity_models(AIAdapter(primary,client),None,gemini,settings,client)
            public={'company':None,'role':'Software engineering intern','field':'Software','location':'Singapore','employment_type':'internship','recruitment_year':now().year}
            plan=await router.generate(AIInput(stage='opportunity_plan',context=json.dumps(public)),Operation('live-public-smoke','public','opportunity_plan'),current_revision=lambda:'public')
            source=SourceAPIs.from_environment(client).for_opportunity()
            assert source.brave_mode=='llm_context'
            results=await source.collect_opportunity_query(ResearchContext(role=public['role'],field='Software',location='Singapore'),plan.data.interview_intelligence[0] if plan.data.interview_intelligence else 'software engineering internship Singapore interview process')
            assert isinstance(results,list)
            if results:
                context={'opportunity':public,'category':'interview_intelligence','allowed_fields':['recruitment_stages','preparation_topics'],
                    'sources':[{'ref':0,'title':results[0].title,'excerpt':results[0].evidence}]}
                def validate(output):validate_claims(output,'interview_intelligence',results[:1],public)
                await router.generate(AIInput(stage='opportunity_evaluate',context=json.dumps(context)),Operation('live-public-smoke','public','opportunity_evaluate'),current_revision=lambda:'public',validate_output=validate)
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
    claims=Evaluation(findings=[{'field':'compensation','value':'SGD 1500','refs':[i],'quotes':[text],'confidence':'low','evidence_type':'candidate_reported','scope':'exact'} for i in (0,1)])
    result=dedupe_findings('internship_insights',validate_claims(claims,'internship_insights',[a,b]))
    assert len(result)==1 and set(result[0].source_ids)=={'a','b'} and result[0].value=='SGD 1500'


@pytest.mark.parametrize('quota_followup',[False,True])
def test_follow_up_evidence_reaches_reasoner_without_discarding_previous_findings(opportunity_flow,quota_followup):
    flow=opportunity_flow;search=flow[4];original_search=search.collect_opportunity_query;primary=flow[2];original_generate=primary.generate
    paused=set()
    async def collect(context,query):
        values=await original_search(context,query)
        if 'followup' in query:
            return [values[0].model_copy(update={'url':values[0].url+'/followup','evidence':values[0].evidence+' A followup report adds detail.'})]
        return values
    async def generate(request,operation,**kwargs):
        if request.stage!='opportunity_evaluate':return await original_generate(request,operation,**kwargs)
        primary.calls.append(request);data=json.loads(request.context);text=data['sources'][0]['excerpt']
        if quota_followup and 'followup' in text and data['category'] not in paused:
            paused.add(data['category'])
            raise AIError('rate_limited',limit_scope='user',retry_after=1)
        output=Evaluation(findings=[{'field':data['allowed_fields'][0],'value':text,'refs':[0],'quotes':[text],'confidence':'low','evidence_type':'candidate_reported','scope':'exact'}],follow_up_query=None if 'followup' in text else 'Example '+data['category']+' followup')
        kwargs['validate_output'](output)
        return SimpleNamespace(data=output)
    search.collect_opportunity_query=collect;primary.generate=generate
    ingest(flow);_,result,_=research(flow)
    assert len(search.calls)==6
    evaluations=[json.loads(call.context) for call in primary.calls if call.stage=='opportunity_evaluate']
    assert len(evaluations)==(9 if quota_followup else 6)
    assert len([data for data in evaluations if 'followup' not in data['sources'][0]['excerpt']])==3
    for category in result['categories'].values():
        assert len(category['findings'])==2
        assert any('followup' in f['value'] for f in category['findings'])
        assert any('followup' not in f['value'] for f in category['findings'])


def test_workspace_reports_quota_wait_instead_of_research_unavailable(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];original=primary.generate;paused=False
    async def generate(request,operation,**kwargs):
        nonlocal paused
        if request.stage=='opportunity_evaluate' and json.loads(request.context)['category']=='interview_intelligence' and not paused:
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
        if request.stage=='opportunity_evaluate':
            category=json.loads(request.context)['category'];attempts[category]=attempts.get(category,0)+1
            if attempts[category]==2:raise AIError('rate_limited',limit_scope='user',retry_after=1)
        return await original(request,operation,**kwargs)
    primary.generate=generate;ingest(flow)
    _,result,_=research(flow)
    assert result['finished'] and result['status']=='failed'
    assert set(attempts.values())=={3}  # Invalid, quota pause, final bounded correction.
    assert all(v['error_code']=='invalid_output' for v in result['categories'].values())
