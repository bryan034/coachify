from tests.api_views import saved_research,goal_content
"""One live goal, automatic snapshots, real LangGraph/MongoDB and fake APIs."""
import asyncio
import json
import os
import time
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.main import create_app
from app.ai.adapter import AIError
from app.repositories.goals import now
from app.schemas.analysis import Generation,ResearchSource
from app.schemas.jd import JDExtraction,JDReply
from app.schemas.research import SourcedTopics
OWNER='11111111-1111-4111-8111-111111111111';OTHER='22222222-2222-4222-8222-222222222222'
BASE='/api/v1/career/workspace'
TEXT='A technical interview includes SQL exercise and joins.'

def headers(key=None,other=False):return {'Authorization':'Bearer '+('other' if other else 'owner'),'Idempotency-Key':key or str(uuid4())}
class AI:
    settings=SimpleNamespace(enabled=True)
    def __init__(self):self.calls=[];self.fail=False;self.quota=False
    async def generate(self,request,operation,**kwargs):
        self.calls.append(request)
        if self.fail:raise AIError('invalid_output',True)
        if request.stage=='jd_scope':
            from app.ai.jd_scope import JobIdentity
            output=JobIdentity(is_job_description=True,evidence=[request.source_text[:200]])
        elif request.stage=='jd_extraction':
            role='Second Analyst' if 'Second' in request.source_text else 'Data Analyst'
            output=JDExtraction(role=role,field='Data',company=None,summary='Interpret data for decisions.',skills=[{'name':'SQL','category':'Technical','priority':'required','origin':'employer','evidence':'SQL is required.'}])
        elif request.stage=='interview_synthesis':
            if self.quota:self.quota=False;raise AIError('rate_limited',True,limit_scope='provider',retry_after=1)
            output=SourcedTopics(topics=[{'name':'SQL','category':'Technical','interview_stage':'technical interview','assessment_type':'SQL exercise','source_ids':[request.sources[0].source_id],'quotes':[TEXT]}])
        elif request.stage=='focused_answer':
            from app.ai.qa_contracts import FocusedAnswer
            context=json.loads(request.context)
            assert context['facts'] and 'interview_research' not in context
            output=FocusedAnswer(reply='Practise SQL joins for the reported technical interview.',references=[f['ref'] for f in context['facts']])
        elif request.stage=='question_route':
            from app.ai.qa_contracts import QuestionRoute
            output=QuestionRoute(topic='skills',terms=['SQL'])
        elif request.stage=='goal_edit':
            from app.ai.goal_edit_contracts import GoalEditDecision
            output=GoalEditDecision(status='ready',reply='Added Python to your goal.',intent='Add Python',changes=[
                {'collection':'skills','action':'add','reference':'new1','field':'name','value':'Python'},
                {'collection':'skills','action':'add','reference':'new1','field':'category','value':'Technical'}])
        elif request.stage in ('jd_chat','workspace_chat'):
            context=json.loads(request.context)
            assert context['career_goal']['skills']
            output=JDReply(reply='Practise SQL joins for the reported technical interview.',proposed_skills=None)
        else:
            output=JDExtraction(role='Data Analyst',field='Data',company=None,skills=[{'name':'SQL','category':'Technical','priority':'suggested','origin':'generated_guidance'}])
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return SimpleNamespace(data=output,generation=Generation(provider='fixture',model='fixture',prompt_version='test',generated_at=now()))
class Sources:
    def __init__(self):self.calls=[];self.block=False;self.empty=False
    async def collect_platform(self,context,platform,round=0):
        self.calls.append((context,platform,round))
        if self.block:raise TimeoutError()
        if self.empty:return []
        return [ResearchSource(source_id=platform+'-1',platform='other',url='https://example.test/'+platform,evidence=TEXT,reliability='unverified')]
