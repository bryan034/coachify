"""Canonical goal acknowledgement: CAS, revisions and owner isolation."""
from copy import deepcopy
from datetime import datetime,timezone
from threading import RLock
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from app.confirmation.service import CvConfirmationService,project
from app.main import create_app
from app.repositories.goals import GoalError
from app.schemas.analysis import CareerGoal,mongo_document
from app.schemas.cv_confirmation import ConfirmCvGoal

OWNER='11111111-1111-4111-8111-111111111111'
OTHER='22222222-2222-4222-8222-222222222222'
ID='000000000000000000000001'
BASE='/api/v1/career/goals'


def goal(**changes):
    stamp=datetime(2026,1,1,tzinfo=timezone.utc)
    return CareerGoal(_id=ID,user_id=OWNER,version=1,skill_mapping_version='skills-v1',created_at=stamp,updated_at=stamp,
        target_type='specific_job',field='Analytics',role='Data analyst',requirements_source='pasted_jd',
        generation_version='fixture',readiness='pending',skills=[{'name':'Python','category':'technical','priority':'required','origin':'employer','evidence':'Use Python.'}],**changes)


class Rows:
    def __init__(self,documents=()):self.rows={d['_id']:deepcopy(d) for d in documents};self.lock=RLock();self.hook=None
    def find_one(self,query):
        with self.lock:
            row=self.rows.get(query.get('_id'))
            return deepcopy(row) if row and all(row.get(k)==v for k,v in query.items()) else None
    def update_one(self,query,update):
        with self.lock:
            row=self.rows.get(query['_id'])
            if not row:return SimpleNamespace(matched_count=0)
            for key,value in query.items():
                if key=='cv_confirmation_receipts.key':
                    if any(r['key']==value['$ne'] for r in row.get('cv_confirmation_receipts',[])):return SimpleNamespace(matched_count=0)
                elif row.get(key)!=value:return SimpleNamespace(matched_count=0)
            row.update(deepcopy(update.get('$set',{})))
            for key,value in update.get('$push',{}).items():row[key]=(row.get(key,[])+deepcopy(value['$each']))[value['$slice']:]
            if self.hook:self.hook()
            return SimpleNamespace(matched_count=1)


def service(value=None):
    value=value or goal()
    goals=Rows([mongo_document(value)])
    state=Rows([{'_id':OWNER,'version':3,'goal_id':ObjectId(value.id)}])
    return CvConfirmationService(SimpleNamespace(goals=goals,state=state))


def mutation(**changes):
    return ConfirmCvGoal(expected_goal_id=ID,expected_goal_version=1,expected_selection_version=3,mutation_id=str(uuid4()),**changes)


def test_auto_saved_goal_is_not_confirmed_until_explicit_acknowledgement():
    repo=service();before=repo.view(OWNER)
    assert before=={'goal_id':ID,'goal_version':1,'selection_version':3,'confirmed':False,'context':None,'reason':None}
    saved=repo.confirm(OWNER,mutation())
    assert saved['confirmed'] and saved['context']['skill_ids']==['skill:python']
    assert repo.state.rows[OWNER]['version']==3
    assert repo.goals.goals.rows[ObjectId(ID)]['version']==1
    assert repo.context(OWNER,ID,1)==saved['context']


def test_retries_are_exact_and_revision_changes_invalidate_confirmation():
    repo=service();body=mutation();saved=repo.confirm(OWNER,body)
    assert repo.confirm(OWNER,body)==saved
    assert len(repo.state.rows[OWNER]['cv_confirmation_receipts'])==1
    repo.goals.goals.rows[ObjectId(ID)]['version']=2
    assert not repo.view(OWNER)['confirmed'] and repo.context(OWNER) is None
    with pytest.raises(GoalError):repo.confirm(OWNER,body)
    with pytest.raises(GoalError):repo.context(OWNER,ID,1)


def test_reselection_and_unversioned_content_changes_invalidate_stamp():
    repo=service();repo.confirm(OWNER,mutation());repo.state.rows[OWNER]['version']=4
    assert repo.context(OWNER) is None
    repo.state.rows[OWNER]['version']=3;repo.goals.goals.rows[ObjectId(ID)]['role']='Changed role'
    assert repo.context(OWNER) is None


def test_goal_change_during_acknowledgement_cannot_publish_confirmed_context():
    repo=service()
    repo.state.hook=lambda:repo.goals.goals.rows[ObjectId(ID)].update(version=2)
    with pytest.raises(GoalError):repo.confirm(OWNER,mutation())
    assert repo.context(OWNER) is None


