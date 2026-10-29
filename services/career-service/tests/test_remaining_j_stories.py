from tests.api_views import goal_view
"""J05/J10/J12/J13: real MongoDB, synthetic AI/retrieval, no live credentials."""
import copy
import os
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
from app.repositories.goals import GoalError,now
from app.schemas.analysis import CareerGoal,Generation,ResearchSource,mongo_document
from app.schemas.jd import JDExtraction
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
        if request.stage=='role_guidance':
            value=JDExtraction(role='Wrong AI role',field='Wrong AI field',company=None,skills=[] if self.empty else [
                {'name':'SQL','category':'Technical','priority':'suggested','origin':'generated_guidance','context':'Useful for analysis; depth varies.'}])
        else:
            value=SourcedTopics(topics=[] if self.empty else [{'name':'SQL','category':'Technical','source_ids':['forged' if self.forge else 'source-1'],
                'quotes':[TEXT],'question_patterns':['Explain joins.']}])
        if kwargs.get('validate_output'):kwargs['validate_output'](value)
        return SimpleNamespace(data=value,generation=provenance())
class Sources:
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
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000);db=mongo['coachify_remaining_test_'+uuid4().hex];ai=AI();sources=Sources();goal=seed(db)
    def profile(req):return httpx.Response(200,json={'id':OTHER if req.headers.get('Authorization')=='Bearer other' else OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    try:
        with TestClient(create_app(database=db,ai=ai,research_client=sources,profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as client:
            yield client,db,ai,sources,goal
    finally:mongo.drop_database(db.name);mongo.close()
def generate(flow,key=None):
    client,_,_,_,goal=flow
    return client.post(BASE+goal.id+'/guidance',headers=headers(key),json={'expected_version':1,'expected_selection_version':1})
def research(flow,**changes):
    client,_,_,_,goal=flow
    return client.post(BASE+goal.id+'/interview-research',headers=headers(),json={'expected_version':1,'expected_selection_version':1,**changes})

def test_guidance_is_advisory_idempotent_editable_and_explicitly_selected(flow):
    client,db,ai,sources,goal=flow;key=str(uuid4());first=generate(flow,key);assert first.status_code==200,first.text
    review=goal_view(first);assert review['target_type']=='career_exploration'
    assert review['content']['role']==goal.role and review['content']['skills'][0]['priority']=='suggested'
    assert review['content']['skills'][0]['skill_id']=='language.sql'
    assert goal_view(generate(flow,key))==review and len(ai.calls)==1
    assert db.career_state.find_one({'_id':OWNER})['goal_id']==ObjectId(goal.id)
    assert client.get(BASE+review['goal_id'],headers=headers(other=True)).status_code==404
    content=review['content'];content['skills'][0]['context']='Edited planning rationale'
    changed=client.patch(BASE+review['goal_id']+'/review',headers=headers(),json={'expected_version':1,'content':content})
    assert changed.status_code==200,changed.text
    reviewed=goal_view(changed);data={k:reviewed['content'][k] for k in ('role','field','company','location','seniority_level','job_url')}
    selected=client.post(BASE+'confirm',headers=headers(),json={**data,'expected_selection_version':1,'replace_current':True,
        'target_type':'career_exploration','review_id':reviewed['goal_id'],'expected_review_version':reviewed['version']})
    assert selected.status_code==200,selected.text
    assert goal_view(selected)['goal']['skills'][0]['origin']=='generated_guidance'
    assert goal_view(selected)['dependent_results_need_review'] is True
    assert db.career_goals.find_one({'_id':ObjectId(goal.id)})['skills']==[]

@pytest.mark.parametrize('defect',['empty','provider','stale'])
def test_guidance_failure_never_replaces_prior_goal(flow,defect):
    client,db,ai,sources,goal=flow
    if defect=='empty':ai.empty=True
    if defect=='provider':ai.fail=True
    if defect=='stale':ai.hook=lambda:db.career_state.update_one({'_id':OWNER},{'$inc':{'version':1}})
    response=generate(flow)
    assert response.status_code in (409,503),response.text
    assert db.career_goals.count_documents({'record_type':'requirement_review'})==0
    assert 'guidance_processing' not in db.career_state.find_one({'_id':OWNER})


def test_priority_corrections_conflicts_and_noop_keep_item_identity(flow):
    client,db,ai,_,goal=flow
    review=goal_view(generate(flow));content=copy.deepcopy(review['content']);item=content['skills'][0]
    item.update(priority='conflicting',priority_evidence='I am unsure which planning priority to use.',origin='user_declaration')
    body={'expected_version':1,'content':content};key=headers()
    path=BASE+review['goal_id']+'/review';first=client.patch(path,headers=key,json=body)
    assert first.status_code==200,first.text
    assert goal_view(first)['content']['skills'][0]['item_id']==review['content']['skills'][0]['item_id']
    assert goal_view(first)['content']['skills'][0]['priority_origin']=='user_declaration'
    assert goal_view(client.patch(path,headers=key,json=body))==goal_view(first)
    same=client.patch(path,headers=headers(),json={'expected_version':2,'content':goal_view(first)['content']})
    assert goal_view(same)['version']==2
    reset=client.patch(path,headers=headers(),json={'expected_version':2,'reset':'all'})
    assert reset.status_code==422
    saved=goal_view(client.get(BASE+review['goal_id'],headers=headers()))
    assert saved['content']['skills'][0]['priority']=='conflicting'
    assert saved['content']['skills'][0]['priority_origin']=='user_declaration'


def test_public_research_reuses_across_users_with_private_links_and_no_private_inputs(flow):
    client,db,ai,sources,goal=flow;first=research(flow);assert first.status_code==200,first.text
    result=goal_view(first);record=result['research'];rid=record['_id']
    assert result['general'] and record['skills'][0]['independent_report_count']==0
    shared=db.interview_research.find_one({'_id':ObjectId(rid)})
    assert 'PRIVATE' not in str(shared) and OWNER not in str(shared) and 'user_id' not in shared
    assert ai.calls[-1].stage=='interview_synthesis' and ai.calls[-1].conversation==[] and not ai.calls[-1].context
    assert client.get(BASE+goal.id+'/interview-research',headers=headers(other=True)).status_code==404
    other=seed(db,OTHER)
    assert client.get(BASE+other.id+'/interview-research?research_id='+rid,headers=headers(other=True)).status_code==404
    second=client.post(BASE+other.id+'/interview-research',headers=headers(other=True),json={'expected_version':1,'expected_selection_version':1})
    assert second.status_code==200 and goal_view(second)['reused'] is True
    assert goal_view(second)['research']['_id']==rid and len(sources.contexts)==1
    assert db.interview_research.count_documents({})==1
    reopened=client.get(BASE+other.id+'/interview-research?research_id='+rid,headers=headers(other=True))
    assert reopened.status_code==200 and goal_view(reopened)['reused'] is True


def test_refresh_pins_history_and_failure_preserves_previous_result(flow):
    client,db,ai,sources,goal=flow
    first=goal_view(research(flow))['research'];second=goal_view(research(flow,refresh=True))['research']
    assert second['version']>first['version'] and second['_id']!=first['_id']
    old=goal_view(client.get(BASE+goal.id+'/interview-research?research_id='+first['_id'],headers=headers()))
    assert old['research']==first and old['historical']
    ai.fail=True;assert research(flow,refresh=True).status_code==503
    restored=goal_view(client.get(BASE+goal.id+'/interview-research',headers=headers()))
    assert restored['status']=='failed' and restored['research']==second


@pytest.mark.parametrize('case',['forged','blocked','empty','changed_goal'])
def test_research_failure_empty_and_late_results_are_distinct(flow,case):
    client,db,ai,sources,goal=flow
    if case=='forged':ai.forge=True
    if case=='blocked':sources.fail=True
    if case=='empty':ai.empty=True
    if case=='changed_goal':ai.hook=lambda:db.career_state.update_one({'_id':OWNER},{'$inc':{'version':1}})
    response=research(flow)
    if case=='empty':
        assert response.status_code==200,response.text
        assert goal_view(response)['status']=='no_findings' and goal_view(response)['research']['skills']==[]
    elif case=='changed_goal':
        assert response.status_code==409
        assert not db.career_state.find_one({'_id':OWNER}).get('research_links')
    else:
        assert response.status_code==503
        view=goal_view(client.get(BASE+goal.id+'/interview-research',headers=headers()))
        assert view['status']==('unavailable' if case=='blocked' else 'failed') and view['research'] is None


def test_processing_lease_avoids_duplicate_acquisition_and_recovers_on_expiry(flow):
    client,db,ai,sources,goal=flow
    repo=client.app.state.research_store
    from app.api.v1.research import context_for
    context=context_for(goal);lease=repo.begin(context,False)
    pending=research(flow);assert pending.status_code==200 and goal_view(pending)['status']=='processing'
    assert not ai.calls and not sources.contexts
    db.research_contexts.update_one({'_id':context.reuse_key()},{'$set':{'lease.expires_at':now()-timedelta(seconds=1)}})
    assert goal_view(client.get(BASE+goal.id+'/interview-research',headers=headers()))['status']=='failed'
    assert research(flow).status_code==200


def test_context_mismatch_and_staleness_do_not_reuse_exact_results(flow):
    client,db,ai,sources,goal=flow
    first=goal_view(research(flow))['research']
    other=seed(db,OTHER,location='Singapore')
    different=client.post(BASE+other.id+'/interview-research',headers=headers(other=True),json={'expected_version':1,'expected_selection_version':1})
    assert different.status_code==200 and goal_view(different)['research']['_id']!=first['_id']
    assert len(sources.contexts)==2
    db.interview_research.update_one({'_id':ObjectId(first['_id'])},{'$set':{'last_researched_at':now()-timedelta(days=8)}})
    assert goal_view(client.get(BASE+goal.id+'/interview-research',headers=headers()))['stale'] is True
    assert goal_view(research(flow))['research']['_id']!=first['_id']


def test_users_cannot_submit_research_source_urls(flow):
    client,db,ai,sources,goal=flow
    response=research(flow,source_urls=['https://example.test/interview'])
    assert response.status_code==422
    assert not sources.contexts and not ai.calls


def test_unconnected_api_preserves_history_without_calling_model(flow):
    from app.clients.research import UnavailableResearchProvider
    client,db,ai,sources,goal=flow
    original=goal_view(research(flow))['research'];calls=len(ai.calls)
    client.app.state.research_client=UnavailableResearchProvider()
    response=research(flow,refresh=True)
    assert response.status_code==503 and 'not connected' in response.text
    saved=goal_view(client.get(BASE+goal.id+'/interview-research',headers=headers()))
    assert saved['status']=='unavailable' and saved['research']==original
    assert len(ai.calls)==calls


def test_explicit_importance_changes_preserve_user_provenance(flow):
    client,db,ai,sources,goal=flow
    review=goal_view(generate(flow));content=copy.deepcopy(review['content'])
    content['skills'][0].update(origin='user_declaration',priority='preferred',priority_evidence='My chosen planning priority.')
    path=BASE+review['goal_id']+'/review'
    edited=client.patch(path,headers=headers(),json={'expected_version':1,'content':content})
    assert edited.status_code==200,edited.text
    changed=goal_view(edited)
    assert changed['content']['skills'][0]['priority_origin']=='user_declaration'
    assert changed['content']['skills'][0]['item_id']==review['content']['skills'][0]['item_id']


def test_brave_policy_rebuilds_old_mixed_provider_cache_and_preserves_history(flow):
    client,db,ai,sources,goal=flow
    first=research(flow);assert first.status_code==200,first.text
    old_id=goal_view(first)['research']['_id']
    db.research_contexts.update_many({}, {'$set':{'policy':'public-interview-v1'}})
    second=research(flow);assert second.status_code==200,second.text
    assert not goal_view(second)['reused']
    assert goal_view(second)['research']['_id']!=old_id
    assert len(sources.contexts)==2
    historical=client.get(BASE+goal.id+'/interview-research?research_id='+old_id,headers=headers())
    assert historical.status_code==200 and goal_view(historical)['research']['_id']==old_id
    assert goal_view(research(flow))['reused'] is True


def edit_current_goal(client,goal,**changes):
    saved=goal_view(client.get(BASE+goal.id,headers=headers()))
    content=copy.deepcopy(saved['content']);content.update(changes)
    result=client.patch(BASE+goal.id+'/review',headers=headers(),json={'expected_version':saved['version'],'content':content})
    assert result.status_code==200,result.text
    return goal_view(result)


def test_real_review_edit_during_retrieval_rejects_late_attachment(flow):
    import asyncio
    import threading
    from concurrent.futures import ThreadPoolExecutor
    client,db,ai,sources,goal=flow
    started=threading.Event();release=threading.Event();collect=sources.collect
    async def blocked(context):
        started.set();await asyncio.to_thread(release.wait)
        return await collect(context)
    sources.collect=blocked
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(research,flow)
        try:
            assert started.wait(5)
            changed=edit_current_goal(client,goal,role='Product Analyst')
            assert changed['version']==2
            # The original flaw needs no selection change: the real review API
            # modifies the same canonical goal document in place.
            assert db.career_state.find_one({'_id':OWNER})['version']==1
        finally:release.set()
        result=pending.result(timeout=10)
    assert result.status_code==409,result.text
    assert not db.career_state.find_one({'_id':OWNER}).get('research_links')
    assert db.interview_research.count_documents({})==1  # Immutable public history survives.
    latest=goal_view(client.get(BASE+goal.id+'/interview-research',headers=headers()))
    assert latest['research'] is None and latest['context']['role']=='Product Analyst'
    assert research(flow,expected_version=2).status_code==200


@pytest.mark.parametrize('changes',[{'role':'Product Analyst'},{'summary':'Updated personal review of the same public role.'}])
def test_old_research_is_explicit_history_until_current_revision_is_attached(flow,changes):
    client,db,ai,sources,goal=flow
    key=str(uuid4());body={'expected_version':1,'expected_selection_version':1}
    first=client.post(BASE+goal.id+'/interview-research',headers=headers(key),json=body)
    assert first.status_code==200,first.text
    original=goal_view(first)['research'];identifier=original['_id']
    edit_current_goal(client,goal,**changes)
    current=goal_view(client.get(BASE+goal.id+'/interview-research',headers=headers()))
    assert current['research'] is None and current['status']=='missing'
    historical=goal_view(client.get(BASE+goal.id+'/interview-research?research_id='+identifier,headers=headers()))
    assert historical['historical'] and historical['research']==original
    assert historical['context']['role']==original['role']
    assert client.post(BASE+goal.id+'/interview-research',headers=headers(key),json=body).status_code==409
    refreshed=research(flow,expected_version=2)
    assert refreshed.status_code==200,refreshed.text
    assert goal_view(client.get(BASE+goal.id+'/interview-research',headers=headers()))['research'] is not None
    assert db.interview_research.find_one({'_id':ObjectId(identifier)}) is not None


def test_edit_between_link_write_and_final_check_leaves_only_historical_link(flow,monkeypatch):
    client,db,ai,sources,goal=flow
    repo=client.app.state.research_store;original=repo.state.update_one;changed=[]
    def race(query,update,*args,**kwargs):
        result=original(query,update,*args,**kwargs)
        if not changed and any(key.startswith('research_link_meta.') for key in update.get('$set',{})):
            changed.append(True);edit_current_goal(client,goal,role='Product Analyst')
        return result
    monkeypatch.setattr(repo.state,'update_one',race)
    result=research(flow)
    assert result.status_code==409,result.text
    assert changed
    history=repo.linked(OWNER,goal.id)
    assert len(history)==1 and repo.read(OWNER,goal.id) is None
    assert repo.read(OWNER,goal.id,history[0]) is not None
    assert repo.linked(OWNER,goal.id,current=True)==[]
