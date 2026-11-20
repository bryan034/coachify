"""J02–J04: review storage used by the workspace, against real disposable MongoDB."""
import copy
import os
from datetime import datetime,timezone
from uuid import uuid4
import pytest
from bson import ObjectId
from pydantic import ValidationError
from pymongo import MongoClient
from app.repositories.goals import GoalError,GoalStore,now
from app.repositories.reviews import ReviewStore
from app.schemas.analysis import CareerGoal,Generation,mongo_document
from app.schemas.goals import SaveGoal
from app.schemas.jd import JDExtraction,SaveReview
OWNER='11111111-1111-4111-8111-111111111111'
OTHER='22222222-2222-4222-8222-222222222222'
OUTPUT={'role':'Analyst','field':'Data','company':None,'skills':[{'name':'SQL','category':'Technical','priority':'required','origin':'employer','evidence':'Query data with SQL.','group_id':'entry','group_operator':'any'}],
 'non_skill_requirements':[{'requirement_id':'model-id','category':'qualification','description':'Degree or equivalent experience preferred.','priority':'preferred','evidence':'Degree or experience.','group_id':'entry','group_operator':'any'}]}
GENERATION=Generation(provider='fixture',model='fixture',prompt_version='test',generated_at=datetime.now(timezone.utc))
@pytest.fixture
def stores():
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB.')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000);db=mongo['elo_reviews_test_'+uuid4().hex]
    try:yield ReviewStore(db),GoalStore(db),db
    finally:mongo.drop_database(db.name);mongo.close()
def extract(reviews,output=OUTPUT,kind='text'):
    return reviews.create(OWNER,str(uuid4()),'synthetic-digest',JDExtraction.model_validate(output),GENERATION,kind)
def content_of(review):
    return copy.deepcopy(review.content.model_dump(mode='json'))
def save(reviews,review,content=None,key=None,**extra):
    body=SaveReview.model_validate({'expected_version':review.version,'content':content_of(review) if content is None else content,**extra})
    return reviews.save(review.id,OWNER,key or str(uuid4()),body)
def confirm(reviews,goals,review,key=None,selection=0):
    key=key or str(uuid4());content=review.content
    command=SaveGoal(target_type=review.target_type,role=content.role,field=content.field,company=content.company,location=content.location,
        seniority_level=content.seniority_level,job_url=content.job_url,employment_type=content.employment_type,
        review_id=review.id,expected_review_version=review.version,expected_selection_version=selection)
    return goals.confirm(OWNER,key,command,reviews.goal(review,OWNER,key,command))
def test_create_is_idempotent_owner_scoped_and_maps_skills(stores):
    reviews,_,db=stores;key=str(uuid4());content=JDExtraction.model_validate(OUTPUT)
    first=reviews.create(OWNER,key,'synthetic-digest',content,GENERATION,'document')
    assert reviews.create(OWNER,key,'synthetic-digest',content,GENERATION,'document')==first
    row=db.career_goals.find_one({'_id':ObjectId(first.id)})
    assert row['source_kind']=='document' and row['content']['skills'][0]['skill_id']=='language.sql'
    with pytest.raises(GoalError) as missing:reviews.get(first.id,OTHER)
    assert missing.value.status==404
    with pytest.raises(GoalError) as conflict:reviews.create(OWNER,key,'different-digest',content,GENERATION,'document')
    assert conflict.value.status==409
def test_metadata_provenance_explicit_correction_conflict_and_noop(stores):
    reviews,goals,_=stores;review=extract(reviews);content=content_of(review);content['company']='Example'
    changed=save(reviews,review,content)
    assert changed.requirements_need_review and changed.metadata_origins['company']=='user'
    with pytest.raises(GoalError):save(reviews,review,content)
    content=content_of(changed);content['company']=None
    reset=save(reviews,changed,content,acknowledge_context=True)
    assert reset.content.company is None and reset.metadata_origins['company']=='user' and not reset.requirements_need_review
    assert save(reviews,reset).version==reset.version
    assert confirm(reviews,goals,reset)['goal'].id==reset.id
def test_atomic_reclassification_preserves_identity_or_groups_and_ranges(stores):
    reviews,goals,_=stores;review=extract(reviews);content=content_of(review);skill=content['skills'].pop();identity=skill['item_id']
    content['non_skill_requirements'].append({'requirement_id':identity,'description':'SQL experience is one accepted route.','category':'experience','priority':'required','evidence':'Relevant SQL experience.','group_id':'entry','group_operator':'any','minimum_months':12,'maximum_months':36})
    updated=save(reviews,review,content);conditions=updated.content.non_skill_requirements
    assert updated.content.skills==[] and conditions[1].requirement_id==identity
    assert all(r.group_operator=='any' for r in conditions) and conditions[1].correction=='user'
    assert confirm(reviews,goals,updated)['goal'].non_skill_requirements[1].minimum_months==12
    content=content_of(updated);content['non_skill_requirements'][1]['minimum_months']=40
    with pytest.raises(ValidationError):save(reviews,updated,content)
