"""Real BSON/index/idempotency tests; always use randomly named disposable DBs."""
import copy
import os
from uuid import uuid4
import pytest
from pymongo import MongoClient
from app.domain.analysis import ContractConflict
from app.repositories.analysis import AnalysisRepository
from app.repositories.exploration import ExplorationRepository
from app.schemas.analysis import CareerGoal, CvSnapshot, InterviewResearch, ResearchSource, ResearchContext


@pytest.fixture
def database():
    uri = os.getenv('MONGODB_TEST_URI')
    if not uri: pytest.skip('Set MONGODB_TEST_URI to a disposable MongoDB.')
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    name = 'elo_analysis_test_' + uuid4().hex
    database = client[name]
    try:
        client.admin.command('ping')
        yield database
    finally:
        client.drop_database(name); client.close()


def test_goal_idempotency_owner_isolation_and_conflicting_retry(database, documents):
    repo = AnalysisRepository(database); repo.ensure_indexes()
    owner = documents['goal']['user_id']
    saved = repo.save_private('career_goals', documents['goal'], owner)
    assert repo.save_private('career_goals', documents['goal'], owner) == saved
    assert database.career_goals.count_documents({}) == 1
    assert repo.get_private('career_goals', saved.id, owner) == saved
    assert repo.get_private('career_goals', saved.id, '22222222-2222-4222-8222-222222222222') is None
    documents['goal']['role'] = 'Changed role'
    with pytest.raises(ContractConflict): repo.save_private('career_goals', documents['goal'], owner)
    assert 'source_text' not in database.career_goals.find_one()


def test_wrong_owner_cannot_create_goal(database, documents):
    with pytest.raises(ContractConflict):
        AnalysisRepository(database).save_private('career_goals', documents['goal'], 'someone-else')
    assert database.career_goals.count_documents({}) == 0


def test_public_research_is_verified_and_reused_by_context(database, documents):
    repo = AnalysisRepository(database); repo.ensure_indexes()
    data = documents['research']; sources = {s['source_id']: ResearchSource.model_validate(s) for s in data['sources']}
    saved = repo.save_research(data, trusted_sources=sources)
    assert repo.save_research(data, trusted_sources=sources) == saved
    assert database.interview_research.find_one()['context_key'] == saved.context_key
    from datetime import datetime, timezone
    context = ResearchContext(field='software', role='ENGINEER')
    assert repo.reusable_research(context, datetime(2025,1,1,tzinfo=timezone.utc), 'skills-v1') == saved
    assert repo.reusable_research(context, datetime(2027,1,1,tzinfo=timezone.utc), 'skills-v1') is None
    assert repo.reusable_research(context, datetime(2025,1,1,tzinfo=timezone.utc), 'other-map') is None
    duplicate = copy.deepcopy(data); duplicate['_id'] = '000000000000000000000099'
    with pytest.raises(ContractConflict): repo.save_research(duplicate, trusted_sources=sources)
    forged = copy.deepcopy(data); forged['sources'][0]['evidence'] = 'Invented quote'
    with pytest.raises(ContractConflict): repo.save_research(forged, trusted_sources=sources)
    with pytest.raises(ValueError): repo.save_private('interview_research', data, documents['goal']['user_id'])


def test_analysis_checks_references_before_persisting(database, documents):
    repo = AnalysisRepository(database); repo.ensure_indexes()
    owner = documents['goal']['user_id']
    cv = CvSnapshot.model_validate(documents['cv']); goal = CareerGoal.model_validate(documents['goal'])
    research = [InterviewResearch.model_validate(documents['research'])]
    with pytest.raises(ContractConflict):
        repo.save_private('skill_gap_analyses', documents['analysis'], owner, cv=None, goal=goal, research=research, profile_version=1)
    assert database.skill_gap_analyses.count_documents({}) == 0
    repo.save_private('career_goals', documents['goal'], owner)
    repo.save_research(documents['research'], trusted_sources={s.source_id:s for s in research[0].sources})
    saved = repo.save_private('skill_gap_analyses', documents['analysis'], owner,
        cv=cv, goal=goal, research=research, profile_version=1)
    assert repo.get_private('skill_gap_analyses', saved.id, owner) == saved
    from bson import ObjectId
    stored = database.skill_gap_analyses.find_one()
    assert isinstance(stored['career_goal_id'], ObjectId)
    assert isinstance(stored['research_ids'][0], ObjectId)
    assert isinstance(stored['inputs']['research'][0]['id'], ObjectId)


def test_private_history_is_versioned_and_does_not_accept_raw_source(database, documents):
    repo = ExplorationRepository(database); repo.ensure_indexes()
    data = {k: v for k, v in documents['goal'].items() if k in
        ('_id', 'user_id', 'version', 'skill_mapping_version', 'created_at', 'updated_at')}
    data['messages'] = [{'role':'user','content':'I enjoy building interfaces.'}]
    owner = data['user_id']
    saved = repo.save('exploration_sessions', data, owner, 0)
    assert repo.save('exploration_sessions', data, owner, 0) == saved
    data['version'] = 2
    repo.save('exploration_sessions', data, owner, 1)
    data['messages'][0]['content'] = 'Conflicting completion'
    with pytest.raises(ContractConflict): repo.save('exploration_sessions', data, owner, 1)
    assert repo.get('exploration_sessions', saved.id, 'foreign') is None
    data['source_text'] = 'Full JD'
    with pytest.raises(ValueError): repo.save('exploration_sessions', data, owner, 1)


def test_terminal_operation_cannot_be_overwritten_and_selected_goal_must_exist(database, documents):
    repo=ExplorationRepository(database)
    base={k:v for k,v in documents['goal'].items() if k in
        ('_id','user_id','version','skill_mapping_version','created_at','updated_at')}
    owner=base['user_id']
    operation={**base,'stage':'chat','status':'cancelled','input_revision':'1'}
    repo.save('ai_operations',operation,owner,0)
    operation.update(version=2,status='running')
    with pytest.raises(ContractConflict): repo.save('ai_operations',operation,owner,1)
    session={**base,'selected_career_goal_id':'000000000000000000000088'}
    with pytest.raises(ContractConflict): repo.save('exploration_sessions',session,owner,0)


def test_successful_operation_persists_only_a_verified_result_reference(database, documents):
    owner=documents['goal']['user_id']
    repo=ExplorationRepository(database)
    base={k:v for k,v in documents['goal'].items() if k in
        ('user_id','skill_mapping_version','created_at','updated_at')}
    data={**base,'_id':'000000000000000000000077','version':1,
          'stage':'extraction','status':'pending','input_revision':'1'}
    repo.save('ai_operations',data,owner,0)
    data.update(version=2,status='succeeded',result_id=documents['goal']['_id'],generation=documents['goal']['generation'])
    with pytest.raises(ContractConflict): repo.save('ai_operations',data,owner,1)
    AnalysisRepository(database).save_private('career_goals',documents['goal'],owner)
    saved=repo.save('ai_operations',data,owner,1)
    assert repo.get('ai_operations',saved.id,owner).generation == saved.generation
