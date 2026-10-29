from app.schemas.jd import JDExtraction
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
from app.schemas.discovery import Scope,Decision,Plan,Listings,MarketSummary,Listing,Requirement,RecommendedSkill,ConversationMemory,SourceAssessment,SourceAssessments,DiscoveryUnderstanding,DiscoveryAnswer
from app.schemas.analysis import Generation,CareerGoal
from app.schemas.discovery import DiscoverySource as ResearchSource
from app.repositories.goals import now,GoalStore
from app.workflows.discovery import aggregate,validated_listings
from app.domain.discovery_readiness import REQUIRED_FIELDS

OWNER='11111111-1111-4111-8111-111111111111'
BASE='/api/v1/career/discoveries'
def headers(other=False,key=None):return {'Authorization':'Bearer '+('other' if other else 'owner'),'Idempotency-Key':key or str(uuid4())}
SCOPE=Scope(field='Software Engineering',area='Software Engineering',career_stage='entry_level',location='Singapore')
PROFILE='Research context: starting my career; Singapore; I enjoy building software; focus on engineering; other interests: music; no activities to avoid; no work constraints; I am clear about this direction.'
UNSURE_PROFILE=PROFILE.replace('starting my career','unsure about career stage').replace('Singapore','unsure about location')

def complete_understanding(profile=PROFILE):
    values={'field':'Software Engineering','role_family_or_work':'building software','interest':'building software',
        'career_stage':'entry_level','location':'Singapore','other_interests':'music',
        'avoided_activities':'none','work_preferences':'none','skill_ambiguity':'resolved'}
    result=DiscoveryUnderstanding(**{key:DiscoveryAnswer(status='known',value=value,evidence=profile) for key,value in values.items()})
    if profile==UNSURE_PROFILE:
        for key in ('career_stage','location'):setattr(result,key,DiscoveryAnswer(status='unsure',evidence=profile))
    return result


class AI:
    settings=SimpleNamespace(enabled=True,model='synthetic')
    def __init__(self):self.calls=[];self.contexts=[];self.quota_at=None;self.empty=False;self.fail=False;self.question=False;self.hook=None;self.result_override=None
    async def generate(self,request,operation,**kwargs):
        self.calls.append(request.stage);data=json.loads(request.context);self.contexts.append((request,data))
        if self.hook:await self.hook(request,data)
        if self.fail:raise AIError('invalid_output')
        if request.stage=='discovery_turn':
            raw_message=request.conversation[-1].content
            message=raw_message.split('\nResearch context:',1)[0]
            understanding=DiscoveryUnderstanding.model_validate(data.get('understanding',{}))
            if '\nResearch context:' in raw_message:understanding=complete_understanding(raw_message.split('\n',1)[1])
            scope=SCOPE.model_copy(update={'area':'Backend Engineering','specificity':'specialisation'}) if 'Backend' in message else SCOPE
            previous=data.get('previous') or {}
            memory=ConversationMemory.model_validate(data.get('memory',{}))
            if 'problem solving' in message:memory.interests=['problem solving']
            if 'customer-facing' in message:memory.preferences=['Avoid customer-facing work']
            if message.startswith('Question:'):action='ANSWER'
            elif message.startswith(('Remove ','Add ')):action='REFINE_SKILLS'
            else:action='START_RESEARCH'
            if message=='Unsure':scope=None;action='ASK_CLARIFICATION'
            if message=='Broad direction':scope=Scope(field='Software Engineering',area='Software Engineering')
            result=Decision(action=action,scope=scope,question='What kind of work interests you?' if scope is None else None,
                reply='Let’s explore your career direction.',understanding=understanding,memory=memory,recommendations=[],
                excluded_skills=[message.removeprefix('Remove ')] if message.startswith('Remove ') else previous.get('excluded_skills',[]),
                requested_skills=[message.removeprefix('Add ')] if message.startswith('Add ') else previous.get('requested_skills',[]))
        elif request.stage=='discovery_plan':result=Plan(related_roles=['Software Engineer','Backend Engineer'],queries=['graduate software jobs','graduate backend jobs'])
        elif request.stage=='discovery_assess':
            result=SourceAssessments(sources=[SourceAssessment(ref=i,relevant=True,score=3,quote='Software Engineer') for i,source in enumerate(data['sources'])])
        elif request.stage=='discovery_extract':
            count=self.calls.count('discovery_extract')
            if count==self.quota_at:raise AIError('rate_limited',limit_scope='user',retry_after=1,provider='gemini')
            result=Listings(listings=[] if self.empty else [Listing(ref=i,job_title='Software Engineer',location='Singapore',career_stage='entry_level',relevant=True,requirements=[Requirement(kind='skill',name='SQL',quote='SQL is required.'),Requirement(kind='skill',name='Python',quote='Python preferred.',preferred=True),Requirement(kind='responsibility',name='Build APIs',quote='Build APIs.')]) for i,s in enumerate(data['sources'])])
        elif request.stage=='discovery_summary':
            result=MarketSummary(responsibility_refs=[0] if data['responsibilities'] else [],skills=[RecommendedSkill(
                name=skill['name'],skill_refs=[i],requirement_type='core' if skill['name']=='SQL' else 'optional',
                relevance='Useful for working with application data.',learning_priority='high' if skill['name']=='SQL' else 'low')
                for i,skill in enumerate(data['skills']) if skill['name'] not in data.get('excluded_skills',[])]+[RecommendedSkill(
                    name=name,skill_refs=[],requirement_type='optional',relevance='An addition requested by the user.',learning_priority='low')
                    for name in data.get('requested_skills',[])])
        else:raise AssertionError(request.stage)
        if request.stage=='discovery_extract' and self.question:result.question='Would you prefer building APIs or analysing data?';result.question_refs=[0]
        if self.result_override:result=self.result_override(request,result)
        if kwargs.get('validate_output'):kwargs['validate_output'](result)
        return SimpleNamespace(data=result,generation=Generation(provider='synthetic',model='synthetic',prompt_version='test',generated_at=now()))

