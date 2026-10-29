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
from app.schemas.discovery import Scope,Decision,Plan,Listings,MarketSummary,Listing,Requirement,RecommendedSkill,ConversationMemory
from app.schemas.analysis import Generation,ResearchSource,CareerGoal
from app.repositories.goals import now,GoalStore
from app.workflows.discovery import aggregate,validated_listings

OWNER='11111111-1111-4111-8111-111111111111'
BASE='/api/v1/career/discoveries'
def headers(other=False,key=None):return {'Authorization':'Bearer '+('other' if other else 'owner'),'Idempotency-Key':key or str(uuid4())}
SCOPE=Scope(field='Software Engineering',area='Software Engineering',career_stage='entry_level',location='Singapore')

class AI:
    settings=SimpleNamespace(enabled=True,model='synthetic')
    def __init__(self):self.calls=[];self.contexts=[];self.quota_at=None;self.empty=False;self.fail=False;self.question=False;self.hook=None;self.result_override=None
    async def generate(self,request,operation,**kwargs):
        self.calls.append(request.stage);data=json.loads(request.context);self.contexts.append((request,data))
        if self.hook:await self.hook(request,data)
        if self.fail:raise AIError('invalid_output')
        if request.stage=='discovery_turn':
            message=request.conversation[-1].content
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
                reply='Let’s explore your career direction.',memory=memory,recommendations=[],
                excluded_skills=[message.removeprefix('Remove ')] if message.startswith('Remove ') else previous.get('excluded_skills',[]),
                requested_skills=[message.removeprefix('Add ')] if message.startswith('Add ') else previous.get('requested_skills',[]))
        elif request.stage=='discovery_plan':result=Plan(related_roles=['Software Engineer','Backend Engineer'],queries=['graduate software jobs','graduate backend jobs'])
        elif request.stage=='discovery_extract':
            count=self.calls.count('discovery_extract')
            if count==self.quota_at:raise AIError('rate_limited',limit_scope='user',retry_after=1,provider='gemini')
            result=Listings(listings=[] if self.empty else [Listing(ref=i,company=s['title'].split(' · ')[0],job_title='Software Engineer',location='Singapore',career_stage='entry_level',relevant=True,requirements=[Requirement(kind='skill',name='SQL',quote='SQL is required.'),Requirement(kind='skill',name='Python',quote='Python preferred.',preferred=True),Requirement(kind='responsibility',name='Build APIs',quote='Build APIs.')]) for i,s in enumerate(data['sources'])])
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
    assert row['status']=='conversation' and row['decision']['question']
    assert not flow[3].calls


def test_unknown_stage_and_location_do_not_block_research(flow):
    row=start(flow,'Broad direction')
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
    flow[3].empty=True;row=start(flow);row=wait(flow,row)
    assert row['coverage']=='insufficient' and row['listings_analysed']==0 and row['review']['current']['goal']['skills']==[]
    assert 'discovery_extract' not in flow[2].calls and row['warnings']


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
    entered=threading.Event();release=threading.Event();original=flow[3].collect_opportunity_query
    async def slow(context,query):
        if context.role=='Software Engineering':
            entered.set()
            while not release.is_set():await asyncio.sleep(.01)
        return await original(context,query)
    flow[3].collect_opportunity_query=slow
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
    for name in ('Decision','DiscoverySession','ConversationMemory','ChatMessage','MarketSummary','RecommendedSkill'):
        assert saved['components']['schemas'][name]==current['components']['schemas'][name]


def test_transcript_capacity_prevents_unbounded_session_growth():
    from app.workflows.discovery import check_conversation_capacity
    from app.repositories.goals import GoalError
    with pytest.raises(GoalError):check_conversation_capacity({'messages':[{'role':'user','content':'x'}]*996})
    with pytest.raises(GoalError):check_conversation_capacity({'messages':[{'role':'assistant','content':'界'*12000}]*100})
