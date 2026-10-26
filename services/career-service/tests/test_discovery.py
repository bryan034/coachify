"""Synthetic end-to-end discovery: real Mongo/graphs, no CV/provider/network calls."""
import asyncio
import json
import os
import time
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.main import create_app
from app.ai.adapter import AIError
from app.schemas.discovery import Scope,Decision,Plan,Listings,MarketSummary,Listing,Requirement
from app.schemas.analysis import Generation,ResearchSource,CareerGoal
from app.repositories.goals import now,GoalStore
from app.workflows.discovery import aggregate,validated_listings

OWNER='11111111-1111-4111-8111-111111111111'
BASE='/api/v1/career/discoveries'
def headers(other=False,key=None):return {'Authorization':'Bearer '+('other' if other else 'owner'),'Idempotency-Key':key or str(uuid4())}
SCOPE=Scope(field='Software Engineering',area='Software Engineering',career_stage='entry_level',location='Singapore')

class AI:
    settings=SimpleNamespace(enabled=True,model='synthetic')
    def __init__(self):self.calls=[];self.quota_at=None;self.empty=False;self.fail=False
    async def generate(self,request,operation,**kwargs):
        self.calls.append(request.stage);data=json.loads(request.context)
        if self.fail:raise AIError('invalid_output')
        if request.stage=='discovery_turn':
            message=request.conversation[-1].content
            scope=SCOPE.model_copy(update={'area':'Backend Engineering','specificity':'specialisation'}) if 'Backend' in message else SCOPE
            result=Decision(action='START_RESEARCH',scope=scope,question=None,reply='Confirm this career area to research real job listings.',recommendations=[])
        elif request.stage=='discovery_plan':result=Plan(related_roles=['Software Engineer','Backend Engineer'],queries=['graduate software jobs','graduate backend jobs'])
        elif request.stage=='discovery_extract':
            count=self.calls.count('discovery_extract')
            if count==self.quota_at:raise AIError('rate_limited',limit_scope='user',retry_after=1,provider='groq')
            result=Listings(listings=[] if self.empty else [Listing(ref=i,company=s['title'].split(' · ')[0],job_title='Software Engineer',location='Singapore',career_stage='entry_level',relevant=True,requirements=[Requirement(kind='skill',name='SQL',quote='SQL is required.'),Requirement(kind='skill',name='Python',quote='Python preferred.',preferred=True),Requirement(kind='responsibility',name='Build APIs',quote='Build APIs.')]) for i,s in enumerate(data['sources'])])
        elif request.stage=='discovery_summary':result=MarketSummary(responsibility_refs=[0] if data['responsibilities'] else [])
        else:raise AssertionError(request.stage)
        if kwargs.get('validate_output'):kwargs['validate_output'](result)
        return SimpleNamespace(data=result,generation=Generation(provider='synthetic',model='synthetic',prompt_version='test',generated_at=now()))

class Sources:
    configured=True;brave_mode='llm_context'
    def __init__(self):self.calls=[];self.empty=False;self.fail=False
    async def collect_opportunity_query(self,context,query):
        self.calls.append(query)
        if self.fail:raise TimeoutError()
        if self.empty:return []
        start=0 if len(self.calls)%2 else 5
        return [ResearchSource(source_id=f'job-{i}',platform='employer',url=f'https://example.test/jobs/{i}',title=f'Employer {i} · Software Engineer',
            evidence=f'Employer {i} Software Engineer Singapore. SQL is required. Python preferred. Build APIs.',reliability='official',retrieved_at=now()) for i in range(start,start+5)]

@pytest.fixture
def flow():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000);db=mongo['coachify_discovery_test_'+uuid4().hex]
    ai=AI();sources=Sources()
    def profile(request):return httpx.Response(200,json={'id':'22222222-2222-4222-8222-222222222222' if request.headers.get('authorization')=='Bearer other' else OWNER,'email_verified':True} if request.url.path.endswith('/session') else {'onboarding_complete':True})
    upstream=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile))
    try:
        with TestClient(create_app(database=db,ai=ai,context_ai=ai,research_client=sources,profile_client=upstream)) as client:yield client,db,ai,sources
    finally:mongo.drop_database(db.name);mongo.close()

def start(flow,message='I want to stay broad in software engineering'):
    client=flow[0];row=client.post(BASE,headers=headers(),json={'consent':True}).json()['session']
    response=client.post(f"{BASE}/{row['id']}/messages",headers=headers(),json={'expected_version':row['version'],'message':message})
    assert response.status_code==200,response.text
    return response.json()['session']

def research(flow,row,**kwargs):
    response=flow[0].post(f"{BASE}/{row['id']}/research",headers=headers(),json={'expected_version':row['version'],'scope':row['decision']['scope'],'confirmed':True,**kwargs})
    assert response.status_code==202,response.text
    return response.json()['session']

def wait(flow,row,status='review'):
    for _ in range(200):
        response=flow[0].get(f"{BASE}/{row['id']}",headers=headers());assert response.status_code==200,response.text
        value=response.json()['session']
        if value['status']==status:return value
        if value['status']=='failed' and status!='failed':pytest.fail(str(value))
        time.sleep(.025)
    pytest.fail(str(value))

