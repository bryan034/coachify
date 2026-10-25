"""J08/J09 real MongoDB + fake external boundaries; no live provider calls."""
import asyncio
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.main import create_app
from app.schemas.analysis import CvSnapshot, Generation
from app.schemas.goals import ExplorationOutput
from app.repositories.goals import GoalError

OWNER='11111111-1111-4111-8111-111111111111'
OTHER='22222222-2222-4222-8222-222222222222'
BASE='/api/v1/career'


class FakeAI:
    settings=SimpleNamespace(enabled=True)
    def __init__(self): self.inputs=[]; self.fail=False; self.hook=None
    async def generate(self, data, operation, **kwargs):
        self.inputs.append(data)
        if self.hook: self.hook()
        if self.fail:
            from app.ai.adapter import AIError
            raise AIError('unavailable',True)
        memory=json.loads(data.context)
        missing=memory['unresolved_topics']
        question=memory['current_focus']
        updates=[]
        if not memory['explicit_skip'] and question:
            quote=data.conversation[-1].content
            updates=[{'topic':question,'status':'answered','value':quote,'quote':quote}]
            missing=[topic for topic in missing if topic!=question]
        return SimpleNamespace(data=ExplorationOutput(reply='Thanks. We can explore analytical work.',
            follow_up='Can you tell me more about '+missing[0]+'?' if missing else 'Which direction feels closest?',
            focus=missing[0] if missing else None,context_updates=updates,
            interests=['data'],preferences=['Singapore'],suggestions=[{'role':'Data analyst','field':'Analytics',
                'rationale':'You enjoy analytical work.','uncertainty':'Current proficiency is self-reported or unknown.'}]),
            generation=Generation(provider='fixture',model='fixture-model',prompt_version='exploration-test',generated_at=datetime.now(timezone.utc)))



class FakeCV:
    def __init__(self): self.rows=[]
    async def list(self, token): return self.rows
    async def get(self, identifier, token, owner):
        found=next((r for r in self.rows if r.id==identifier and r.user_id==owner and r.extraction_status=='succeeded'),None)
        if not found: raise GoalError('CV unavailable.',409)
        return found


@pytest.fixture
def flow():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri: pytest.skip('Set MONGODB_TEST_URI for disposable MongoDB flow tests.')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000); name='coachify_goals_test_'+uuid4().hex
    def profile(req):
        owner=OTHER if req.headers.get('Authorization')=='Bearer other' else OWNER
        return httpx.Response(200,json={'id':owner,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    ai=FakeAI(); cv=FakeCV()
    upstream=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile))
    try:
        with TestClient(create_app(profile_client=upstream,database=mongo[name],ai=ai,cv_client=cv)) as client:
            yield client,mongo[name],ai,cv
    finally: mongo.drop_database(name);mongo.close()


def headers(key=None,owner='owner'):
    return {'Authorization':'Bearer '+owner,'Idempotency-Key':key or str(uuid4())}


def start(client,**kwargs):
    response=client.post(BASE+'/explorations',json={'consent':True,**kwargs},headers=headers())
    assert response.status_code==200,response.text
    return response.json()


def turn(client,draft,**kwargs):
    return client.post(BASE+'/explorations/'+draft['_id']+'/messages',json={'expected_version':draft['version'],'answer':'I built a small project.',**kwargs},headers=headers())


def complete(client):
    draft=start(client)
    for _ in range(6):
        response=turn(client,draft); assert response.status_code==200,response.text
        draft=response.json()
    return draft


def confirm_body(draft=None,**kwargs):
    return {'target_type':'career_exploration' if draft else 'specific_job','role':'Data analyst','field':'Analytics',
        'expected_selection_version':0, **({'draft_id':draft['_id'],'expected_draft_version':draft['version']} if draft else {}),**kwargs}


def test_no_cv_questions_resume_and_explicit_confirmation(flow):
    client,db,ai,cv=flow
    draft=start(client)
    assert draft['cv']['mode']=='none' and draft['next_question']=='aspirations'
    first=turn(client,draft).json()
    assert not first['suggestions'] # AI cannot bypass backend completeness.
    assert client.get(BASE+'/explorations/'+first['_id'],headers=headers()).json()['answers']==first['answers']
    for _ in range(5): first=turn(client,first).json()
    assert first['context_complete'] and first['suggestions'][0]['role']=='Data analyst'
    assert client.get(BASE+'/goals/current',headers=headers()).json()['goal'] is None
    response=client.post(BASE+'/goals/confirm',json=confirm_body(first),headers=headers())
    assert response.status_code==200,response.text
    saved=response.json()
    assert saved['goal']['company'] is None and saved['goal']['readiness']=='pending'
    assert saved['goal']['skills']==[] and saved['selection_version']==1
    assert db.cvs.count_documents({})==0
    record=db.career_goals.find_one({'record_type':'exploration_draft'})
    assert 'attachment_text' not in record and len(record['turns'])==6


