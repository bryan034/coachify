import json
import os
from pathlib import Path
from uuid import uuid4
import pytest
from pydantic import ValidationError
from pymongo import MongoClient
from app.schemas.cv import CvSnapshot
from app.repositories.cvs import CvRepository


def fixture():
    return json.loads((Path(__file__).parent / 'cv.json').read_text())


def test_authoritative_cv_schema_matches_career_wire_snapshot():
    artifact = Path(__file__).resolve().parents[3] / 'contracts/api/models/cv.schema.json'
    assert CvSnapshot.model_json_schema(by_alias=True) == json.loads(artifact.read_text())
    assert CvSnapshot.model_validate(fixture()).skills[0].proficiency is None


@pytest.mark.parametrize('changes', [{'user_id':'not-uuid'}, {'file_url':'https://public.test/cv.pdf'},
    {'source_text':'private raw CV'}, {'extraction_status':'failed'}, {'version':True}])
def test_invalid_cv_records_are_rejected(changes):
    with pytest.raises(ValidationError): CvSnapshot.model_validate({**fixture(), **changes})


def test_cv_mongo_roundtrip_and_private_owner_isolation():
    uri = os.getenv('MONGODB_TEST_URI')
    if not uri: pytest.skip('Set MONGODB_TEST_URI to a disposable MongoDB.')
    client = MongoClient(uri, serverSelectionTimeoutMS=3000)
    name = 'coachify_cv_test_' + uuid4().hex
    try:
        client.admin.command('ping')
        repo = CvRepository(client[name]); repo.ensure_indexes()
        data = fixture(); owner = data['user_id']
        record = repo.save(data, owner)
        assert repo.save(data, owner) == record
        assert repo.get(record.id, owner) == record
        assert repo.get(record.id, 'foreign') is None
        data['file_name'] = 'changed.txt'
        with pytest.raises(ValueError): repo.save(data, owner)
        assert client[name].cvs.count_documents({}) == 1
    finally:
        client.drop_database(name); client.close()