@pytest.mark.parametrize('message',['Software Engineering','I want Backend Engineering','Keep it broad: Software Engineering','None of those three; other suggestions please','I changed my mind: Backend Engineering'])
def test_conversation_is_goal_setting_and_never_launches_search_without_confirmation(flow,message):
    row=start(flow,message)
    assert row['status']=='conversation' and row['decision']['action']=='CONFIRM_AREA'
    assert flow[3].calls==[] and flow[2].calls==['discovery_turn']
    assert flow[0].get(BASE+'/current',headers=headers()).json()['session']['decision']==row['decision']
    assert flow[0].get(f"{BASE}/{row['id']}",headers=headers(other=True)).status_code==404
    assert flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None


def test_research_reviews_then_confirms_through_shared_persistence_without_cv(flow,monkeypatch):
    row=start(flow);research(flow,row);row=wait(flow,row)
    assert row['listings_analysed']==10 and row['employers_analysed']==10
    assert row['coverage']=='good' and len(row['review']['extraction']['skills'])==2
    assert row['stats'][0]['requirement_type']=='core' and row['stats'][0]['mention_count']==10
    assert row['stats'][1]['requirement_type']=='optional'
    assert all('Singapore' in q and 'entry level' in q for q in flow[3].calls)
    assert flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None
    review=row['review'];content=review['extraction'];content['skills']=content['skills'][:1]
    response=flow[0].patch('/api/v1/career/goals/'+review['review_id']+'/review',headers=headers(),json={'expected_version':review['version'],'content':content})
    assert response.status_code==200,response.text
    review=response.json();seen=[];original=GoalStore.persist_target
    def save(store,goal):seen.append(goal);return original(store,goal)
    monkeypatch.setattr(GoalStore,'persist_target',save)
    key=str(uuid4());body={'target_type':'career_exploration','role':content['role'],'field':content['field'],'location':content['location'],'seniority_level':content['seniority_level'],'review_id':review['review_id'],'expected_review_version':review['version'],'expected_selection_version':0}
    response=flow[0].post('/api/v1/career/goals/confirm',headers=headers(key=key),json=body)
    assert response.status_code==200,response.text
    goal=CareerGoal.model_validate(response.json()['goal']);assert len(seen)==1
    assert goal.company is None and goal.job_url is None and goal.discovery.listings_analysed==10
    assert goal.skills[0].source_urls and goal.skills[0].origin=='market_research'
    assert flow[0].get('/api/v1/career/workspace',headers=headers()).json()['review']['review_id']==review['review_id']
    assert flow[0].post('/api/v1/career/goals/confirm',headers=headers(key=key),json=body).json()['selection_version']==1
    assert len(seen)==1
    assert flow[1].research_contexts.find_one({'_id':goal.discovery.research_id})['aggregate']['listings']


def test_quota_resume_reuses_searches_and_successful_extractions(flow):
    flow[2].quota_at=2;row=start(flow);research(flow,row);waiting=wait(flow,row,'waiting')
    assert waiting['limit_scope']=='user' and waiting['retry_after']<=1
    searches=len(flow[3].calls);row=wait(flow,row)
    assert row['listings_analysed']==10 and len(flow[3].calls)==searches
    assert flow[2].calls.count('discovery_extract')==5  # Four batches plus the denied second batch.


def test_empty_sources_and_empty_supported_listings_are_honest(flow):
    flow[3].empty=True;row=start(flow);research(flow,row);row=wait(flow,row)
    assert row['coverage']=='insufficient' and row['listings_analysed']==0 and row['review']['extraction']['skills']==[]
    assert 'discovery_extract' not in flow[2].calls and row['warnings']


def test_refresh_preserves_evidence_snapshot_and_requires_new_confirmation(flow):
    row=start(flow);research(flow,row);row=wait(flow,row);review=row['review'];calls=len(flow[3].calls)
    research(flow,row,refresh=True);latest=wait(flow,row)
    assert len(flow[3].calls)>calls and latest['review']['review_id']!=review['review_id']
    assert flow[1].research_contexts.count_documents({'kind':'career_discovery_evidence'})==2
    assert flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None


def test_schema_errors_are_bounded_and_leave_session_recoverable(flow):
    row=start(flow);flow[2].fail=True;research(flow,row);row=wait(flow,row,'failed')
    assert row['error_code']=='invalid_output' and flow[2].calls.count('discovery_plan')==2
    assert flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None


def test_fabricated_quotes_and_senior_requirements_cannot_enter_entry_level_target():
    source=ResearchSource(source_id='s',platform='employer',url='https://example.test/job',title='Employer · Software Engineer',evidence='Employer Software Engineer Singapore. SQL required.')
    listing=Listing(ref=0,company='Employer',job_title='Software Engineer',location='Singapore',career_stage='experienced',relevant=True,requirements=[Requirement(kind='skill',name='SQL',quote='SQL required.')])
    assert validated_listings(Listings(listings=[listing]),[source],SCOPE)==[]
    listing.career_stage='entry_level';listing.requirements[0].quote='Invented SQL required.'
    with pytest.raises(AIError):validated_listings(Listings(listings=[listing]),[source],SCOPE)


def test_duplicate_reposts_do_not_inflate_sample_or_frequency():
    item={'company':'Employer','job_title':'Software Engineer','location':'Singapore','source_id':'s','source_url':'https://example.test/one','requirements':[{'kind':'skill','name':'SQL','category':'technical','quote':'SQL required.','preferred':False}]}
    result=aggregate(SCOPE,[item,{**item,'source_id':'repost','source_url':'https://example.test/two'}])
    assert len(result['listings'])==1 and result['stats'][0]['mention_count']==1 and result['stats'][0]['sample_size']==1
