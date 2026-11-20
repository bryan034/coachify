"""J05/J10/J12/J13: real MongoDB, synthetic AI/retrieval, no live credentials."""
import os
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.main import create_app
from app.domain.review import MAPPING_VERSION
from app.ai.errors import AIError
from app.repositories.goals import GoalError,now
from app.schemas.analysis import CareerGoal,Generation,InterviewResearch,ResearchSource,context_for,mongo_document
from app.schemas.jd import JDExtraction,SaveReview
from app.schemas.research import SourcedTopics

OWNER='11111111-1111-4111-8111-111111111111';OTHER='22222222-2222-4222-8222-222222222222'
BASE='/api/v1/career/goals/'
TEXT='Data Analyst interview includes SQL exercise. Explain joins.'

def headers(key=None,other=False):return {'Authorization':'Bearer '+('other' if other else 'owner'),'Idempotency-Key':key or str(uuid4())}
def provenance():return Generation(provider='fixture',model='fixture',prompt_version='test',generated_at=now())
class AI:
    settings=SimpleNamespace(enabled=True)
    def __init__(self):self.calls=[];self.hook=None;self.fail=False;self.empty=False;self.forge=False
    async def generate(self,request,operation,**kwargs):
        self.calls.append(request)
        if self.hook:self.hook()
        if self.fail:raise AIError('unavailable',True)
        value=SourcedTopics(topics=[] if self.empty else [{'name':'SQL','category':'Technical','source_ids':['forged' if self.forge else 'source-1'],
            'quotes':[TEXT],'question_patterns':['Explain joins.']}])
        if kwargs.get('validate_output'):kwargs['validate_output'](value)
        return SimpleNamespace(data=value,generation=provenance())
class Sources:
    provider='brave';backend='brave'
    def __init__(self):self.contexts=[];self.fail=False
    async def collect(self,context):
        self.contexts.append(context)
        if self.fail:raise GoalError('Public material unavailable',503)
        return [ResearchSource(source_id='source-1',platform='other',url='https://example.test/interview',
            title='Public interview guide',evidence=TEXT,role_match='exact',reliability='unverified',report_group=None,retrieved_at=now())]

def seed(db,owner=OWNER,company=None,location=None):
    stamp=now();goal=CareerGoal(_id=str(ObjectId()),user_id=owner,version=1,skill_mapping_version='skills-v1',
        created_at=stamp,updated_at=stamp,target_type='career_exploration',field='Data',role='Data Analyst',company=company,location=location,
        interests=['PRIVATE INTEREST'],preferences=['PRIVATE PREFERENCE'],skills=[],requirements_source='career_exploration',generation_version='pending',readiness='pending')
    db.career_goals.insert_one(mongo_document(goal));db.career_state.replace_one({'_id':owner},{'_id':owner,'version':1,'goal_id':ObjectId(goal.id),'receipts':[]},upsert=True)
    return goal