def test_skip_unknown_idempotency_conflict_and_failure_preserve_progress(flow):
    client,db,ai,cv=flow; draft=start(client); key=str(uuid4())
    body={'expected_version':1,'skip':True,'answer':None}
    path=BASE+'/explorations/'+draft['_id']+'/messages'
    one=client.post(path,json=body,headers=headers(key));two=client.post(path,json=body,headers=headers(key))
    assert one.json()==two.json() and len(ai.inputs)==1
    assert one.json()['answers']['aspirations']['status']=='skipped' and one.json()['answers']['aspirations']['value'] is None
    assert client.post(path,json={**body,'answer':'different','skip':False},headers=headers(key)).status_code==409
    assert turn(client,draft).status_code==409
    ai.fail=True
    assert turn(client,one.json()).status_code==503
    assert client.get(BASE+'/explorations/'+draft['_id'],headers=headers()).json()['version']==2
    assert 'processing' not in db.career_goals.find_one({'record_type':'exploration_draft'})


def test_owner_isolation_and_client_cannot_assign_skills(flow):
    client,db,ai,cv=flow; draft=start(client)
    assert client.get(BASE+'/explorations/'+draft['_id'],headers=headers(owner='other')).status_code==404
    assert client.post(BASE+'/explorations',json={'consent':True,'user_id':OTHER},headers=headers()).status_code==422
    assert client.post(BASE+'/goals/confirm',json={**confirm_body(),'skills':[{'name':'fake'}]},headers=headers()).status_code==422
    assert client.get(BASE+'/goals',headers=headers(owner='other')).json()=={'goals':[],'explorations':[]}
    assert client.post(BASE+'/explorations',json={'consent':True}).status_code==401


def test_confirm_retries_replacement_cancel_noop_and_stale_draft(flow):
    client,db,ai,cv=flow; draft=complete(client); body=confirm_body(draft); key=str(uuid4())
    a=client.post(BASE+'/goals/confirm',json=body,headers=headers(key)).json()
    b=client.post(BASE+'/goals/confirm',json=body,headers=headers(key)).json()
    assert a==b and db.career_goals.count_documents({'record_type':{'$ne':'exploration_draft'}})==1
    # Same actual goal is a no-op, with no replacement needed.
    noop_key=str(uuid4())
    assert client.post(BASE+'/goals/confirm',json={**body,'expected_selection_version':1},headers=headers(noop_key)).json()['selection_version']==1
    assert client.post(BASE+'/goals/confirm',json={**body,'role':'Different','expected_selection_version':1,'replace_current':True},headers=headers(noop_key)).status_code==409
    change=confirm_body(role='Designer',field='Design',expected_selection_version=1)
    assert client.post(BASE+'/goals/confirm',json=change,headers=headers()).status_code==409
    changed=client.post(BASE+'/goals/confirm',json={**change,'replace_current':True},headers=headers()).json()
    assert changed['selection_version']==2 and changed['dependent_results_need_review']
    assert client.post(BASE+'/goals/confirm',json={**change,'replace_current':True},headers=headers()).status_code==409
    assert db.career_goals.count_documents({'record_type':{'$ne':'exploration_draft'}})==2
    assert client.post(BASE+'/goals/confirm',json={**body,'expected_selection_version':2,'expected_draft_version':99,'replace_current':True},headers=headers()).status_code==409


def test_temporary_cv_is_transient_and_reattach_is_required(flow):
    client,db,ai,cv=flow; draft=start(client,temporary_filename='cv.txt')
    assert turn(client,draft).status_code==422
    response=turn(client,draft,attachment_text='SYNTHETIC PRIVATE CV CONTENT')
    assert response.status_code==200,response.text
    assert 'SYNTHETIC PRIVATE CV CONTENT' in ai.inputs[-1].context
    assert 'SYNTHETIC PRIVATE CV CONTENT' not in json.dumps(list(db.career_goals.find()),default=str)
    assert turn(client,response.json(),attachment_text='a different CV').status_code==409
    document=client.post(BASE+'/explorations/cv/document',files={'file':('cv.txt','Synthetic skills and experience','text/plain')},headers=headers())
    assert document.status_code==200,document.text
    assert document.json()['text']=='Synthetic skills and experience'


def test_saved_cv_explicit_context_and_stale_version_guard(flow,documents):
    client,db,ai,cv=flow; cv.rows=[CvSnapshot.model_validate(documents['cv'])]
    listing=client.get(BASE+'/context',headers=headers()).json()
    assert listing['cvs'][0]['id']==documents['cv']['_id']
    assert start(client)['cv']['mode']=='none'
    draft=start(client,cv_id=documents['cv']['_id'])
    cv.rows[0].version=2
    assert turn(client,draft).status_code==409 and not ai.inputs


def test_late_result_does_not_overwrite_newer_draft(flow):
    client,db,ai,cv=flow; draft=start(client)
    from bson import ObjectId
    ai.hook=lambda: db.career_goals.update_one({'_id':ObjectId(draft['_id'])},{'$inc':{'version':1}})
    assert turn(client,draft).status_code==409
    stored=client.get(BASE+'/explorations/'+draft['_id'],headers=headers()).json()
    assert stored['version']==2 and not stored['turns']


