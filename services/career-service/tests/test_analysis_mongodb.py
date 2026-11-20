"""Real BSON/index/idempotency tests; always use randomly named disposable DBs."""
import copy
import os
from uuid import uuid4
import pytest
from pymongo import MongoClient
from app.domain.analysis import ContractConflict
from app.repositories.analysis import AnalysisRepository
from app.schemas.analysis import CareerGoal, ResearchSource, mongo_document


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


def test_private_goal_reads_are_owner_scoped(database, documents):
    repo = AnalysisRepository(database); repo.ensure_indexes()
    goal = CareerGoal.model_validate(documents['goal'])
    database.career_goals.insert_one(mongo_document(goal))
    assert repo.get_private('career_goals', goal.id, goal.user_id) == goal
    assert repo.get_private('career_goals', goal.id, '22222222-2222-4222-8222-222222222222') is None
    with pytest.raises(ValueError): repo.get_private('interview_research', goal.id, goal.user_id)


def test_public_research_is_verified_and_idempotent(database, documents):
    repo = AnalysisRepository(database); repo.ensure_indexes()
    data = documents['research']; sources = {s['source_id']: ResearchSource.model_validate(s) for s in data['sources']}
    saved = repo.save_research(data, trusted_sources=sources)
    assert repo.save_research(data, trusted_sources=sources) == saved
    assert database.interview_research.find_one()['context_key'] == saved.context_key
    assert repo.get_research(saved.id) == saved
    duplicate = copy.deepcopy(data); duplicate['_id'] = '000000000000000000000099'
    with pytest.raises(ContractConflict): repo.save_research(duplicate, trusted_sources=sources)
    forged = copy.deepcopy(data); forged['sources'][0]['evidence'] = 'Invented quote'
    with pytest.raises(ContractConflict): repo.save_research(forged, trusted_sources=sources)
