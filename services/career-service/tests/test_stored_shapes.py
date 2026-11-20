"""The one-off stored-shape upgrade against a disposable MongoDB."""
import os
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from bson import ObjectId
from pymongo import MongoClient

from app.domain.discovery_conversation import INTRODUCTION
from app.repositories.goals import GoalStore, now
from app.repositories.question_memory import VERIFIED_EVIDENCE
from app.repositories.stored_shapes import RETIRED_INTRODUCTIONS, StoredShapes, current_understanding
from app.schemas.analysis import CareerGoal
from app.schemas.goals import CvContext
from app.schemas.opportunity import CATEGORIES, SUMMARY_UNAVAILABLE, CategoryResult
from app.workers.upgrade_stored_shapes import main

OWNER = '00000000-0000-4000-8000-000000000001'
OTHER = '00000000-0000-4000-8000-000000000002'


@pytest.fixture
def db():
    uri = os.getenv('MONGODB_TEST_URI')
    if not uri:
        pytest.skip('Requires disposable MongoDB')
    mongo = MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)
    database = mongo['elo_stored_shapes_test_' + uuid4().hex]
    try:
        yield database
    finally:
        mongo.drop_database(database.name)
        mongo.close()


def seed(db, documents):
    stamp = now()
    db.career_goals.create_index([('user_id', 1), ('create_key', 1)], unique=True)
    db.career_goals.create_index([('user_id', 1), ('created_at', -1), ('_id', -1)])
    historical = {'_id': str(uuid4()), 'user_id': OWNER, 'create_key': str(uuid4()), 'role': 'Historical target'}
    db.career_goals.insert_one(deepcopy(historical))
    goal = CareerGoal.model_validate(documents['goal'])
    db.career_goals.insert_one({'_id': ObjectId(goal.id), 'user_id': OWNER, 'create_key': 'canonical:' + goal.id,
                                'baseline': {'role': 'Old'}, 'baseline_origins': {}, 'updated_at': stamp - timedelta(days=2)})
    db.research_contexts.insert_many([
        {'_id': 'chat-old', 'kind': 'career_discovery', 'owner': OWNER, 'created_at': stamp - timedelta(days=3),
         'messages': [{'role': 'assistant', 'content': RETIRED_INTRODUCTIONS[1]}, {'role': 'user', 'content': 'Hi'}],
         'decision': {'understanding': {'broad_exploration': {'status': 'known', 'value': 'yes', 'evidence': 'Keep it broad'},
                                        'industry': {'status': 'known', 'value': 'Finance'},
                                        'field': {'status': 'known', 'value': 'Data'}}}},
        {'_id': 'chat-new', 'kind': 'career_discovery', 'owner': OWNER, 'created_at': stamp - timedelta(days=1),
         'messages': [{'role': 'assistant', 'content': INTRODUCTION}], 'decision': None},
        {'_id': 'chat-other', 'kind': 'career_discovery', 'owner': OTHER, 'created_at': stamp - timedelta(days=5), 'messages': []},
        {'_id': 'job-old', 'kind': 'opportunity_job', 'finished': False, 'requested': [],
         'categories': {'interview_intelligence': {**CategoryResult(status='completed').model_dump(mode='json'),
                                                   'findings': [{'field': 'recruitment_stages'}, {'field': 'retired_field'}]},
                        'internship_insights': CategoryResult(status='completed').model_dump(mode='json'),
                        'company_intelligence': CategoryResult(status='completed').model_dump(mode='json')}},
    ])
    db.career_state.insert_many([{'_id': OWNER, 'version': 1, 'goal_id': ObjectId(goal.id)},
                                 {'_id': OTHER, 'version': 0, 'goal_id': None, 'active_discovery': 'chat-other'}])
    verified, unverified = ObjectId(), ObjectId()
    db.interview_research.insert_many([{'_id': verified, 'generation': {'prompt_version': VERIFIED_EVIDENCE}},
                                       {'_id': unverified, 'generation': {'prompt_version': 'saved-question-evidence-v1'}},
                                       {'_id': ObjectId(), 'intelligence': {'schema_version': 1, 'categories': {}}},
                                       {'_id': ObjectId(), 'intelligence': {'schema_version': 2, 'categories': {}, 'warnings': [SUMMARY_UNAVAILABLE]}}])
    db.research_contexts.insert_many([{'_id': 'question-result:kept', 'kind': 'question_result', 'research_id': str(verified)},
                                      {'_id': 'question-result:stale', 'kind': 'question_result', 'research_id': str(unverified)}])
    return goal, historical