def test_confirmation_pins_cv_and_replays_even_if_cv_changes_after_success(flow,documents):
    client,db,ai,cv=flow;cv.rows=[CvSnapshot.model_validate(documents['cv'])]
    draft=start(client,cv_id=documents['cv']['_id'])
    for _ in range(6):
        response=turn(client,draft);assert response.status_code==200,response.text
        draft=response.json()
    key=str(uuid4());body=confirm_body(draft)
    first=client.post(BASE+'/goals/confirm',json=body,headers=headers(key))
    assert first.status_code==200,first.text
    assert first.json()['goal']['source_profile_version']==1
    cv.rows[0].version=2
    assert client.post(BASE+'/goals/confirm',json=body,headers=headers(key)).status_code==200
    assert client.post(BASE+'/goals/confirm',json={**body,'expected_selection_version':1,'replace_current':True},headers=headers()).status_code==409


def test_agent_clarifies_vague_answers_and_uses_previous_messages(flow):
    client,db,ai,cv=flow
    original=ai.generate
    async def vague(data,operation,**kwargs):
        result=await original(data,operation,**kwargs)
        result.data=ExplorationOutput(reply='We can figure that out together.',follow_up='What would you like your working day to involve?',
            focus='aspirations',context_updates=[],interests=[],preferences=[],suggestions=[])
        return result
    ai.generate=vague
    draft=start(client)
    first=turn(client,draft,answer='Hi').json()
    assert first['answers']=={} and first['next_question']=='aspirations' and not first['context_complete']
    second=turn(client,first,answer='I am still figuring that out.').json()
    assert second['answers']=={} and len(ai.inputs[-1].conversation)==3
    assert ai.inputs[-1].conversation[0].content=='Hi'
    assert 'What would you like your working day' in ai.inputs[-1].conversation[1].content
    assert client.post(BASE+'/goals/confirm',json=confirm_body(second),headers=headers()).status_code==409


def test_grounded_partial_context_is_not_complete_and_forged_updates_cannot_publish(flow):
    client,db,ai,cv=flow;original=ai.generate
    async def partial(data,operation,**kwargs):
        result=await original(data,operation,**kwargs)
        result.data=ExplorationOutput(reply='Let’s narrow down what you mean by data.',follow_up='What sort of problems would you like to solve?',
            focus='aspirations',context_updates=[{'topic':'aspirations','status':'partial','value':'Interested in data work','quote':'data'}],
            interests=['data'],preferences=[],suggestions=[])
        return result
    ai.generate=partial;draft=start(client)
    one=turn(client,draft,answer='Maybe something with data.').json()
    assert one['answers']['aspirations']['status']=='partial' and not one['context_complete']
    # The same model update is not grounded in this new human message.
    failed=turn(client,one,answer='Hello again')
    assert failed.status_code==503
    saved=client.get(BASE+'/explorations/'+draft['_id'],headers=headers()).json()
    assert saved['version']==one['version'] and len(saved['turns'])==1


def test_agent_can_collect_multiple_topics_in_one_message(flow):
    client,db,ai,cv=flow;original=ai.generate
    text='I want useful work. I studied computing. I built a project. I use SQL. I enjoy analysis. I prefer Singapore.'
    # Make each evidence quote an exact substring, including the final punctuation.
    text=text.rstrip('.')
    async def grounded(data,operation,**kwargs):
        result=await original(data,operation,**kwargs)
        values=text.split('. ')
        result.data=ExplorationOutput(reply='We have enough to compare directions.',follow_up='Which option feels closest?',focus=None,
            context_updates=[{'topic':topic,'status':'answered','value':value,'quote':value} for topic,value in zip(
                ['aspirations','education','experience','skills','interests','preferences'],values)],
            interests=['analysis'],preferences=['Singapore'],suggestions=result.data.suggestions)
        return result
    ai.generate=grounded;draft=start(client);response=turn(client,draft,answer=text)
    assert response.status_code==200,response.text
    assert response.json()['context_complete'] and len(response.json()['turns'])==1


def test_conversation_continues_beyond_twelve_turns_with_bounded_history(flow):
    client,db,ai,cv=flow;original=ai.generate
    async def clarify(data,operation,**kwargs):
        result=await original(data,operation,**kwargs)
        result.data=ExplorationOutput(reply='We can keep exploring.',follow_up='What would you most like to change about your direction?',focus='aspirations',
            context_updates=[],interests=[],preferences=[],suggestions=[])
        return result
    ai.generate=clarify;draft=start(client)
    for _ in range(32):
        response=turn(client,draft,answer='I am still unsure.');assert response.status_code==200,response.text
        draft=response.json()
    assert draft['total_turns']==32 and len(draft['turns'])==30 and not draft['context_complete']
