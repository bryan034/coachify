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
    assert value.extraction.repair_attempts is None and value.extraction.response_mode is None
    assert 'file_url' not in value.model_dump() and 'user_id' not in value.model_dump()


def test_failure_diagnostics_openapi_matches_runtime(harness):
    _, app, *_ = harness
    artifact = Path(__file__).resolve().parents[3] / 'contracts/api/cv.yaml'
    contract = json.loads(artifact.read_text())['components']['schemas']
    for name in ('ErrorInfo', 'ExtractionMetadata', 'CvDetail', 'ReconciliationView', 'InterviewProgress', 'InterviewTopic', 'CvSummary', 'ProcessingProgress', 'ActiveQuestion', 'ConversationSend'):
        assert app.openapi()['components']['schemas'][name] == contract[name]


def test_deletion_contract_matches_runtime(harness):
    _, app, *_ = harness
    artifact = Path(__file__).resolve().parents[3] / 'contracts/api/cv.yaml'
    contract = json.loads(artifact.read_text())
    runtime = app.openapi()
    assert contract['paths']['/api/v1/cv/{cv_id}']['delete'] == runtime['paths']['/api/v1/cv/{cv_id}']['delete']
    assert contract['components']['schemas']['CvDeletionResult'] == runtime['components']['schemas']['CvDeletionResult']


def test_deletion_error_descriptions_are_stable_on_python_312(monkeypatch, harness):
    from http import HTTPStatus
    from app.main import create_app
    monkeypatch.setattr(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, 'phrase', 'Request Entity Too Large')
    monkeypatch.setattr(HTTPStatus.UNPROCESSABLE_ENTITY, 'phrase', 'Unprocessable Entity')
    app = create_app(settings=harness[1].state.settings)
    responses = app.openapi()['paths']['/api/v1/cv/{cv_id}']['delete']['responses']
    assert responses['413']['description'] == 'Content Too Large'
    assert responses['422']['description'] == 'Unprocessable Content'


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


def test_processing_progress_is_saved_and_visible_during_extraction(harness):
    from tests.conftest import upload
    client, app, extractor, *_ = harness
    cv = upload(client).json()
    assert cv['processing_progress'] == {'stage': 'queued', 'percent': 0, 'message': 'Upload saved. Waiting to start.'}
    original_parse, original_extract = app.state.worker.parser, extractor.extract
    observed = []

    def capture():
        value = client.get('/api/v1/cv/' + cv['id']).json()['processing_progress']
        observed.append(value)
        listed = client.get('/api/v1/cv').json()['cvs'][0]
        assert listed['processing_progress'] == value

    def parse(*args):
        capture()
        return original_parse(*args)

    def extract(*args, **kwargs):
        capture()
        return original_extract(*args, **kwargs)

    app.state.worker.parser, extractor.extract = parse, extract
    app.state.worker.run_once()
    assert [value['stage'] for value in observed] == ['document_parse', 'model_request']
    assert [value['percent'] for value in observed] == [25, 45]
    completed = client.get('/api/v1/cv/' + cv['id']).json()
    assert completed['status'] == 'ready', completed
    assert completed['processing_progress']['percent'] == 100


def test_saved_cv_response_maps_each_skill_to_a_display_group_without_changing_the_skill():
    value = CvDetail.model_validate(fixture())
    assert set(value.skill_groups) == {skill.name for skill in value.skills}
    assert all(group for group in value.skill_groups.values())
    assert 'skill_groups' not in value.skills[0].model_dump()