@pytest.fixture
def flow():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000);db=mongo['elo_remaining_test_'+uuid4().hex];ai=AI();sources=Sources();goal=seed(db)
    def profile(req):return httpx.Response(200,json={'id':OTHER if req.headers.get('Authorization')=='Bearer other' else OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    try:
        with TestClient(create_app(database=db,ai=ai,research_client=sources,profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as client:
            yield client,db,ai,sources,goal
    finally:mongo.drop_database(db.name);mongo.close()
def generate(flow):
    client,_,_,_,goal=flow
    content=JDExtraction(role=goal.role,field=goal.field,company=None,skills=[
        {'name':'SQL','category':'Technical','priority':'suggested','origin':'generated_guidance','context':'Useful for analysis; depth varies.'}])
    return client.app.state.review_store.create_guidance(OWNER,str(uuid4()),'synthetic-digest',goal,content,provenance())
def save_review(client,review,content,key=None,**extra):
    body=SaveReview.model_validate({'expected_version':review.version,'content':content,**extra})
    return client.app.state.review_store.save(review.id,OWNER,key or str(uuid4()),body)
def test_priority_corrections_conflicts_and_noop_keep_item_identity(flow):
    client,db,ai,_,goal=flow
    review=generate(flow);content=review.content.model_dump(mode='json');item=content['skills'][0]
    item.update(priority='conflicting',priority_evidence='I am unsure which planning priority to use.',origin='user_declaration')
    key=str(uuid4());first=save_review(client,review,content,key)
    assert first.content.skills[0].item_id==review.content.skills[0].item_id
    assert first.content.skills[0].priority_origin=='user_declaration'
    assert save_review(client,review,content,key)==first
    same=save_review(client,first,first.content.model_dump(mode='json'))
    assert same.version==2
    saved=client.app.state.review_store.get(review.id,OWNER)
    assert saved.content.skills[0].priority=='conflicting'
    assert saved.content.skills[0].priority_origin=='user_declaration'


def test_explicit_importance_changes_preserve_user_provenance(flow):
    client,db,ai,sources,goal=flow
    review=generate(flow);content=review.content.model_dump(mode='json')
    content['skills'][0].update(origin='user_declaration',priority='preferred',priority_evidence='My chosen planning priority.')
    changed=save_review(client,review,content)
    assert changed.content.skills[0].priority_origin=='user_declaration'
    assert changed.content.skills[0].item_id==review.content.skills[0].item_id


def edit_current_goal(client,goal,**changes):
    saved=client.app.state.review_store.get(goal.id,OWNER)
    content=saved.content.model_dump(mode='json');content.update(changes)
    return save_review(client,saved,content)


def acquire(flow,goal,owner=OWNER,refresh=False):
    """Run the research store steps the workspace workflow uses, with synthetic retrieval."""
    client,_,_,sources,_=flow
    repo=client.app.state.research_store;context=context_for(goal)
    started=repo.begin(context,refresh)
    if started.get('record'):record,reused=started['record'],True
    else:
        stamp=now();found=asyncio.run(sources.collect(context))
        record=repo.finish(context,started['token'],InterviewResearch(_id=str(ObjectId()),version=started['version'],
            skill_mapping_version=MAPPING_VERSION,created_at=stamp,updated_at=stamp,**context.model_dump(),sources=found,skills=[],
            research_status='no_findings',last_researched_at=stamp,generation=provenance()));reused=False
    repo.attach(owner,goal.id,1,str(uuid4()),'synthetic-digest',record,goal_version=goal.version,reused=reused)
    return record


def current_goal(flow):
    client,_,_,_,goal=flow
    return client.app.state.research_store.goal(OWNER,goal.id)


def test_public_research_is_shared_across_users_with_private_links(flow):
    client,db,ai,sources,goal=flow;repo=client.app.state.research_store
    first=acquire(flow,goal)
    shared=db.interview_research.find_one({'_id':ObjectId(first.id)})
    assert 'PRIVATE' not in str(shared) and OWNER not in str(shared) and 'user_id' not in shared
    other=seed(db,OTHER)
    with pytest.raises(GoalError) as hidden:repo.read(OTHER,other.id,first.id)
    assert hidden.value.status==404
    second=acquire(flow,other,OTHER)
    assert second.id==first.id and len(sources.contexts)==1 and db.interview_research.count_documents({})==1
    assert repo.read(OTHER,other.id,first.id).id==first.id
    with pytest.raises(GoalError):repo.read(OTHER,goal.id)


def test_refresh_pins_history_and_failure_preserves_previous_result(flow):
    client,db,ai,sources,goal=flow;repo=client.app.state.research_store;context=context_for(goal)
    first=acquire(flow,goal);second=acquire(flow,goal,refresh=True)
    assert second.version>first.version and second.id!=first.id
    assert repo.read(OWNER,goal.id,first.id)==first
    started=repo.begin(context,True);repo.fail(context,started['token'],'failed')
    assert repo.read(OWNER,goal.id).id==second.id
    assert db.research_contexts.find_one({'_id':context.reuse_key()})['status']=='failed'


def test_processing_lease_avoids_duplicate_acquisition_and_recovers_on_expiry(flow):
    client,db,ai,sources,goal=flow;repo=client.app.state.research_store;context=context_for(goal)
    assert repo.begin(context,False).get('token')
    assert repo.begin(context,False)=={'processing':True}
    db.research_contexts.update_one({'_id':context.reuse_key()},{'$set':{'lease.expires_at':now()-timedelta(seconds=1)}})
    assert repo.begin(context,False).get('token')


def test_context_mismatch_staleness_and_policy_change_do_not_reuse_results(flow):
    client,db,ai,sources,goal=flow;repo=client.app.state.research_store;context=context_for(goal)
    first=acquire(flow,goal)
    assert acquire(flow,seed(db,OTHER,location='Singapore'),OTHER).id!=first.id and len(sources.contexts)==2
    assert repo.begin(context,False)['record'].id==first.id
    db.research_contexts.update_one({'_id':context.reuse_key()},{'$set':{'policy':'public-interview-v1'}})
    assert 'record' not in repo.begin(context,False)
    db.research_contexts.update_many({},{'$unset':{'lease':''},'$set':{'policy':repo.policy}})
    db.interview_research.update_one({'_id':ObjectId(first.id)},{'$set':{'last_researched_at':now()-timedelta(days=8)}})
    assert 'record' not in repo.begin(context,False)


@pytest.mark.parametrize('changes',[{'role':'Product Analyst'},{'summary':'Updated personal review of the same public role.'}])
def test_old_research_is_explicit_history_until_current_revision_is_attached(flow,changes):
    client,db,ai,sources,goal=flow;repo=client.app.state.research_store
    original=acquire(flow,goal)
    edit_current_goal(client,goal,**changes)
    assert repo.read(OWNER,goal.id) is None
    assert repo.read(OWNER,goal.id,original.id)==original
    acquire(flow,current_goal(flow))
    assert repo.read(OWNER,goal.id) is not None
    assert db.interview_research.find_one({'_id':ObjectId(original.id)}) is not None


def test_edit_before_attachment_rejects_the_late_result(flow):
    client,db,ai,sources,goal=flow;repo=client.app.state.research_store;context=context_for(goal)
    started=repo.begin(context,False);stamp=now()
    record=repo.finish(context,started['token'],InterviewResearch(_id=str(ObjectId()),version=started['version'],
        skill_mapping_version=MAPPING_VERSION,created_at=stamp,updated_at=stamp,**context.model_dump(),sources=[],skills=[],
        research_status='no_findings',last_researched_at=stamp,generation=provenance()))
    assert edit_current_goal(client,goal,role='Product Analyst').version==2
    with pytest.raises(GoalError):repo.attach(OWNER,goal.id,1,str(uuid4()),'synthetic-digest',record,goal_version=1)
    assert not db.career_state.find_one({'_id':OWNER}).get('research_links')
    assert db.interview_research.count_documents({})==1


def test_edit_between_link_write_and_final_check_leaves_only_historical_link(flow,monkeypatch):
    client,db,ai,sources,goal=flow
    repo=client.app.state.research_store;original=repo.state.update_one;changed=[]
    def race(query,update,*args,**kwargs):
        result=original(query,update,*args,**kwargs)
        if not changed and any(key.startswith('research_link_meta.') for key in update.get('$set',{})):
            changed.append(True);edit_current_goal(client,goal,role='Product Analyst')
        return result
    monkeypatch.setattr(repo.state,'update_one',race)
    with pytest.raises(GoalError):acquire(flow,goal)
    assert changed
    history=repo.linked(OWNER,goal.id)
    assert len(history)==1 and repo.read(OWNER,goal.id) is None
    assert repo.read(OWNER,goal.id,history[0]) is not None
    assert repo.linked(OWNER,goal.id,current=True)==[]