def test_owner_isolation_and_blocked_requirement_review():
    repo=service();assert repo.view(OTHER)['goal_id'] is None
    with pytest.raises(GoalError):repo.confirm(OTHER,mutation())
    repo.goals.goals.rows[ObjectId(ID)]['requirements_need_review']=True
    assert repo.view(OWNER)['reason']
    with pytest.raises(GoalError):repo.confirm(OWNER,mutation())


def test_projection_preserves_large_requirements_and_generic_conditions():
    value=goal();raw=value.model_dump(by_alias=True,mode='json')
    raw['skills']=[{'name':f'Skill {i}','category':'technical','priority':'required','origin':'employer','evidence':'Required.'} for i in range(200)]
    raw['non_skill_requirements']=[{'requirement_id':f'req-{i}','category':'eligibility' if i else 'qualification',
        'description':'A Computer Science degree is required.' if i==0 else 'Eligibility '+str(i)+'.',
        'priority':'required','evidence':'A supported requirement.','group_id':'alternatives','group_operator':'any'} for i in range(100)]
    context=project(CareerGoal.model_validate(raw),3)
    assert len(context['skill_ids'])==200 and len(context['conditions'])==100
    assert context['conditions'][0]['kind']=='qualification'
    assert context['conditions'][1]['kind']=='requirement'
    assert context['conditions'][1]['source_category']=='eligibility'
    assert context['conditions'][1]['description']=='Eligibility 1.'
    assert context['conditions'][1]['group_operator']=='any'


def test_reused_mutation_key_cannot_confirm_a_different_selection():
    repo=service();body=mutation();repo.confirm(OWNER,body)
    repo.state.rows[OWNER]['version']=4
    changed=ConfirmCvGoal.model_validate({**body.model_dump(mode='json'),'expected_selection_version':4})
    with pytest.raises(GoalError,match='different details'):repo.confirm(OWNER,changed)