@pytest.fixture
def flow():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000);db=mongo['elo_workspace_test_'+uuid4().hex];ai=AI();sources=Sources()
    def profile(req):return httpx.Response(200,json={'id':OTHER if req.headers.get('Authorization')=='Bearer other' else OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    try:
        with TestClient(create_app(database=db,ai=ai,research_client=sources,profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as client:
            yield client,db,ai,sources
    finally:mongo.drop_database(db.name);mongo.close()
def ingest(flow,text='SQL is required.',key=None):return flow[0].post(BASE+'/jd',headers=headers(key),json={'text':text})
def wait(flow,phase='ready'):
    for _ in range(180):
        value=flow[0].get(BASE,headers=headers()).json()
        if value['phase']==phase:return value
        time.sleep(.03)
    pytest.fail('Workflow did not reach '+phase+': '+str(value))


def test_async_duplicate_jd_with_new_key_reconnects_instead_of_conflicting(flow):
    client,db,ai,_=flow;original=ai.generate;blocked=True
    async def generate(request,operation,**kwargs):
        if request.stage=='jd_extraction':
            while blocked:await asyncio.sleep(.01)
        return await original(request,operation,**kwargs)
    ai.generate=generate
    body={'text':'SQL is required.'}
    first=client.post(BASE+'/jd',headers={**headers(),'Prefer':'respond-async'},json=body)
    assert first.status_code==202
    again=client.post(BASE+'/jd',headers={**headers(),'Prefer':'respond-async'},json=body)
    assert again.status_code==202 and again.json()['operation_id']==first.json()['operation_id']
    conflict=client.post(BASE+'/jd',headers={**headers(),'Prefer':'respond-async'},json={'text':'A different role. SQL is required.'})
    assert conflict.status_code==409 and conflict.json()['code']=='operation_in_progress'
    assert client.get(BASE+'/operations/'+first.json()['operation_id'],headers=headers(other=True)).status_code==404
    blocked=False
    for _ in range(100):
        result=client.get(BASE+'/operations/'+first.json()['operation_id'],headers=headers()).json()
        if result.get('status')=='succeeded':break
        time.sleep(.02)
    assert result['status']=='succeeded'
    assert len([call for call in ai.calls if call.stage=='jd_extraction'])==1

def test_jd_graph_autosaves_current_goal_and_gates_chat_on_both_inputs(flow):
    client,db,ai,sources=flow;key=str(uuid4());response=ingest(flow,key=key)
    assert response.status_code==202,response.text
    initial=response.json();assert initial['current']['goal']['skills'][0]['name']=='SQL'
    current=wait(flow);assert saved_research(flow,current)['skills'][0]['assessment_type']=='SQL exercise'
    assert {v[1] for v in sources.calls}=={'brave'}
    answer=client.post(BASE+'/messages',headers=headers(),json={'session_id':current['session_id'],'expected_version':current['revision'],'message':'What should I practise?'})
    assert answer.status_code==200,answer.text
    assert ingest(flow,key=key).json()['session_id']==current['session_id']
    assert len([r for r in ai.calls if r.stage=='jd_extraction'])==1
    assert db.career_checkpoints.count_documents({})>0
    # Raw source and private transcript never enter checkpoint documents/writes.
    raw=str(list(db.career_checkpoints.find({})))+str(list(db.career_checkpoint_writes.find({})))
    assert 'SQL is required.' not in raw and 'What should I practise?' not in raw
    assert client.get(BASE,headers=headers(other=True)).json()['session_id'] is None
    assert client.post(BASE+'/messages',headers=headers(other=True),json={'session_id':current['session_id'],'expected_version':1,'message':'Hi'}).status_code==409


def test_edit_is_current_without_confirmation_and_new_jd_replaces_the_session(flow):
    client,db,ai,sources=flow;ingest(flow);first=wait(flow);content=goal_content(first['current']['goal']);content['summary']='Updated role interpretation.'
    saved=client.patch(BASE+'/review',headers=headers(),json={'session_id':first['session_id'],'expected_version':first['revision'],'content':content})
    assert saved.status_code==200,saved.text
    second=wait(flow);assert second['current']['goal']['summary']=='Updated role interpretation.'
    assert second['session_id']==first['session_id'] and second['revision']>first['revision']
    assert ingest(flow,'Second role. SQL is required.').status_code==202
    replaced=wait(flow);assert replaced['session_id']!=first['session_id'] and replaced['current']['goal']['role']=='Second Analyst'
    stale=client.post(BASE+'/messages',headers=headers(),json={'session_id':first['session_id'],'expected_version':first['revision'],'message':'Old session'})
    assert stale.status_code==409
    active=client.get('/api/v1/career/goals/current',headers=headers()).json()
    assert active['goal']['_id']==replaced['current']['goal']['_id']


def test_failed_research_preserves_latest_goal_and_keeps_saved_goal_chat_available(flow):
    client,db,ai,sources=flow;sources.block=True;ingest(flow);value=wait(flow,'research_failed')
    assert value['current']['goal']['skills'] and value['research_id'] is None
    assert client.post(BASE+'/messages',headers=headers(),json={'session_id':value['session_id'],'expected_version':value['revision'],'message':'Explain'}).status_code==200
    sources.block=False;assert client.post(BASE+'/retry',headers=headers()).status_code==202
    assert wait(flow)['research_id']


def test_quota_pause_resumes_failed_node_without_repeating_search(flow):
    client,db,ai,sources=flow;ai.quota=True;ingest(flow);pending=wait(flow,'waiting_quota')
    assert pending['retry_after']==1
    ready=wait(flow);assert saved_research(flow,ready) and len(sources.calls)==2


def test_empty_research_is_explicit_and_checkpoint_expiry_keeps_saved_goal(flow):
    client,db,ai,sources=flow;sources.empty=True;ingest(flow);value=wait(flow)
    assert saved_research(flow,value)['research_status']=='no_findings'
    assert len(sources.calls)==2 # Brave only, at most one extra query round
    assert not any(r.stage=='interview_synthesis' for r in ai.calls)
    db.career_state.update_one({'_id':OWNER},{'$set':{'workspace.expires_at':now()-timedelta(seconds=1)}})
    expired=client.get(BASE,headers=headers()).json();assert expired['phase']=='expired' and expired['current']['goal']
    assert client.post(BASE+'/retry',headers=headers()).status_code==202
    assert wait(flow)['current']['goal']['_id']==value['current']['goal']['_id']


def test_invalid_replacement_retains_prior_career_goal(flow):
    client,db,ai,sources=flow;ingest(flow);old=wait(flow);ai.fail=True
    assert ingest(flow,'Second JD').status_code==503
    assert client.get(BASE,headers=headers()).json()['session_id']==old['session_id']


def test_stale_review_edit_and_lost_success_retry_cannot_replace_new_goal(flow):
    client,db,ai,sources=flow;ingest(flow);first=wait(flow);key=headers()
    body={'session_id':first['session_id'],'expected_version':first['revision'],'content':goal_content(first['current']['goal'])}
    body['content']['summary']='Saved exactly once.'
    saved=client.patch(BASE+'/review',headers=key,json=body);assert saved.status_code==200
    assert client.patch(BASE+'/review',headers=key,json=body).json()['revision']==saved.json()['revision']
    ingest(flow,'Second role, SQL required');second=wait(flow)
    assert client.patch(BASE+'/review',headers=headers(),json=body).status_code==409
    assert client.get(BASE,headers=headers()).json()['session_id']==second['session_id']


def test_process_restart_resumes_checkpoint_without_repeating_api_searches(flow):
    client,db,ai,sources=flow;ai.quota=True;ingest(flow);wait(flow,'waiting_quota')
    client.portal.call(client.app.state.workflow.close)
    def profile(req):return httpx.Response(200,json={'id':OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    with TestClient(create_app(database=db,ai=ai,research_client=sources,profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as resumed:
        assert wait((resumed,db,ai,sources))['phase']=='ready'
    assert len(sources.calls)==2


def test_edit_during_quota_pause_releases_old_research_lease(flow):
    client,db,ai,sources=flow;ai.quota=True;ingest(flow);value=wait(flow,'waiting_quota')
    content=goal_content(value['current']['goal']);content['summary']='Latest role summary.'
    changed=client.patch(BASE+'/review',headers=headers(),json={'session_id':value['session_id'],'expected_version':value['revision'],'content':content})
    assert changed.status_code==200,changed.text
    latest=wait(flow)
    assert latest['current']['goal']['summary']=='Latest role summary.'
    assert latest['revision']>value['revision']


def test_pending_context_is_still_the_latest_goal_and_invalid_scope_never_half_saves(flow):
    client,db,ai,sources=flow;ingest(flow);value=wait(flow)
    content=goal_content(value['current']['goal']);content['role']='Business Analyst'
    response=client.patch(BASE+'/review',headers=headers(),json={'session_id':value['session_id'],'expected_version':value['revision'],'content':content})
    assert response.status_code==200,response.text
    latest=response.json();assert latest['current']['goal']['role']=='Business Analyst'
    assert latest['current']['goal']['requirements_need_review'] and latest['current']['goal']['readiness']=='pending'
    content=goal_content(latest['current']['goal']);content['role']=None
    invalid=client.patch(BASE+'/review',headers=headers(),json={'session_id':value['session_id'],'expected_version':latest['revision'],'content':content})
    assert invalid.status_code==422
    current=client.get(BASE,headers=headers()).json()
    assert current['current']['goal']['version']==current['revision']==latest['revision']


def test_brave_summary_survives_graph_storage_and_cross_user_cache_reuse(flow):
    from app.schemas.analysis import BraveAnswer,AnswerClaim
    from app.schemas.research import ResearchBatch
    client,db,ai,sources=flow
    text='Candidates report a technical screen and SQL assessment.'
    summary=BraveAnswer(summary_id='answer1',text=text,source_ids=['s1'],claims=[AnswerClaim(text=text,source_ids=['s1'])])
    async def collect(context,platform,round=0):
        sources.calls.append((context,platform,round))
        return ResearchBatch(sources=[ResearchSource(source_id='s1',platform='other',url='https://example.test/public',evidence='Candidate SQL exercise report.')],summaries=[summary])
    sources.collect_platform=collect
    original=ai.generate
    async def generate(request,operation,**kwargs):
        if request.stage!='interview_synthesis':return await original(request,operation,**kwargs)
        ai.calls.append(request);assert request.summaries[0].text==text
        return SimpleNamespace(data=SourcedTopics(topics=[{'name':'SQL','category':'Technical','interview_stage':'technical screen','assessment_type':'SQL assessment',
            'source_ids':['s1'],'quotes':[text],'evidence_origin':'brave_summary','summary_id':'answer1'}]),generation=Generation(provider='fixture',model='fixture',prompt_version='test',generated_at=now()))
    ai.generate=generate
    ingest(flow);value=wait(flow)
    assert saved_research(flow,value)['summaries'][0]['text']==text and saved_research(flow,value)['skills'][0]['evidence_origin']=='brave_summary'
    assert saved_research(flow,value)['skills'][0]['interview_stage']=='technical screen'
    assert saved_research(flow,value)['sources'][0]['evidence']!=text
    assert len(sources.calls)==1  # A supported answer does not need another broad search.
    assert client.post(BASE+'/jd',headers=headers(other=True),json={'text':'SQL is required.'}).status_code==202
    for _ in range(100):
        other=client.get(BASE,headers=headers(other=True)).json()
        if other['phase']=='ready':break
        time.sleep(.03)
    assert other['phase']=='ready' and other['research_id']==value['research_id']
    assert len(sources.calls)==1


def test_context_access_failure_preserves_goal_and_explains_the_required_access(flow):
    from app.repositories.goals import GoalError
    client,db,ai,sources=flow
    async def collect(*args,**kwargs):raise GoalError('Brave LLM Context API credentials or access need checking.',503)
    sources.collect_platform=collect
    ingest(flow);value=wait(flow,'research_failed')
    assert value['current']['goal']['skills']
    assert 'LLM Context API credentials' in value['error'] and value['research_id'] is None


@pytest.mark.parametrize('failure,expected',[
    ('http','Brave API rate limit reached (HTTP 429). Wait before retrying interview research.'),
    ('timeout','Public research timed out.'),
    ('validation','The search provider returned research data that could not be validated.')])
def test_research_failure_category_survives_workflow_without_exposing_details(flow,failure,expected):
    from app.repositories.goals import GoalError
    client,db,ai,sources=flow
    async def collect(*args,**kwargs):
        if failure=='http':raise GoalError(expected,503)
        if failure=='timeout':raise TimeoutError('PRIVATE timeout details')
        raise ValueError('PRIVATE invalid data')
    sources.collect_platform=collect
    ingest(flow);value=wait(flow,'research_failed')
    assert expected in value['error'] and 'PRIVATE' not in value['error']
    assert value['current']['goal']['skills']


def test_background_failure_code_is_available_in_workspace_response(flow):
    client,db,ai,sources=flow;sources.block=True
    ingest(flow);value=wait(flow,'research_failed')
    assert value['error_code']=='research_unavailable' and value['error']


def test_background_quota_code_is_available_for_ui_classification(flow):
    client,db,ai,sources=flow;ai.quota=True
    ingest(flow);value=wait(flow,'waiting_quota')
    assert value['error_code']=='rate_limited' and value['retry_after']==1
    assert wait(flow)['error_code'] is None



def test_async_jd_wait_resumes_the_same_graph_call_and_receipt(flow):
    from app.ai.adapter import AIAdapter
    from app.ai.config import AISettings
    client,db,fixture_ai,sources=flow
    calls=[]
    def provider(request):
        calls.append(request.content)
        if len(calls)==1:return httpx.Response(429,headers={'Retry-After':'1'})
        output={'role':'Data Analyst','field':'Data','company':None,'skills':[]}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
    transport=httpx.AsyncClient(transport=httpx.MockTransport(provider))
    try:
        adapter=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),transport)
        # Only extraction uses the real adapter; research keeps deterministic fixtures.
        async def generate(request,operation,**kwargs):
            return await (adapter if request.stage=='jd_extraction' else fixture_ai).generate(request,operation,**kwargs)
        client.app.state.ai=SimpleNamespace(generate=generate,settings=fixture_ai.settings)
        key=str(uuid4());h={**headers(key),'Prefer':'respond-async'}
        response=client.post(BASE+'/jd',headers=h,json={'text':'Data Analyst at a software firm.'})
        assert response.status_code==202,response.text
        id=response.json()['operation_id'];path=BASE+'/operations/'+id
        assert client.get(path,headers=headers(other=True)).status_code==404
        assert client.post(BASE+'/jd',headers=h,json={'text':'Data Analyst at a software firm.'}).json()['operation_id']==id
        for _ in range(100):
            pending=client.get(path,headers=headers()).json()
            if pending['status']=='waiting_quota':break
            time.sleep(.01)
        assert pending['status']=='waiting_quota' and pending['retry_after']<=1
        assert db.career_goals.count_documents({})==0
        for _ in range(150):
            result=client.get(path,headers=headers()).json()
            if result['status']=='succeeded':break
            time.sleep(.02)
        assert result['status']=='succeeded',result
        assert result['result']['current']['goal']['role']=='Data Analyst'
        assert len(calls)==2 and calls[0]==calls[1]
        assert wait(flow)['current']['goal']['role']=='Data Analyst'
        assert 'Data Analyst at a software firm.' not in str(list(db.career_checkpoints.find({})))

    finally: client.portal.call(transport.aclose)



def test_async_jd_repairs_missing_fields_without_publishing_bad_data(flow):
    from app.ai.adapter import AIAdapter
    from app.ai.config import AISettings
    client,db,fixture_ai,sources=flow
    calls=[];release=asyncio.Event()
    async def provider(request):
        calls.append(json.loads(request.content))
        if len(calls)==1:output={'role':'PRIVATE_FAILED_VALUE','field':'Data','skills':[]}
        else:
            await release.wait()
            output={'role':'Analyst','field':'Data','company':None,'skills':[]}
        return httpx.Response(200,json={'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
    transport=httpx.AsyncClient(transport=httpx.MockTransport(provider))
    try:
        adapter=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),transport)
        async def generate(request,operation,**kwargs):
            return await (adapter if request.stage=='jd_extraction' else fixture_ai).generate(request,operation,**kwargs)
        client.app.state.ai=SimpleNamespace(generate=generate,settings=fixture_ai.settings)
        response=client.post(BASE+'/jd',headers={**headers(),'Prefer':'respond-async'},json={'text':'Synthetic analyst role.'})
        path=BASE+'/operations/'+response.json()['operation_id']
        for _ in range(100):
            pending=client.get(path,headers=headers()).json()
            if pending['status']=='repairing':break
            time.sleep(.01)
        assert pending['status']=='repairing',pending
        assert pending['validation_feedback']['violations']==[{'field':'company','issue':'missing'}]
        assert db.career_goals.count_documents({})==0
        assert 'PRIVATE_FAILED_VALUE' not in json.dumps(pending)
        client.portal.call(release.set)
        for _ in range(100):
            done=client.get(path,headers=headers()).json()
            if done['status']=='succeeded':break
            time.sleep(.02)
        assert done['status']=='succeeded' and done['validation_feedback'] is None
        assert done['result']['current']['goal']['role']=='Analyst'
        assert len(calls)==2 and 'company' in calls[1]['messages'][0]['content']
        assert wait(flow)['phase']=='ready'
    finally:
        client.portal.call(release.set);client.portal.call(transport.aclose)


def test_interview_synthesis_repairs_repeatedly_without_repeating_search(flow):
    client,db,ai,sources=flow;generate=ai.generate;failures=[2]
    async def recover(request,operation,**kwargs):
        if request.stage=='interview_synthesis' and failures[0]:
            failures[0]-=1;ai.calls.append(request)
            raise AIError('invalid_output',True,reason='schema_validation',fields=('topics',),
                violations=[{'field':'topics','issue':'missing'}])
        return await generate(request,operation,**kwargs)
    client.app.state.ai=SimpleNamespace(generate=recover,settings=ai.settings)
    ingest(flow);done=wait(flow)
    assert saved_research(flow,done) and done['error'] is None
    assert len([r for r in ai.calls if r.stage=='interview_synthesis'])==3
    assert len(sources.calls)==2
