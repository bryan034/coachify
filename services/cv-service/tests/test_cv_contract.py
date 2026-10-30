"""Public saved-CV contract and storage guarantees after Career integration."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4
import pytest
from pydantic import ValidationError
from app.domain.errors import Conflict
from app.schemas.cv import CvDetail, ItemMutation
from tests.conftest import ready


def fixture():
    return json.loads((Path(__file__).parent / 'cv.json').read_text())


def test_authoritative_cv_schema_describes_the_public_saved_cv_response():
    artifact = Path(__file__).resolve().parents[3] / 'contracts/api/models/cv.schema.json'
    assert CvDetail.model_json_schema() == json.loads(artifact.read_text())
    value = CvDetail.model_validate(fixture())
    assert value.status == 'ready'
    assert value.skills[0].proficiency is None
    assert 'file_url' not in value.model_dump() and 'user_id' not in value.model_dump()


@pytest.mark.parametrize('changes', [
    {'user_id': 'not-uuid'}, {'file_url': 'https://public.test/cv.pdf'},
    {'source_text': 'private raw CV'}, {'extraction_status': 'failed'},
    {'expected_version': True},
])
def test_invalid_cv_write_controls_are_rejected(changes, harness):
    client, *_ = harness
    cv = ready(harness)
    body = {'expected_version': cv['version'], 'mutation_id': str(uuid4()),
            'action': 'update', 'title': 'A deliberate correction', **changes}
    with pytest.raises(ValidationError): ItemMutation.model_validate(body)
    before = client.get('/api/v1/cv/' + cv['id']).json()
    result = client.patch('/api/v1/cv/' + cv['id'] + '/items/' + cv['items'][0]['id'], json=body)
    assert result.status_code == 422
    assert client.get('/api/v1/cv/' + cv['id']).json() == before


def test_cv_repository_roundtrip_idempotency_and_private_owner_isolation(harness):
    _, app, *_ = harness
    cv = ready(harness)
    repo = app.state.repository
    original = repo.get('owner-a', cv['id'])
    assert repo.insert(deepcopy(original)) == original
    assert repo.get('owner-a', cv['id']) == original
    assert repo.get('owner-b', cv['id']) is None
    assert len(repo.list('owner-a')) == 1
    conflicting = deepcopy(original)
    conflicting['upload_fingerprint'] = 'different synthetic file fingerprint'
    with pytest.raises(Conflict): repo.insert(conflicting)
    assert len(repo.list('owner-a')) == 1
    assert repo.get('owner-a', cv['id']) == original


def test_cv_skill_adds_shared_identity_without_rewriting_source_key():
    from app.schemas.cv import CvSkill
    value=CvSkill(skill_id='skill:structured query language',name='Structured Query Language',category='unspecified',
        proficiency=None,experience_months=None,context=None,evidence=[],evidence_type='user_clarified',explicit=False,item_ids=[],sources=[])
    assert value.canonical_skill_id=='language.sql'
    assert value.skill_id=='skill:structured query language'
    assert value.skill_registry_version=='skills-v2'