class Sources:
    configured=True;brave_mode='llm_context'
    def __init__(self):self.calls=[];self.empty=False;self.fail=False
    async def collect_discovery_query(self,context,query):
        self.calls.append(query)
        if self.fail:raise TimeoutError()
        if self.empty:return []
        start=0 if len(self.calls)%2 else 5
        return [ResearchSource(source_id=f'job-{i}',platform='employer',url=f'https://example.test/jobs/{i}',company=f'Employer {i}',title=f'Employer {i} · Software Engineer',
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

def start(flow,message='I want to stay broad in software engineering',profile=PROFILE):
    if profile:message+='\n'+profile
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

@pytest.mark.parametrize('message',['Software Engineering','I want Backend Engineering','Keep it broad: Software Engineering','I changed my mind: Backend Engineering'])
def test_clear_direction_automatically_launches_research_without_saving_goal(flow,message):
    row=start(flow,message)
    assert row['status']=='researching' and row['decision']['action']=='START_RESEARCH'
    row=wait(flow,row)
    assert flow[3].calls
    assert flow[0].get(f"{BASE}/{row['id']}",headers=headers(other=True)).status_code==404
    assert flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None


def test_unclear_interests_ask_one_question_without_research(flow):
    row=start(flow,'Unsure')
    assert row['status']=='conversation' and row['decision']['reply']
    assert not flow[3].calls


def test_unknown_stage_and_location_do_not_block_research(flow):
    row=start(flow,'Broad direction',profile=UNSURE_PROFILE)
    assert row['status']=='researching' and row['scope']['location'] is None
    assert row['scope']['career_stage']=='unspecified'
    assert wait(flow,row)['status']=='review'


def test_research_reviews_then_confirms_through_shared_persistence_without_cv(flow,monkeypatch):
    row=start(flow);row=wait(flow,row)
    assert row['listings_analysed']==10 and row['employers_analysed']==10
    assert row['coverage']=='good' and len(row['review']['current']['goal']['skills'])==2
    assert row['stats'][0]['requirement_type']=='core' and row['stats'][0]['mention_count']==10
    assert row['stats'][1]['requirement_type']=='optional'
    assert all('Singapore' in q and 'entry level' in q for q in flow[3].calls)
    assert flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None
    review=row['review'];content={k:v for k,v in review['current']['goal'].items() if k in JDExtraction.model_fields};content['skills']=content['skills'][:1]
    response=flow[0].patch('/api/v1/career/goals/'+review['current']['goal']['_id']+'/review',headers=headers(),json={'expected_version':review['current']['goal']['version'],'content':content})
    assert response.status_code==200,response.text
    review=response.json();seen=[];original=GoalStore.persist_target
    def save(store,goal):seen.append(goal);return original(store,goal)
    monkeypatch.setattr(GoalStore,'persist_target',save)
    key=str(uuid4());body={'target_type':'career_exploration','role':content['role'],'field':content['field'],'location':content['location'],'seniority_level':content['seniority_level'],'review_id':review['current']['goal']['_id'],'expected_review_version':review['current']['goal']['version'],'expected_selection_version':0}
    response=flow[0].post('/api/v1/career/goals/confirm',headers=headers(key=key),json=body)
    assert response.status_code==200,response.text
    goal=CareerGoal.model_validate(response.json()['goal']);assert len(seen)==1
    assert goal.company is None and goal.job_url is None and goal.discovery.listings_analysed==10
    assert goal.skills[0].source_urls and goal.skills[0].origin=='generated_guidance'
    assert goal.skills[0].priority=='suggested' and goal.skills[0].evidence is None
    assert flow[0].get('/api/v1/career/workspace',headers=headers()).json()['current']['goal']['_id']==review['current']['goal']['_id']
    assert flow[0].post('/api/v1/career/goals/confirm',headers=headers(key=key),json=body).json()['selection_version']==1
    assert len(seen)==1
    assert flow[1].research_contexts.find_one({'_id':goal.discovery.research_id})['aggregate']['listings']


def test_quota_resume_reuses_searches_and_successful_extractions(flow):
    flow[2].quota_at=2;row=start(flow);waiting=wait(flow,row,'waiting')
    assert waiting['limit_scope']=='user' and waiting['retry_after']<=1
    searches=len(flow[3].calls);row=wait(flow,row)
    assert row['listings_analysed']==10 and len(flow[3].calls)==searches
    assert flow[2].calls.count('discovery_extract')==5  # Four batches plus the denied second batch.


def test_empty_sources_and_empty_supported_listings_are_honest(flow):
    flow[3].empty=True;row=start(flow);row=wait(flow,row,'failed')
    assert row['error_code']=='invalid_output' and row['listings_analysed']==0 and row['review'] is None
    assert 'discovery_extract' not in flow[2].calls
    assert len(flow[3].calls)==3 and 'alternative employers' in flow[3].calls[-1]


def test_refresh_preserves_evidence_snapshot_and_requires_new_confirmation(flow):
    row=start(flow);row=wait(flow,row);review=row['review'];calls=len(flow[3].calls)
    research(flow,row,refresh=True);latest=wait(flow,row)
    assert len(flow[3].calls)>calls and latest['review']['current']['goal']['_id']!=review['current']['goal']['_id']
    assert flow[1].research_contexts.count_documents({'kind':'career_discovery_evidence'})==2
    assert flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None


def test_schema_errors_are_bounded_and_leave_session_recoverable(flow):
    flow[2].fail=True;
    # Fail research after the initial direction decision, not conversation.
    original=flow[2].generate
    async def generate(request,*args,**kwargs):
        flow[2].fail=request.stage!='discovery_turn'
        return await original(request,*args,**kwargs)
    flow[2].generate=generate
    row=start(flow);row=wait(flow,row,'failed')
    assert row['error_code']=='invalid_output' and flow[2].calls.count('discovery_plan')==2
    assert flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None


def test_paraphrased_evidence_is_allowed_but_stage_mismatches_are_excluded():
    source=ResearchSource(source_id='s',platform='employer',url='https://example.test/job',title='Employer · Software Engineer',evidence='Employer Software Engineer Singapore. SQL required.')
    listing=Listing(ref=0,job_title='Software Engineer',location='Singapore',career_stage='experienced',relevant=True,requirements=[Requirement(kind='skill',name='SQL',quote='SQL required.')])
    assert validated_listings(Listings(listings=[listing]),[source],SCOPE)==[]
    listing.career_stage='entry_level';listing.requirements[0].quote='The role requires SQL skills.'
    parsed=validated_listings(Listings(listings=[listing]),[source],SCOPE)
    assert parsed[0]['requirements'][0]['quote']=='The role requires SQL skills.'
    assert parsed[0]['company'] is None


def test_duplicate_reposts_do_not_inflate_sample_or_frequency():
    item={'company':'Employer','job_title':'Software Engineer','location':'Singapore','source_id':'s','source_url':'https://example.test/one','requirements':[{'kind':'skill','name':'SQL','category':'technical','quote':'SQL required.','preferred':False}]}
    result=aggregate(SCOPE,[item,{**item,'source_id':'repost','source_url':'https://example.test/two'}])
    assert len(result['listings'])==1 and result['stats'][0]['mention_count']==1 and result['stats'][0]['sample_size']==1


def test_interrupted_conversation_commit_reuses_checkpoint_only_for_the_same_payload(flow):
    client,db,ai,_=flow
    row=client.post(BASE,headers=headers(),json={'consent':True}).json()['session']
    service=client.app.state.discovery;original=service.rows
    class InterruptedWrite:
        failed=False
        def __getattr__(self,name):return getattr(original,name)
        def update_one(self,query,update,**kwargs):
            if query.get('owner')==OWNER and query.get('version')==row['version'] and not self.failed:
                self.failed=True
                from app.repositories.goals import GoalError
                raise GoalError('Synthetic commit interruption.',503)
            return original.update_one(query,update,**kwargs)
    service.rows=InterruptedWrite()
    key=str(uuid4());path=f"{BASE}/{row['id']}/messages"
    body={'expected_version':row['version'],'message':'Software Engineering'}
    assert client.post(path,headers=headers(key=key),json=body).status_code==503
    assert ai.calls.count('discovery_turn')==1
    assert client.post(path,headers=headers(key=key),json={**body,'message':'Backend Engineering'}).status_code==409
    restored=client.post(path,headers=headers(key=key),json=body)
    assert restored.status_code==200,restored.text
    assert restored.json()['session']['decision']['scope']['area']=='Software Engineering'
    assert ai.calls.count('discovery_turn')==1


def send(flow,row,message,key=None):
    response=flow[0].post(f"{BASE}/{row['id']}/messages",headers=headers(key=key),json={'expected_version':row['version'],'message':message})
    assert response.status_code==200,response.text
    return response.json()['session']


def test_memory_recent_context_and_transcript_survive_reload_without_research_for_questions(flow):
    row=wait(flow,start(flow,'I enjoy problem solving'));calls=len(flow[3].calls)
    row=wait(flow,send(flow,row,'Question: I dislike customer-facing work'))
    restored=flow[0].get(BASE+'/current',headers=headers()).json()['session']
    assert restored['messages']==row['messages']
    assert restored['decision']['memory']['interests']==['problem solving']
    assert restored['decision']['memory']['preferences']==['Avoid customer-facing work']
    assert len(flow[3].calls)==calls and row['status']=='review'
    request,context=[v for v in flow[2].contexts if v[0].stage=='discovery_turn'][-1]
    assert context['memory']['interests']==['problem solving']
    assert len(request.conversation)<=7 and request.conversation[-1].content=='Question: I dislike customer-facing work'
    assert all(len(m.content)<=400 for m in request.conversation[:-1])
    assert 'sources' not in context and context['facts']
    assert flow[0].get(f"{BASE}/{row['id']}",headers=headers(other=True)).status_code==404


def test_duplicate_message_replay_does_not_duplicate_transcript_or_research(flow):
    row=wait(flow,start(flow));version=row['version'];key=str(uuid4())
    updated=send(flow,row,'Question: What is SQL?',key)
    replay=send(flow,{**updated,'version':version},'Question: What is SQL?',key)
    assert replay['messages']==updated['messages'] and flow[2].calls.count('discovery_turn')==2
    response=flow[0].post(f"{BASE}/{row['id']}/messages",headers=headers(key=key),json={'expected_version':version,'message':'Different payload'})
    assert response.status_code==409


def test_skill_refinement_reuses_evidence_and_retains_original_market_observations(flow):
    row=wait(flow,start(flow));searches=len(flow[3].calls);previous=row['review']['current']['goal']['discovery']['research_id']
    row=wait(flow,send(flow,row,'Remove Python'))
    assert len(flow[3].calls)==searches
    assert [s['name'] for s in row['review']['current']['goal']['skills']]==['SQL']
    assert any(s['name']=='Python' for s in row['stats'])
    assert flow[1].research_contexts.find_one({'_id':previous})
    assert row['review']['current']['goal']['discovery']['research_id']!=previous
    assert flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None


def test_chat_and_scope_change_during_search_prevent_old_results_from_publishing(flow):
    import threading
    entered=threading.Event();release=threading.Event();original=flow[3].collect_discovery_query
    async def slow(context,query):
        if context.role=='Software Engineering':
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
        return await original(context,query)
    flow[3].collect_discovery_query=slow
    row=start(flow);assert entered.wait(2)
    try:
        answered=send(flow,row,'Question: I prefer problem solving')
        assert answered['status']=='researching' and len(answered['messages'])==4
        changed=send(flow,answered,'I changed my mind: Backend Engineering')
        assert changed['scope']['area']=='Backend Engineering'
    finally:release.set()
    final=wait(flow,changed)
    assert final['review']['current']['goal']['role']=='Backend Engineering'
    assert all('Your career direction: **Software Engineering**' not in m['content'] for m in final['messages'])


def test_research_asks_optional_question_without_stopping_and_accepts_answer(flow):
    import threading
    asked=threading.Event();release=threading.Event();flow[2].question=True
    async def hook(request,data):
        if request.stage=='discovery_extract' and flow[2].calls.count('discovery_extract')==2:
            asked.set()
            while not release.is_set():await asyncio.sleep(.01)
    flow[2].hook=hook
    row=start(flow);assert asked.wait(2)
    try:
        current=flow[0].get(f"{BASE}/{row['id']}",headers=headers()).json()['session']
        questions=[m for m in current['messages'] if 'Would you prefer' in m['content']]
        assert len(questions)==1 and 'https://example.test/jobs/' in questions[0]['content']
        row=send(flow,current,'Question: I enjoy problem solving')
        assert row['status']=='researching'
    finally:release.set()
    row=wait(flow,row)
    assert len([m for m in row['messages'] if 'Would you prefer' in m['content']])==1
    assert flow[2].contexts[-1][1]['memory']['interests']==['problem solving']


def test_conversation_changed_during_synthesis_recomputes_before_publishing(flow):
    import threading
    entered=threading.Event();release=threading.Event()
    async def hook(request,data):
        if request.stage=='discovery_summary' and flow[2].calls.count('discovery_summary')==1:
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
    flow[2].hook=hook
    row=start(flow);assert entered.wait(2)
    try:row=send(flow,row,'Question: I enjoy problem solving')
    finally:release.set()
    final=wait(flow,row)
    assert flow[2].calls.count('discovery_summary')==2
    assert len([m for m in final['messages'] if 'Your career direction:' in m['content']])==1
    assert flow[2].contexts[-1][1]['memory']['interests']==['problem solving']


def test_user_added_skill_is_never_presented_as_a_market_requirement(flow):
    row=wait(flow,start(flow));searches=len(flow[3].calls)
    row=wait(flow,send(flow,row,'Add Drawing'))
    skill=next(s for s in row['review']['current']['goal']['skills'] if s['name']=='Drawing')
    assert skill['origin']=='user_declaration' and skill['evidence'] is None and skill['source_urls']==[]
    assert len(flow[3].calls)==searches
    assert 'user-requested addition; no listing evidence' in row['messages'][-1]['content']


def test_synthesis_can_consolidate_alternatives_without_making_every_tool_required(flow):
    def override(request,result):
        if request.stage=='discovery_summary':return MarketSummary(responsibility_refs=[0],skills=[RecommendedSkill(
            name='Working with application data',skill_refs=[0,1],requirement_type='core',relevance='Practise querying and processing application data; tools can vary.',learning_priority='high')])
        return result
    flow[2].result_override=override
    row=wait(flow,start(flow));skills=row['review']['current']['goal']['skills']
    assert len(skills)==1 and len(row['stats'])==2
    assert skills[0]['origin']=='generated_guidance' and skills[0]['priority']=='suggested'
    assert skills[0]['source_urls'] and skills[0]['evidence'] is None


def test_forged_synthesis_references_fail_with_bounded_repair(flow):
    def override(request,result):
        if request.stage=='discovery_summary':result.skills[0].skill_refs=[999]
        return result
    flow[2].result_override=override
    row=wait(flow,start(flow),'failed')
    assert row['review'] is None and row['error_code']=='invalid_output'
    assert flow[2].calls.count('discovery_summary')==2


def test_chat_rejects_forged_citations_without_saving_messages(flow):
    row=wait(flow,start(flow));messages=row['messages']
    def override(request,result):
        if request.stage=='discovery_turn':result.source_ids=['invented']
        return result
    flow[2].result_override=override
    response=flow[0].post(f"{BASE}/{row['id']}/messages",headers=headers(),json={'expected_version':row['version'],'message':'Question: What is SQL?'})
    assert response.status_code>=400
    assert flow[0].get(BASE+'/current',headers=headers()).json()['session']['messages']==messages


def test_chat_context_is_bounded_independently_of_transcript_length(flow):
    row=wait(flow,start(flow,'I enjoy problem solving'))
    db=flow[1];stored=[{'role':'assistant' if i%2 else 'user','content':str(i)+' synthetic text '*100} for i in range(80)]
    db.research_contexts.update_one({'_id':row['id']},{'$set':{'messages':stored}})
    send(flow,row,'Question: Tell me about SQL')
    request,context=[v for v in flow[2].contexts if v[0].stage=='discovery_turn'][-1]
    assert len(request.conversation)==7
    assert all(len(m.content)<=400 for m in request.conversation[:-1])
    assert len(context['facts'])<=16 and context['memory']['interests']==['problem solving']
    assert len(json.dumps(context))<6000


def test_discovery_openapi_models_match_application():
    from pathlib import Path
    saved=json.loads((Path(__file__).resolve().parents[3]/'contracts/api/career.yaml').read_text())
    current=create_app().openapi()
    for name in ('Decision','DiscoveryAnswer','DiscoveryUnderstanding','DiscoveryView','DiscoverySession','ConversationMemory','ChatMessage','MarketSummary','RecommendedSkill'):
        assert saved['components']['schemas'][name]==current['components']['schemas'][name]


def test_transcript_capacity_prevents_unbounded_session_growth():
    from app.workflows.discovery import check_conversation_capacity
    from app.repositories.goals import GoalError
    with pytest.raises(GoalError):check_conversation_capacity({'messages':[{'role':'user','content':'x'}]*996})
    with pytest.raises(GoalError):check_conversation_capacity({'messages':[{'role':'assistant','content':'界'*12000}]*100})


def test_truncated_batches_split_without_repeating_the_same_paid_request(flow):
    async def hook(request,data):
        if request.stage=='discovery_extract' and len(data['sources'])>1:raise AIError('incomplete_output')
    flow[2].hook=hook
    row=wait(flow,start(flow))
    assert row['listings_analysed']==10 and row['coverage']=='good'
    batches=[tuple(s['title'] for s in data['sources']) for request,data in flow[2].contexts if request.stage=='discovery_extract']
    assert len(batches)==len(set(batches))
    assert any(len(batch)>1 for batch in batches)
    assert len([batch for batch in batches if len(batch)==1])==10


def test_split_extraction_quota_resume_keeps_successful_children_and_searches(flow):
    singles=[];blocked=False
    async def hook(request,data):
        nonlocal blocked
        if request.stage!='discovery_extract':return
        if len(data['sources'])>1:raise AIError('incomplete_output')
        if len(singles)==1 and not blocked:
            blocked=True;raise AIError('rate_limited',limit_scope='provider',retry_after=1,provider='gemini')
        singles.append(data['sources'][0]['title'])
    flow[2].hook=hook
    row=start(flow);waiting=wait(flow,row,'waiting');searches=len(flow[3].calls)
    first=singles[0];row=wait(flow,waiting)
    assert row['listings_analysed']==10 and singles.count(first)==1
    assert len(flow[3].calls)==searches


def test_one_unextractable_listing_keeps_other_results_and_reports_partial_coverage(flow):
    async def hook(request,data):
        if request.stage=='discovery_extract' and any(s['title'].startswith('Employer 0 ·') for s in data['sources']):raise AIError('incomplete_output')
    flow[2].hook=hook
    row=wait(flow,start(flow))
    assert row['status']=='review' and row['listings_analysed']==9 and row['coverage']=='limited'
    assert len(row['sources'])==9 and all(not source['title'].startswith('Employer 0 ·') for source in row['sources'])
    assert any('incomplete' in warning for warning in row['warnings'])
    assert row['review'] and flow[0].get('/api/v1/career/goals/current',headers=headers()).json()['goal'] is None
    single=[data for request,data in flow[2].contexts if request.stage=='discovery_extract' and len(data['sources'])==1 and data['sources'][0]['title'].startswith('Employer 0 ·')]
    assert [data['max_requirements'] for data in single]==[15,8]


def test_relevant_listings_after_early_indexes_and_unrelated_pages_are_selected(flow):
    async def collect(context,query):
        flow[3].calls.append(query)
        return [ResearchSource(source_id=f'candidate-{i}',platform='other',
            url=f'https://example.test/'+('job-descriptions/' if i<8 else 'unrelated/' if i<10 else 'jobs/')+str(i),
            company=f'Employer {i}',title=f'Employer {i} · Software Engineer',evidence=f'Employer {i} Software Engineer Singapore. SQL is required. Python preferred. Build APIs.') for i in (range(20,25) if 'alternative employers' in query else range(20))]
    def override(request,result):
        if request.stage=='discovery_assess':
            data=json.loads(request.context)
            for item in result.sources:
                if '/unrelated/' in data['sources'][item.ref]['url']:
                    item.relevant=False;item.score=0;item.quote=None
        return result
    flow[3].collect_discovery_query=collect;flow[2].result_override=override
    row=wait(flow,start(flow))
    assert row['listings_analysed']==15 and row['employers_analysed']==15
    assert len(row['sources'])==15 and all('/jobs/' in source['url'] for source in row['sources'])
    assert len(flow[3].calls)==3 and any('10 retrieved pages were excluded' in warning for warning in row['warnings'])


def test_relevance_backfills_after_selected_candidates_fail_stage_validation(flow):
    async def collect(context,query):
        index=len(flow[3].calls);flow[3].calls.append(query)
        return [ResearchSource(source_id=f'candidate-{i}',platform='other',url=f'https://example.test/job/{i:02d}',
            company=f'Employer {i}',title=f'Employer {i} · Software Engineer',evidence=f'Employer {i} Software Engineer Singapore. SQL is required. Python preferred. Build APIs.') for i in range(index*20,(index+1)*20)]
    def override(request,result):
        if request.stage=='discovery_extract':
            data=json.loads(request.context)
            for item in result.listings:
                number=int(data['sources'][item.ref]['title'].split()[1])
                if number<20:item.career_stage='experienced'
        return result
    flow[3].collect_discovery_query=collect;flow[2].result_override=override
    row=wait(flow,start(flow))
    assert row['listings_analysed']==20 and row['employers_analysed']==20
    assert all(int(source['url'].rsplit('/',1)[-1])>=20 for source in row['sources'])
    assert len(flow[3].calls)==3


def test_start_acknowledgement_does_not_request_research_permission_or_restart(flow):
    def override(request,result):
        if request.stage=='discovery_turn':result.reply='Would you like to start research?';result.question='Would you like to start research?'
        return result
    flow[2].result_override=override
    row=wait(flow,start(flow));calls=len(flow[3].calls)
    assert all('Would you like to start research?' not in message['content'] for message in row['messages'])
    assert row['decision']['question'] is None
    latest=send(flow,row,'yes')
    assert latest['status']=='review' and len(flow[3].calls)==calls


def test_repeated_irrelevant_contexts_keep_relevant_results_after_one_replacement_search(flow):
    async def collect(context,query):
        index=len(flow[3].calls);flow[3].calls.append(query)
        return [ResearchSource(source_id=f'candidate-{index}-{kind}',platform='other',
            url=f'https://example.test/{kind}/{index}',company=f'Employer {index}',title=f'Employer {index} · Software Engineer',
            evidence=f'Employer {index} Software Engineer Singapore. SQL is required. Python preferred. Build APIs.')
            for kind in ('job-descriptions','unrelated','jobs')]
    def override(request,result):
        if request.stage=='discovery_assess':
            data=json.loads(request.context)
            for item in result.sources:
                if '/unrelated/' in data['sources'][item.ref]['url']:
                    item.relevant=False;item.score=0;item.quote=None
        return result
    flow[3].collect_discovery_query=collect;flow[2].result_override=override
    row=wait(flow,start(flow))
    assert row['coverage']=='limited' and row['listings_analysed']==len(flow[3].calls)
    assert row['review'] is not None and row['error_code'] is None
    assert all('/jobs/' in item['url'] for item in row['sources'])
    assert sum('alternative employers' in query for query in flow[3].calls)==1
    assert any('single replacement search' in warning for warning in row['warnings'])
    stored=flow[1].research_contexts.find_one({'_id':row['id']})
    assert stored['replacement_searches']==1


def test_retry_does_not_reuse_candidates_from_old_twenty_url_policy(flow):
    row=wait(flow,start(flow));previous=row['review']['current']['goal']['discovery']['research_id'];calls=len(flow[3].calls)
    flow[1].research_contexts.update_one({'_id':row['id']},{'$set':{'research_policy':'discovery-listings-v2','status':'failed'}})
    row=wait(flow,research(flow,row))
    assert len(flow[3].calls)>calls
    assert row['review']['current']['goal']['discovery']['research_id']!=previous
    assert flow[1].research_contexts.find_one({'_id':previous})


def test_new_session_has_no_introduction_or_model_or_search_calls(flow):
    from app.domain.discovery_conversation import INTRODUCTION
    key=str(uuid4())
    first=flow[0].post(BASE,headers=headers(key=key),json={'consent':True})
    assert first.status_code==200
    row=first.json()['session']
    assert row['messages']==[]
    assert 'introduction' not in first.json()
    assert row['decision'] is None and row['scope'] is None and row['summary'] is None
    assert row['sources']==[] and row['stats']==[] and row['review'] is None
    replay=flow[0].post(BASE,headers=headers(key=key),json={'consent':True})
    assert replay.json()['session']['id']==row['id']
    assert replay.json()['session']['messages']==row['messages']
    assert flow[2].calls==[] and flow[3].calls==[]


def test_fresh_open_does_not_load_previous_conversation_or_call_models(flow):
    from app.domain.discovery_conversation import INTRODUCTION
    previous=wait(flow,start(flow,'I enjoy problem solving'))
    calls=list(flow[2].calls);searches=list(flow[3].calls)
    response=flow[0].get(BASE+'/current?fresh=true',headers=headers())
    assert response.status_code==200 and response.json()['session'] is None
    assert response.json()['introduction']==INTRODUCTION
    assert flow[2].calls==calls and flow[3].calls==searches
    assert flow[0].get(BASE+'/current',headers=headers()).json()['session']['id']==previous['id']


def test_distinct_start_keys_create_isolated_chats_with_no_inherited_memory(flow):
    from app.domain.discovery_conversation import INTRODUCTION
    previous=wait(flow,start(flow,'I enjoy problem solving'))
    calls=list(flow[2].calls);searches=list(flow[3].calls)
    response=flow[0].post(BASE,headers=headers(),json={'consent':True})
    assert response.status_code==200
    fresh=response.json()['session']
    assert fresh['id']!=previous['id'] and fresh['version']==1
    assert fresh['messages']==[]
    assert 'introduction' not in response.json()
    assert fresh['decision'] is None and fresh['scope'] is None and fresh['review'] is None and fresh['sources']==[]
    assert flow[2].calls==calls and flow[3].calls==searches
    fresh=wait(flow,send(flow,fresh,'Backend Engineering\n'+PROFILE))
    request,context=[v for v in flow[2].contexts if v[0].stage=='discovery_turn'][-1]
    assert context['previous']=={} and context['memory']=={} and context['facts']==[]
    assert all('problem solving' not in message.content for message in request.conversation)
    assert flow[0].get(f"{BASE}/{previous['id']}",headers=headers()).json()['session']['messages']==previous['messages']


def test_introduction_is_only_returned_on_fresh_open_and_never_sent_to_ai(flow):
    from app.domain.discovery_conversation import INTRODUCTION
    opened=flow[0].get(BASE+'/current?fresh=true',headers=headers()).json()
    assert opened['introduction']==INTRODUCTION
    row=wait(flow,start(flow,'I enjoy problem solving'))
    for path in (BASE+'/current',f"{BASE}/{row['id']}"):
        payload=flow[0].get(path,headers=headers()).json()
        assert INTRODUCTION not in json.dumps(payload,ensure_ascii=False)
        assert 'introduction' not in payload
    # Previously created sessions may still contain the display-only message.
    flow[1].research_contexts.update_one({'_id':row['id']},
        {'$push':{'messages':{'$each':[{'role':'assistant','content':INTRODUCTION}],'$position':0}}})
    response=flow[0].post(f"{BASE}/{row['id']}/messages",headers=headers(),
        json={'expected_version':row['version'],'message':'Question: Tell me about SQL'})
    assert response.status_code==200
    assert 'introduction' not in response.json()
    assert INTRODUCTION not in json.dumps(response.json(),ensure_ascii=False)
    for request,context in flow[2].contexts:
        assert INTRODUCTION not in request.context
        assert all(not INTRODUCTION.startswith(message.content) for message in request.conversation)


def replacement_provider(flow, *, fail_quota_once=False):
    original=flow[3].collect_discovery_query
    quota=False
    async def collect(context,query):
        nonlocal quota
        if 'alternative employers' not in query:return await original(context,query)
        flow[3].calls.append(query)
        if fail_quota_once and not quota:
            from app.clients.search_sources import SourceRateLimit
            quota=True
            raise SourceRateLimit(1)
        return [ResearchSource(source_id=f'replacement-{i}',platform='employer',
            url=f'https://example.test/jobs/{i}',company=f'Employer {i}',
            title=f'Employer {i} · Software Engineer',
            evidence=f'Employer {i} Software Engineer Singapore. SQL is required. Python preferred. Build APIs.')
            for i in range(10,15)]
    flow[3].collect_discovery_query=collect


@pytest.mark.parametrize('failure',['schema','irrelevant','extraction'])
def test_invalid_evidence_gets_one_new_search_and_keeps_other_results(flow,failure):
    replacement_provider(flow)
    async def hook(request,data):
        stage='discovery_extract' if failure=='extraction' else 'discovery_assess'
        if failure!='irrelevant' and request.stage==stage and any(s['title'].startswith('Employer 0 ·') for s in data['sources']):
            raise AIError('invalid_output',reason='schema_validation',fields=('sources',))
    def override(request,result):
        if failure=='irrelevant' and request.stage=='discovery_assess':
            data=json.loads(request.context)
            for item in result.sources:
                if data['sources'][item.ref]['title'].startswith('Employer 0 ·'):item.relevant=False
        return result
    flow[2].hook=hook;flow[2].result_override=override
    row=wait(flow,start(flow))
    assert row['status']=='review' and row['review']['current']['goal']['company'] is None
    assert len(flow[3].calls)==3 and 'alternative employers' in flow[3].calls[-1]
    assert 'Software Engineering' in flow[3].calls[-1] and 'Singapore' in flow[3].calls[-1]
    assert all(not item['title'].startswith('Employer 0 ·') for item in row['sources'])
    assert any(item['title'].startswith('Employer 10 ·') for item in row['sources'])
    assert any(item['title'].startswith('Employer 5 ·') for item in row['sources'])
    assert row['listings_analysed']==(14 if failure=='irrelevant' else 12)
    stored=flow[1].research_contexts.find_one({'_id':row['id']})
    assert stored['replacement_searches']==1
    # Invalid Gemini output is not regenerated with the same evidence.
    attempts=[request.context for request,data in flow[2].contexts if request.stage in ('discovery_assess','discovery_extract')]
    assert len(attempts)==len(set(attempts))


def test_replacement_failure_stops_without_a_second_error_retry(flow):
    replacement_provider(flow)
    async def hook(request,data):
        if request.stage=='discovery_assess':raise AIError('invalid_output',reason='schema_validation',fields=('sources',))
    flow[2].hook=hook
    row=wait(flow,start(flow),'failed')
    assert row['error_code']=='invalid_output' and row['review'] is None
    assert len(flow[3].calls)==3
    assert flow[1].research_contexts.find_one({'_id':row['id']})['replacement_searches']==1
    assert 'discovery_extract' not in flow[2].calls


def test_replacement_search_quota_wait_resumes_without_spending_another_retry(flow):
    replacement_provider(flow,fail_quota_once=True)
    def override(request,result):
        if request.stage=='discovery_assess':
            data=json.loads(request.context)
            for item in result.sources:
                if data['sources'][item.ref]['title'].startswith('Employer 0 ·'):item.relevant=False
        return result
    flow[2].result_override=override
    row=wait(flow,start(flow),'waiting')
    assert row['provider']=='brave'
    row=wait(flow,row)
    assert row['status']=='review' and row['listings_analysed']==14
    assert flow[1].research_contexts.find_one({'_id':row['id']})['replacement_searches']==1


def test_discovery_keeps_faithful_paraphrases_without_literal_matching(flow):
    def override(request,result):
        if request.stage=='discovery_assess':
            for item in result.sources:item.quote='A software development role.'
        if request.stage=='discovery_extract':
            for listing in result.listings:
                for item in listing.requirements:
                    item.quote={'SQL':'Applicants need SQL skills.', 'Python':'Python knowledge would be an advantage.',
                                'Build APIs':'Develop application interfaces.'}[item.name]
        return result
    flow[2].result_override=override
    row=wait(flow,start(flow))
    assert row['listings_analysed']==10 and len(flow[3].calls)==2
    stored=flow[1].research_contexts.find_one({'_id':row['id']})
    assert stored['listings'][0]['company'].startswith('Employer ')
    assert stored['listings'][0]['requirements'][0]['quote']=='Applicants need SQL skills.'


@pytest.mark.parametrize('replacement',['irrelevant','mixed','duplicate','empty','unavailable','schema','extraction'])
def test_replacement_shortfalls_keep_initial_usable_evidence(flow,replacement):
    replacement_provider(flow)
    original=flow[3].collect_discovery_query
    async def collect(context,query):
        if 'alternative employers' in query and replacement in ('duplicate','empty','unavailable'):
            flow[3].calls.append(query)
            if replacement=='unavailable':raise TimeoutError()
            if replacement=='empty':return []
            return [ResearchSource(source_id='duplicate',platform='employer',
                url='https://example.test/jobs/0',company='Employer 0',
                title='Employer 0 · Software Engineer',evidence='Previously retrieved vacancy.')]
        return await original(context,query)
    async def hook(request,data):
        if replacement=='schema' and request.stage=='discovery_assess' and any(
            int(item['title'].split()[1])>=10 for item in data['sources']):
            raise AIError('invalid_output',reason='schema_validation',fields=('sources',))
    def override(request,result):
        if request.stage=='discovery_assess':
            data=json.loads(request.context)
            for item in result.sources:
                number=int(data['sources'][item.ref]['title'].split()[1])
                if number==0 or replacement=='irrelevant' and number>=10 or replacement=='mixed' and number==10:
                    item.relevant=False
        if request.stage=='discovery_extract' and replacement=='extraction':
            data=json.loads(request.context)
            for item in result.listings:
                if int(data['sources'][item.ref]['title'].split()[1])>=10:item.relevant=False
        return result
    flow[3].collect_discovery_query=collect;flow[2].hook=hook;flow[2].result_override=override
    row=wait(flow,start(flow))
    expected={f'https://example.test/jobs/{i}' for i in range(1,10)}
    if replacement=='mixed':expected.update(f'https://example.test/jobs/{i}' for i in range(11,15))
    assert {item['url'] for item in row['sources']}==expected
    assert row['listings_analysed']==len(expected) and row['error_code'] is None
    assert row['review'] is not None and any('single replacement search' in v for v in row['warnings'])
    assert sum('alternative employers' in query for query in flow[3].calls)==1
    stored=flow[1].research_contexts.find_one({'_id':row['id']})
    assert stored['replacement_searches']==1
    # Original accepted sources are assessed/extracted once, including when the
    # replacement fails extraction after the original extractions completed.
    for stage in ('discovery_assess','discovery_extract'):
        originals=[s['title'] for request,data in flow[2].contexts if request.stage==stage
                   for s in data['sources'] if 1<=int(s['title'].split()[1])<=9]
        assert len(originals)==len(set(originals))


def test_no_relevant_evidence_after_one_replacement_still_fails(flow):
    replacement_provider(flow)
    def override(request,result):
        if request.stage=='discovery_assess':
            for item in result.sources:item.relevant=False
        return result
    flow[2].result_override=override
    row=wait(flow,start(flow),'failed')
    assert row['error_code']=='invalid_output' and row['review'] is None
    assert row['sources']==[] and len(flow[3].calls)==3


def test_finance_alone_asks_about_work_without_research_even_if_model_requests_it(flow):
    def override(request,result):
        if request.stage=='discovery_turn':
            result.scope=Scope(field='Finance',area='Finance')
            result.understanding=DiscoveryUnderstanding(field=DiscoveryAnswer(status='known',value='Finance',evidence='finance'))
        return result
    flow[2].result_override=override
    row=start(flow,'finance',profile=None)
    assert row['status']=='conversation' and row['decision']['action']=='ASK_CLARIFICATION'
    assert row['messages'][-1]['content'].count('?')==6
    assert 'specific role or kind of work' in row['decision']['reply']
    assert 'keep it broad' in row['decision']['reply']
    assert 'Let’s clarify' not in row['messages'][-1]['content']
    assert flow[2].calls==['discovery_turn'] and flow[3].calls==[]
    response=flow[0].post(f"{BASE}/{row['id']}/research",headers=headers(),json={
        'expected_version':row['version'],'scope':row['decision']['scope'],'confirmed':True})
    assert response.status_code==422 and flow[3].calls==[]


@pytest.mark.parametrize('missing',REQUIRED_FIELDS)
def test_every_readiness_field_must_be_addressed_before_research(flow,missing):
    def override(request,result):
        if request.stage=='discovery_turn':setattr(result.understanding,missing,DiscoveryAnswer())
        return result
    flow[2].result_override=override
    row=start(flow)
    assert row['status']=='conversation' and row['decision']['reply']
    assert flow[2].calls==['discovery_turn'] and flow[3].calls==[]


def test_blanket_unsure_fills_remaining_answers_then_starts_automatically(flow):
    def override(request,result):
        if request.stage!='discovery_turn':return result
        message=request.conversation[-1].content
        result.understanding=DiscoveryUnderstanding(field=DiscoveryAnswer(
            status='known',value='Software Engineering',evidence='Software Engineering'))
        if message=='Unsure about everything else':
            for name in DiscoveryUnderstanding.model_fields:
                if name!='field':setattr(result.understanding,name,DiscoveryAnswer(status='unsure',evidence=message))
        return result
    flow[2].result_override=override
    row=start(flow,'Software Engineering',profile=None)
    assert row['status']=='conversation' and flow[3].calls==[]
    row=send(flow,row,'Unsure about everything else')
    assert row['status']=='researching' and row['scope']['career_stage']=='unspecified'
    assert row['scope']['location'] is None
    assert wait(flow,row)['status']=='review'
    assert flow[2].calls.count('discovery_turn')==2


def test_missing_answers_cannot_be_filled_with_invented_or_assistant_evidence(flow):
    def override(request,result):
        if request.stage=='discovery_turn':
            result.understanding=complete_understanding()
            for name in DiscoveryUnderstanding.model_fields:
                setattr(result.understanding,name,DiscoveryAnswer(status='unsure',evidence='Software Engineering'))
            result.understanding.field=DiscoveryAnswer(status='known',value='Software Engineering',evidence='Software Engineering')
        return result
    flow[2].result_override=override
    row=start(flow,'Software Engineering',profile=None)
    assert row['status']=='conversation' and flow[3].calls==[]
    assert row['decision']['understanding']['career_stage']['status']=='unanswered'


def test_material_skill_ambiguity_blocks_until_addressed_or_broad_scope_is_explicit(flow):
    def override(request,result):
        if request.stage=='discovery_turn':
            result.understanding.skill_ambiguity=DiscoveryAnswer(status='known',value='material',evidence=PROFILE)
            if request.conversation[-1].content=='Compare the broad options':
                result.understanding.role_family_or_work=DiscoveryAnswer(status='known',value='keep it broad',evidence='Compare the broad options')
        return result
    flow[2].result_override=override
    row=start(flow)
    assert row['status']=='conversation' and flow[3].calls==[]
    row=send(flow,row,'Compare the broad options')
    assert row['status']=='researching' and wait(flow,row)['status']=='review'


def test_readiness_answers_survive_context_window_and_new_field_invalidates_old_direction(flow):
    row=wait(flow,start(flow));calls=len(flow[3].calls)
    def override(request,result):
        if request.stage=='discovery_turn':
            result.scope=Scope(field='Finance',area='Finance')
            result.understanding.field=DiscoveryAnswer(status='known',value='Finance',evidence='Switch to Finance')
        return result
    flow[2].result_override=override
    row=send(flow,row,'Switch to Finance')
    assert row['status']=='conversation' and row['review'] is None and row['sources']==[]
    assert row['scope']['field']=='Finance' and len(flow[3].calls)==calls
    assert row['decision']['understanding']['role_family_or_work']['status']=='unanswered'
    assert row['decision']['understanding']['career_stage']['status']=='known'


def test_incomplete_new_field_retires_active_research_without_publishing_old_results(flow):
    import threading
    entered=threading.Event();release=threading.Event()
    original=flow[3].collect_discovery_query
    async def collect(context,query):
        entered.set()
        while not release.is_set():await asyncio.sleep(.01)
        return await original(context,query)
    def override(request,result):
        if request.stage=='discovery_turn' and request.conversation[-1].content=='Switch to Finance':
            result.scope=Scope(field='Finance',area='Finance')
            result.understanding.field=DiscoveryAnswer(status='known',value='Finance',evidence='Switch to Finance')
        return result
    flow[3].collect_discovery_query=collect;flow[2].result_override=override
    row=start(flow);assert entered.wait(2)
    try:
        changed=send(flow,row,'Switch to Finance')
        assert changed['status']=='conversation' and changed['scope']['field']=='Finance'
    finally:release.set()
    deadline=time.monotonic()+2
    while flow[0].app.state.discovery.tasks and time.monotonic()<deadline:time.sleep(.01)
    assert not flow[0].app.state.discovery.tasks
    current=flow[0].get(f"{BASE}/{row['id']}",headers=headers()).json()['session']
    assert current['status']=='conversation' and current['review'] is None and current['sources']==[]
    assert 'discovery_summary' not in flow[2].calls


def test_only_unanswered_bundle_topics_are_reasked_and_broad_role_starts_research(flow):
    def override(request,result):
        if request.stage!='discovery_turn':return result
        if request.conversation[-1].content=='Keep it broad':
            result.understanding.role_family_or_work=DiscoveryAnswer(status='known',value='keep it broad',evidence='Keep it broad')
        else:result.understanding.role_family_or_work=DiscoveryAnswer()
        return result
    flow[2].result_override=override
    row=start(flow)
    message=row['messages'][-1]['content']
    assert message.startswith('1. ') and message.count('?')==1
    assert message.endswith('You can keep it broad.') and 'unsure' not in message.lower()
    assert row['status']=='conversation' and flow[3].calls==[]
    row=send(flow,row,'Keep it broad')
    assert row['status']=='researching' and wait(flow,row)['status']=='review'
    assert 'broad_exploration' not in row['decision']['understanding']
    assert 'industry' not in row['decision']['understanding']


def test_other_interests_personalise_synthesis_without_researching_unrelated_hobbies(flow):
    row=wait(flow,start(flow));searches=len(flow[3].calls)
    def override(request,result):
        if request.stage=='discovery_turn':
            result.action='ANSWER'
            result.understanding.other_interests=DiscoveryAnswer(status='known',value='photography',evidence='I also enjoy photography')
        return result
    flow[2].result_override=override
    row=wait(flow,send(flow,row,'I also enjoy photography'))
    assert len(flow[3].calls)==searches
    context=[data for request,data in flow[2].contexts if request.stage=='discovery_summary'][-1]
    assert context['understanding']['other_interests']['value']=='photography'