def test_api_requires_auth_and_default_app_has_no_legacy_target_writes(monkeypatch):
    monkeypatch.delenv('MONGODB_URI',raising=False)
    def profile(request):return httpx.Response(200,json={'id':OWNER,'email_verified':True} if request.url.path.endswith('/session') else {'onboarding_complete':True})
    with TestClient(create_app(profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as client:
        assert client.get(BASE+'/current/cv-confirmation').status_code==401
        assert client.get(BASE+'/current/cv-confirmation',headers={'Authorization':'Bearer owner'}).status_code==503
        assert client.post('/api/v1/career/targets',json={}).status_code==404
        assert client.post(BASE+'/current/cv-confirmation',json={'expected_goal_id':'bad'},headers={'Authorization':'Bearer owner'}).status_code==422


def test_http_confirmation_uses_explicit_exact_revision_and_hides_foreign_context(monkeypatch):
    monkeypatch.delenv('MONGODB_URI',raising=False)
    def profile(request):
        who=OTHER if request.headers.get('authorization')=='Bearer other' else OWNER
        return httpx.Response(200,json={'id':who,'email_verified':True} if request.url.path.endswith('/session') else {'onboarding_complete':True})
    repo=service()
    with TestClient(create_app(profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))) as client:
        client.app.state.goal_store=repo.goals
        client.headers.update({'Authorization':'Bearer owner'})
        assert client.get(BASE+'/current/confirmed-context').json() is None
        body=mutation().model_dump(mode='json')
        saved=client.post(BASE+'/current/cv-confirmation',json=body)
        assert saved.status_code==200,saved.text
        assert saved.json()['confirmed'] and saved.json()['reason'] is None
        assert saved.headers['cache-control']=='no-store'
        assert client.post(BASE+'/current/cv-confirmation',json=body).json()==saved.json()
        assert client.get(BASE+'/'+ID+'/confirmed-context?expected_version=1').json()==saved.json()['context']
        assert client.get(BASE+'/'+ID+'/confirmed-context?expected_version=2').status_code==409
        assert client.get(BASE+'/current/confirmed-context',headers={'Authorization':'Bearer other'}).json() is None
        assert client.post(BASE+'/current/cv-confirmation',json=body,headers={'Authorization':'Bearer other'}).status_code==409


def test_canonical_storage_keys_preserve_retired_unique_index_without_record_migration(documents):
    first=CareerGoal.model_validate(documents['goal'])
    second=first.model_copy(update={'id':'000000000000000000000099'})
    assert mongo_document(first)['create_key']=='canonical:'+first.id
    assert mongo_document(second)['create_key']!=mongo_document(first)['create_key']
    assert 'create_key' not in first.model_dump()


def test_existing_legacy_unique_index_allows_multiple_new_goals_and_drafts(documents):
    import os
    from pymongo import MongoClient
    from app.repositories.goals import GoalStore
    from app.repositories.targets import TargetRepository
    from app.schemas.goals import CvContext
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Set MONGODB_TEST_URI for isolated index coexistence test.')
    mongo=MongoClient(uri,serverSelectionTimeoutMS=3000,tz_aware=True)
    name='elo_confirmation_test_'+uuid4().hex
    db=mongo[name]
    try:
        mongo.admin.command('ping')
        TargetRepository(db) # Deliberately install the pre-upgrade unique index.
        first=CareerGoal.model_validate(documents['goal']);owner=first.user_id
        historical={'_id':str(uuid4()),'user_id':owner,'create_key':str(uuid4()),'role':'Historical target'}
        db.career_goals.insert_one(deepcopy(historical))
        store=GoalStore(db);store.ensure_indexes()
        store.persist_target(first)
        second=first.model_copy(update={'id':'000000000000000000000099'})
        store.persist_target(second)
        draft=store.start(owner,str(uuid4()),{'consent':True},CvContext())
        assert store.draft(draft.id,owner)==draft
        assert db.career_goals.find_one({'_id':historical['_id']})==historical
        assert {g.id for g in store.list(owner)['goals']}=={first.id,second.id}
        assert db.career_goals.index_information()['user_id_1_create_key_1']['unique'] is True
        store.state.insert_one({'_id':owner,'version':1,'goal_id':ObjectId(first.id)})
        acknowledgement=CvConfirmationService(store)
        body=ConfirmCvGoal(expected_goal_id=first.id,expected_goal_version=first.version,
            expected_selection_version=1,mutation_id=str(uuid4()))
        saved=acknowledgement.confirm(owner,body)
        assert saved['confirmed'] and acknowledgement.confirm(owner,body)==saved
        assert len(store.state.find_one({'_id':owner})['cv_confirmation_receipts'])==1
        store.state.update_one({'_id':owner},{'$set':{'goal_id':ObjectId(second.id)},'$inc':{'version':1}})
        assert acknowledgement.context(owner) is None
        with pytest.raises(GoalError):acknowledgement.confirm(owner,body)
    finally:
        mongo.drop_database(name);mongo.close()


def test_confirmation_detects_changed_requirement_details_without_a_version_bump():
    repo=service();repo.confirm(OWNER,mutation())
    repo.goals.goals.rows[ObjectId(ID)]['skills'][0]['required_experience_months']=12
    assert repo.context(OWNER) is None


@pytest.mark.parametrize('description,subjects',[
    ('A Computer Science diploma is required.',['Computer Science']),
    ("A bachelor's degree in Computer Science is required.",['Computer Science']),
    ('A Computer Science or Information Systems diploma is preferred.',['Computer Science','Information Systems']),
    ('A degree in Mathematics or a related discipline is required.',['Mathematics']),
])
def test_qualification_projection_retains_exact_subject_without_claiming_credential(description,subjects):
    value=goal();raw=value.model_dump(by_alias=True,mode='json')
    raw['non_skill_requirements']=[{'requirement_id':'qualification-one','category':'qualification',
        'description':description,'evidence':description,'priority':'required'}]
    context=project(CareerGoal.model_validate(raw),3)
    condition=context['conditions'][0]
    assert set(subjects)<=set(condition['match_terms'])
    assert condition['description']==condition['evidence']==description
    assert condition['item_kinds']==['education'] and condition['kind']=='qualification'
    assert len(condition['match_terms'])<=7
    assert 'qualification_met' not in condition and 'resolution' not in condition


def test_generic_eligibility_projection_stays_exact_after_subject_matching_repair():
    value=goal();raw=value.model_dump(by_alias=True,mode='json')
    description='Singapore citizenship is required.'
    raw['non_skill_requirements']=[{'requirement_id':'eligibility-one','category':'eligibility',
        'description':description,'evidence':description,'priority':'required'}]
    condition=project(CareerGoal.model_validate(raw),3)['conditions'][0]
    assert condition['match_terms']==[description] and condition['kind']=='requirement'