def test_confirmation_and_edits_update_the_same_current_goal(stores):
    reviews,goals,db=stores;review=extract(reviews);goal=confirm(reviews,goals,review)['goal']
    assert goal.readiness=='ready' and goal.skills[0].skill_id=='language.sql'
    assert goal.source_review_id==review.id and goal.non_skill_requirements
    existing=reviews.get(goal.id,OWNER);content=content_of(existing);content['role']='Senior analyst'
    edited=save(reviews,existing,content,acknowledge_context=True)
    assert edited.id==goal.id and edited.version==2
    assert db.career_goals.find_one({'_id':ObjectId(goal.id)})['role']=='Senior analyst'
    assert goals.current(OWNER)['goal'].role=='Senior analyst'
def test_unknown_skills_keep_pending_mapping(stores):
    reviews,goals,_=stores
    review=extract(reviews,{**OUTPUT,'skills':[{'name':'Specialist testing method','category':'Research','priority':'required','origin':'employer','evidence':'Use the specialist method.'}]})
    assert review.content.skills[0].skill_id is None
    assert confirm(reviews,goals,review)['goal'].readiness=='pending'
def test_save_receipts_replay_and_reject_reused_keys(stores):
    reviews,_,_=stores;review=extract(reviews);key=str(uuid4())
    first=save(reviews,review,key=key)
    assert save(reviews,review,key=key)==first
    content=content_of(review);content['company']='Changed'
    with pytest.raises(GoalError):save(reviews,review,content,key=key)
def test_confirm_replay_noop_and_latest_edit_stay_current(stores):
    reviews,goals,db=stores;review=extract(reviews);content=content_of(review);content['skills'][0]['context']='SQL for reporting.'
    changed=save(reviews,review,content);key=str(uuid4())
    first=confirm(reviews,goals,changed,key)
    assert confirm(reviews,goals,changed,key)==first
    goal=first['goal'];restored=reviews.get(goal.id,OWNER)
    assert save(reviews,restored).id==goal.id and db.career_goals.count_documents({'record_type':'requirement_review'})==0
    noop_key=str(uuid4());save(reviews,restored,key=noop_key)
    content=content_of(restored);content['company']='A different edit'
    with pytest.raises(GoalError):save(reviews,restored,content,key=noop_key)
    content=content_of(restored);content['skills'][0]['context']='A temporary refinement.'
    newer=save(reviews,restored,content)
    content['skills'][0]['context']='SQL for reporting.'
    same=save(reviews,newer,content)
    selected=goals.current(OWNER)['goal']
    assert selected.id==goal.id and selected.version==same.version
def test_exploration_metadata_edits_preserve_context_and_reject_employer_conditions(stores):
    reviews,goals,db=stores;stamp=now();identifier='000000000000000000000091'
    goal=CareerGoal(_id=identifier,user_id=OWNER,version=1,skill_mapping_version='skills-v1',created_at=stamp,updated_at=stamp,
       target_type='career_exploration',field='Data',role='Analyst',interests=['Research'],preferences=['Singapore'],requirements_source='career_exploration',generation_version='pending-skills',readiness='pending')
    db.career_goals.insert_one(mongo_document(goal))
    db.career_state.update_one({'_id':OWNER},{'$set':{'goal_id':ObjectId(identifier),'version':0}},upsert=True)
    view=reviews.get(identifier,OWNER);content=content_of(view);content['company']='Example'
    edited=save(reviews,view,content,acknowledge_context=True)
    selected=goals.current(OWNER)['goal']
    assert selected.interests==['Research'] and selected.preferences==['Singapore']
    content=content_of(edited);content['non_skill_requirements']=[OUTPUT['non_skill_requirements'][0]]
    with pytest.raises(GoalError) as rejected:save(reviews,edited,content)
    assert rejected.value.status==422
def test_conflicting_group_rules_and_forged_mapping_cannot_publish(stores):
    reviews,_,_=stores;review=extract(reviews);content=content_of(review)
    content['skills'][0]['skill_id']='forged.sql'
    assert save(reviews,review,content).content.skills[0].skill_id=='language.sql'
    content['non_skill_requirements'][0]['group_operator']='all'
    with pytest.raises(GoalError) as rejected:save(reviews,review,content)
    assert rejected.value.status==422
