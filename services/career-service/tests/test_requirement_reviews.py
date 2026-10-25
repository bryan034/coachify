"""J02–J04: real disposable MongoDB and synthetic external boundaries."""
import os
from datetime import datetime,timezone
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient
from app.main import create_app
from app.schemas.analysis import Generation
from app.schemas.jd import JDExtraction,JDReply
OWNER='11111111-1111-4111-8111-111111111111'
OTHER='22222222-2222-4222-8222-222222222222'
BASE='/api/v1/career'
SOURCE='Private raw JD sentinel. Analyst uses SQL; a degree OR experience is preferred.'
OUTPUT={'role':'Analyst','field':'Data','company':None,'skills':[{'name':'SQL','category':'Technical','priority':'required','origin':'employer','evidence':'Query data with SQL.','group_id':'entry','group_operator':'any'}],
 'non_skill_requirements':[{'requirement_id':'model-id','category':'qualification','description':'Degree or equivalent experience preferred.','priority':'preferred','evidence':'Degree or experience.','group_id':'entry','group_operator':'any'}]}
def headers(key=None,other=False):return {'Authorization':'Bearer '+('other' if other else 'owner'),'Idempotency-Key':key or str(uuid4())}
class AI:
    settings=SimpleNamespace(enabled=True)
    def __init__(self):self.output=OUTPUT;self.inputs=[];self.hook=None
    async def generate(self,data,op,**kwargs):
        self.inputs.append(data)
        if self.hook:self.hook()
        output=(JDExtraction if data.stage=='jd_extraction' else JDReply).model_validate(self.output)
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return SimpleNamespace(data=output,generation=Generation(provider='fixture',model='fixture',prompt_version='test',generated_at=datetime.now(timezone.utc)))
@pytest.fixture
def flow():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB.')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000);db=mongo['coachify_reviews_test_'+uuid4().hex];ai=AI()
    def profile(req):return httpx.Response(200,json={'id':OTHER if req.headers.get('Authorization')=='Bearer other' else OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    try:
        with TestClient(create_app(database=db,ai=ai,profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as client:yield client,db,ai
    finally:mongo.drop_database(db.name);mongo.close()
def extract(client,**extra):
    response=client.post(BASE+'/jd/extract',json={'text':SOURCE,**extra},headers=headers());assert response.status_code==200,response.text
    return response.json()
def save(client,review,content=None,**extra):
    return client.patch(BASE+'/goals/'+review['review_id']+'/review',json={'expected_version':review['version'],**({'content':content} if content is not None else {}),**extra},headers=headers())
def confirm(client,review,**extra):
    return client.post(BASE+'/goals/confirm',json={**{f:review['extraction'][f] for f in ('role','field','company','location','seniority_level','job_url')},'target_type':review['target_type'],'review_id':review['review_id'],'expected_review_version':review['version'],'expected_selection_version':0,**extra},headers=headers())
def test_extract_reload_owner_isolation_no_raw_source_and_idempotency(flow):
    client,db,ai=flow;key=headers();body={'text':SOURCE,'source_kind':'document'}
    first=client.post(BASE+'/jd/extract',json=body,headers=key);assert first.status_code==200,first.text
    review=first.json();assert client.post(BASE+'/jd/extract',json=body,headers=key).json()==review and len(ai.inputs)==1
    row=db.career_goals.find_one({'_id':ObjectId(review['review_id'])})
    assert row['source_kind']=='document' and 'Private raw JD sentinel' not in str(row)
    assert row['content']['skills'][0]['skill_id']=='language.sql'
    assert client.get(BASE+'/goals/'+review['review_id'],headers=headers()).json()==review
    assert client.get(BASE+'/goals/'+review['review_id'],headers=headers(other=True)).status_code==404
    assert client.post(BASE+'/jd/extract',json={'text':'different'},headers=key).status_code==409
    listing=client.get(BASE+'/goals',headers=headers()).json();assert len(listing['reviews'])==1 and listing['goals']==[]
def test_metadata_provenance_reset_conflict_and_noop(flow):
    client,db,ai=flow;review=extract(client);content=review['extraction'];content['company']='Example'
    response=save(client,review,content);assert response.status_code==200,response.text
    changed=response.json();assert changed['requirements_need_review'] and changed['metadata_origins']['company']=='user'
    assert confirm(client,changed).status_code==422 and save(client,review,content).status_code==409
    response=save(client,changed,reset='metadata',acknowledge_context=True);assert response.status_code==200,response.text
    reset=response.json();assert reset['extraction']['company'] is None and reset['metadata_origins']['company']=='extracted'
    assert save(client,reset,reset['extraction']).json()['version']==reset['version']
    assert confirm(client,reset).status_code==200

def test_atomic_reclassification_preserves_identity_or_groups_and_ranges(flow):
    client,db,ai=flow;review=extract(client);content=review['extraction'];skill=content['skills'].pop();identity=skill['item_id']
    content['non_skill_requirements'].append({'requirement_id':identity,'description':'SQL experience is one accepted route.','category':'experience','priority':'required','evidence':'Relevant SQL experience.','group_id':'entry','group_operator':'any','minimum_months':12,'maximum_months':36})
    response=save(client,review,content);assert response.status_code==200,response.text
    updated=response.json();conditions=updated['extraction']['non_skill_requirements']
    assert updated['extraction']['skills']==[] and conditions[1]['requirement_id']==identity
    assert all(r['group_operator']=='any' for r in conditions) and conditions[1]['correction']=='user'
    assert confirm(client,updated).json()['goal']['non_skill_requirements'][1]['minimum_months']==12
    conditions[1]['minimum_months']=40;assert save(client,updated,updated['extraction']).status_code==422

def test_confirmation_and_edit_fork_preserve_immutable_history(flow):
    client,db,ai=flow;review=extract(client);response=confirm(client,review);assert response.status_code==200,response.text
    goal=response.json()['goal'];assert goal['readiness']=='ready' and goal['skills'][0]['skill_id']=='language.sql'
    assert goal['source_review_id']==review['review_id'] and goal['non_skill_requirements']
    existing=client.get(BASE+'/goals/'+goal['_id'],headers=headers()).json();content=existing['extraction'];content['role']='Senior analyst'
    response=save(client,existing,content,acknowledge_context=True);assert response.status_code==200,response.text
    fork=response.json();assert fork['review_id']!=goal['_id']
    assert db.career_goals.find_one({'_id':ObjectId(goal['_id'])})['role']=='Analyst'
    replacement=confirm(client,fork,expected_selection_version=1,replace_current=True);assert replacement.status_code==200,replacement.text
    assert replacement.json()['dependent_results_need_review']
    assert client.get(BASE+'/goals/current',headers=headers()).json()['goal']['role']=='Senior analyst'

def test_unknown_skills_keep_pending_mapping(flow):
    client,db,ai=flow;ai.output={**OUTPUT,'skills':[{'name':'Specialist testing method','category':'Research','priority':'required','origin':'employer','evidence':'Use the specialist method.'}]}
    review=extract(client);assert review['extraction']['skills'][0]['skill_id'] is None
    assert confirm(client,review).json()['goal']['readiness']=='pending'

def test_chat_loads_owned_context_and_discards_late_answers(flow):
    client,db,ai=flow;review=extract(client);ai.output={'reply':'SQL helps you query data.','proposed_skills':None}
    body={'review_id':review['review_id'],'expected_version':review['version'],'message':'Explain SQL.'}
    response=client.post(BASE+'/jd/messages',json=body,headers=headers());assert response.status_code==200,response.text
    assert ai.inputs[-1].source_text is None and 'Query data' in ai.inputs[-1].context and SOURCE not in ai.inputs[-1].context
    assert client.post(BASE+'/jd/messages',json=body,headers=headers(other=True)).status_code==404
    ai.hook=lambda:db.career_goals.update_one({'_id':ObjectId(review['review_id'])},{'$inc':{'version':1}})
    assert client.post(BASE+'/jd/messages',json=body,headers=headers()).status_code==409

def test_save_receipts_and_confirmation_lock(flow):
    client,db,ai=flow;review=extract(client);key=headers();body={'expected_version':1,'content':review['extraction']};path=BASE+'/goals/'+review['review_id']+'/review'
    first=client.patch(path,json=body,headers=key);assert first.status_code==200
    assert client.patch(path,json=body,headers=key).json()==first.json()
    body['content']['company']='Changed';assert client.patch(path,json=body,headers=key).status_code==409
    repo=client.app.state.review_store;repo.claim_confirmation(review['review_id'],OWNER,1,'claim')
    assert save(client,review,review['extraction']).status_code==409
    repo.release_confirmation(review['review_id'],OWNER,'claim');assert save(client,review,review['extraction']).status_code==200

def test_stale_confirm_noop_and_lost_response_replay(flow):
    client,db,ai=flow;review=extract(client);content=review['extraction'];content['skills'][0]['context']='SQL for reporting.'
    changed=save(client,review,content).json();assert confirm(client,review).status_code==409
    key=headers();body={**{f:changed['extraction'][f] for f in ('role','field','company','location','seniority_level','job_url')},'target_type':'specific_job','review_id':changed['review_id'],'expected_review_version':changed['version'],'expected_selection_version':0}
    first=client.post(BASE+'/goals/confirm',json=body,headers=key);assert first.status_code==200,first.text
    assert client.post(BASE+'/goals/confirm',json=body,headers=key).json()==first.json()
    goal=first.json()['goal'];restored=client.get(BASE+'/goals/'+goal['_id'],headers=headers()).json()
    noop=save(client,restored,restored['extraction']);assert noop.status_code==200,noop.text
    assert noop.json()['review_id']==goal['_id'] and db.career_goals.count_documents({'record_type':'requirement_review'})==1
    # An immutable no-op still reserves its idempotency key against a changed retry.
    noop_key=headers();noop_body={'expected_version':restored['version'],'content':restored['extraction']}
    path=BASE+'/goals/'+goal['_id']+'/review'
    assert client.patch(path,json=noop_body,headers=noop_key).status_code==200
    noop_body['content']['company']='A different edit'
    assert client.patch(path,json=noop_body,headers=noop_key).status_code==409
    # Returning to the same effective content keeps the selected goal revision,
    # while acknowledging the exact latest review version for UI readback.
    edit=changed['extraction'];edit['skills'][0]['context']='A temporary refinement.'
    newer=save(client,changed,edit).json()
    edit['skills'][0]['context']='SQL for reporting.'
    same=save(client,newer,edit).json()
    selected=confirm(client,same,expected_selection_version=1)
    assert selected.status_code==200,selected.text
    assert selected.json()['selection_version']==1
    assert selected.json()['review_selection']=={'id':same['review_id'],'version':same['version']}
    assert selected.json()['goal']['source_review_version']==changed['version']

def test_exploration_metadata_edits_preserve_context_and_reject_employer_conditions(flow):
    from app.schemas.analysis import CareerGoal,mongo_document
    from app.repositories.goals import now
    client,db,ai=flow;stamp=now();identifier='000000000000000000000091'
    goal=CareerGoal(_id=identifier,user_id=OWNER,version=1,skill_mapping_version='skills-v1',created_at=stamp,updated_at=stamp,
       target_type='career_exploration',field='Data',role='Analyst',interests=['Research'],preferences=['Singapore'],requirements_source='career_exploration',generation_version='pending-skills',readiness='pending')
    db.career_goals.insert_one(mongo_document(goal))
    view=client.get(BASE+'/goals/'+identifier,headers=headers()).json();content=view['extraction'];content['company']='Example'
    fork=save(client,view,content,acknowledge_context=True);assert fork.status_code==200,fork.text
    selected=confirm(client,fork.json());assert selected.status_code==200,selected.text
    assert selected.json()['goal']['interests']==['Research'] and selected.json()['goal']['preferences']==['Singapore']
    content=fork.json()['extraction'];content['non_skill_requirements']=[OUTPUT['non_skill_requirements'][0]]
    assert save(client,fork.json(),content).status_code==422

def test_conflicting_group_rules_and_forged_mapping_cannot_publish(flow):
    client,db,ai=flow;view=extract(client);content=view['extraction']
    content['skills'][0]['skill_id']='forged.sql';result=save(client,view,content)
    assert result.status_code==200 and result.json()['extraction']['skills'][0]['skill_id']=='language.sql'
    content['non_skill_requirements'][0]['group_operator']='all'
    assert save(client,view,content).status_code==422