EXPECTED = {'retired_goal_indexes': 2, 'goal_storage_keys': 1, 'review_baselines': 1, 'discovery_introductions': 2,
            'discovery_understanding': 1, 'active_discoveries': 1, 'first_opportunity_reports': 1, 'summary_flags': 1,
            'unfinished_opportunity_jobs': 1, 'unverified_question_results': 1}


def test_dry_run_counts_without_writing(db, documents):
    seed(db, documents)
    before = {name: list(db[name].find()) for name in db.list_collection_names()}
    assert StoredShapes(db).upgrade() == EXPECTED
    assert {name: list(db[name].find()) for name in db.list_collection_names()} == before
    assert 'user_id_1_create_key_1' in db.career_goals.index_information()


def test_apply_rewrites_old_records_once_and_keeps_historical_targets(db, documents):
    goal, historical = seed(db, documents)
    assert StoredShapes(db).upgrade(apply=True) == EXPECTED
    assert StoredShapes(db).upgrade() == dict.fromkeys(EXPECTED, 0)

    assert not {'user_id_1_create_key_1', 'user_id_1_created_at_-1__id_-1'} & set(db.career_goals.index_information())
    assert db.career_goals.find_one({'_id': historical['_id']}) == historical
    stored = db.career_goals.find_one({'_id': ObjectId(goal.id)})
    assert set(stored) == {'_id', 'user_id', 'updated_at'}

    old = db.research_contexts.find_one({'_id': 'chat-old'})
    assert old['messages'] == [{'role': 'user', 'content': 'Hi'}]
    assert old['decision']['understanding'] == {'field': {'status': 'known', 'value': 'Data'},
        'role_family_or_work': {'status': 'known', 'value': 'keep it broad', 'evidence': 'Keep it broad'}}
    assert db.research_contexts.find_one({'_id': 'chat-new'})['messages'] == []
    assert db.career_state.find_one({'_id': OWNER})['active_discovery'] == 'chat-new'
    assert db.career_state.find_one({'_id': OTHER})['active_discovery'] == 'chat-other'

    job = db.research_contexts.find_one({'_id': 'job-old'})
    assert set(job['categories']) == set(CATEGORIES)
    assert job['categories']['interview_intelligence']['findings'] == [{'field': 'recruitment_stages'}]
    assert job['categories']['interview_intelligence']['status'] == 'pending'
    assert set(job['requested']) == {'career_progression', 'conversion_outcomes'}

    assert db.interview_research.count_documents({'intelligence.schema_version': 1}) == 0
    assert db.interview_research.count_documents({'intelligence.schema_version': 2, 'intelligence.summary_unavailable': True}) == 1
    assert [row['_id'] for row in db.research_contexts.find({'kind': 'question_result'})] == ['question-result:kept']


def test_new_goals_and_drafts_save_after_the_retired_index_is_dropped(db, documents):
    seed(db, documents)
    StoredShapes(db).upgrade(apply=True)
    store = GoalStore(db)
    store.ensure_indexes()
    first = CareerGoal.model_validate({**documents['goal'], '_id': str(ObjectId())})
    store.persist_target(first)
    store.persist_target(first.model_copy(update={'id': str(ObjectId())}))
    draft = store.start(OWNER, str(uuid4()), {'consent': True}, CvContext())
    assert store.draft(draft.id, OWNER) == draft


def test_a_newer_goal_from_another_chat_keeps_the_owner_unadopted(db, documents):
    seed(db, documents)
    db.career_goals.update_one({'user_id': OWNER, '_id': {'$type': 'objectId'}}, {'$set': {'updated_at': now()}})
    assert StoredShapes(db).active_discoveries(apply=True) == 0
    assert 'active_discovery' not in db.career_state.find_one({'_id': OWNER})


def test_broad_exploration_does_not_replace_a_specific_answered_role():
    understanding = {'broad_exploration': {'status': 'known', 'value': 'yes'}, 'industry': {'status': 'known'},
                     'role_family_or_work': {'status': 'known', 'value': 'Data analyst'}, 'field': {'status': 'known', 'value': 'Data'}}
    assert current_understanding(understanding) == {'role_family_or_work': {'status': 'known', 'value': 'Data analyst'},
                                                    'field': {'status': 'known', 'value': 'Data'}}


def test_worker_prints_counts_and_writes_only_with_apply(db, documents, monkeypatch, capsys):
    seed(db, documents)
    monkeypatch.setenv('MONGODB_URI', os.environ['MONGODB_TEST_URI'])
    monkeypatch.setenv('MONGODB_DATABASE', db.name)
    main([])
    assert '"applied": false' in capsys.readouterr().out
    assert db.career_goals.count_documents({'create_key': {'$exists': True}}) == 2
    main(['--apply'])
    assert '"applied": true' in capsys.readouterr().out
    assert db.career_goals.count_documents({'create_key': {'$exists': True}}) == 1
