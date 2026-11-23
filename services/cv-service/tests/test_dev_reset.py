"""Development reset releases private files and account-scoped upload capacity."""
from copy import deepcopy
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from tests.conftest import docx, ready, select, upload
from tests.test_storage_capacity import limits


@pytest.fixture(autouse=True)
def development(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'development')


@pytest.fixture
def reset_harness(harness):
    if not hasattr(harness[1].state.repository, 'collection'):
        pytest.skip('Development reset requires the MongoDB repository.')
    return harness


def test_reset_releases_capacity_and_preserves_other_accounts(reset_harness):
    client, app, *_ = reset_harness
    cvs = [ready(reset_harness) for _ in range(3)]
    select(client, cvs[0]['id'])
    chat = client.post('/api/v1/cv/conversations', json={
        'cv_id': cvs[0]['id'], 'mutation_id': cvs[0]['id']}).json()
    assert upload(client).status_code == 409
    client.headers['Authorization'] = 'Bearer owner-b'
    other = upload(client).json()
    other_entry = deepcopy(app.state.service.capacity.entry(other['id']))
    client.headers['Authorization'] = 'Bearer owner-a'

    response = client.post('/api/v1/cv/dev/reset')

    assert response.status_code == 200, response.text
    assert response.json()['deleted']['cvs'] == 3
    assert response.json()['deleted']['cv_upload_capacity'] == 3
    assert client.get('/api/v1/cv').json()['cvs'] == []
    assert client.get('/api/v1/cv').json()['selection']['cv_id'] is None
    assert client.get('/api/v1/cv/conversations/' + chat['id']).status_code == 404
    assert all(not app.state.files.exists(cv['id']) for cv in cvs)
    assert app.state.repository.collection.count_documents({'user_id': 'owner-a'}) == 0
    assert app.state.repository.admission.read()['entries'] == {other['id']: other_entry}
    assert app.state.files.exists(other['id'])
    assert client.post('/api/v1/cv/dev/reset').json() == {'deleted': {}}
    assert [upload(client).status_code for _ in range(4)] == [202, 202, 202, 409]
    client.headers['Authorization'] = 'Bearer owner-b'
    assert client.get('/api/v1/cv/' + other['id']).status_code == 200


def test_reset_repairs_capacity_left_by_an_earlier_reset(reset_harness):
    client, app, *_ = reset_harness
    cvs = [upload(client).json() for _ in range(3)]
    app.state.repository.collection.delete_many({'user_id': 'owner-a'})
    for cv in cvs[:2]: app.state.files.remove(cv['id'])
    assert client.get('/api/v1/cv').json()['cvs'] == []
    assert upload(client).status_code == 409

    response = client.post('/api/v1/cv/dev/reset')

    assert response.status_code == 200, response.text
    assert response.json()['deleted']['cv_upload_capacity'] == 3
    assert app.state.repository.admission.read()['entries'] == {}
    assert list(app.state.files.storage_files()) == []
    assert upload(client).status_code == 202


def test_reset_restores_original_byte_capacity(reset_harness):
    client, app, *_ = reset_harness
    limits(app, max_original_bytes_per_owner=len(docx()))
    assert upload(client).status_code == 202
    denied = upload(client)
    assert denied.status_code == 409 and 'private upload storage is full' in denied.json()['detail']

    assert client.post('/api/v1/cv/dev/reset').status_code == 200

    assert upload(client).status_code == 202


def test_failed_file_cleanup_keeps_capacity_until_reset_is_retried(reset_harness, monkeypatch):
    client, app, *_ = reset_harness
    cv = upload(client).json()
    entry = deepcopy(app.state.service.capacity.entry(cv['id']))
    remove = app.state.files.remove
    def fail(identifier):
        raise OSError('Synthetic file removal failure')
    monkeypatch.setattr(app.state.files, 'remove', fail)

    response = client.post('/api/v1/cv/dev/reset')

    assert response.status_code == 503
    assert app.state.files.exists(cv['id'])
    assert app.state.service.capacity.entry(cv['id']) == entry
    monkeypatch.setattr(app.state.files, 'remove', remove)
    assert client.post('/api/v1/cv/dev/reset').status_code == 200
    assert app.state.service.capacity.entry(cv['id']) is None
    assert not app.state.files.exists(cv['id'])
    assert upload(client).status_code == 202


def test_reset_requires_authentication(reset_harness):
    client, app, *_ = reset_harness
    cv = upload(client).json()
    client.headers.pop('Authorization')
    assert client.post('/api/v1/cv/dev/reset').status_code == 401
    assert app.state.files.exists(cv['id'])
    assert app.state.service.capacity.entry(cv['id']) is not None


def test_quota_cleanup_preserves_a_live_upload(harness):
    client, app, *_ = harness
    cv = upload(client).json()
    entry = deepcopy(app.state.service.capacity.entry(cv['id']))

    assert app.state.service.capacity.reset_deleted_owner('owner-a', [cv['id']]) == 0

    assert app.state.service.capacity.entry(cv['id']) == entry
    assert app.state.files.exists(cv['id'])
    assert client.get('/api/v1/cv/' + cv['id']).status_code == 200


def test_quota_cleanup_retries_cas_without_losing_another_accounts_upload(reset_harness, monkeypatch):
    client, app, *_ = reset_harness
    cv = upload(client).json()
    replace = app.state.repository.admission.replace
    concurrent = []
    def upload_before_replace(previous, document):
        if not concurrent:
            concurrent.append(None)
            concurrent[0] = app.state.service.upload('owner-b', 4, 'synthetic.docx', 'docx', docx(), str(uuid4()))
        return replace(previous, document)
    monkeypatch.setattr(app.state.repository.admission, 'replace', upload_before_replace)

    response = client.post('/api/v1/cv/dev/reset')

    assert response.status_code == 200, response.text
    other = concurrent[0]
    assert app.state.service.capacity.entry(cv['id']) is None
    assert list(app.state.repository.admission.read()['entries']) == [other['_id']]
    assert app.state.files.read(other['_id']) == docx()
    assert app.state.repository.get('owner-b', other['_id']) is not None


def test_reset_is_absent_outside_development(reset_harness, monkeypatch):
    _, app, *_ = reset_harness
    monkeypatch.setenv('APP_ENV', 'production')
    with TestClient(create_app(repository=app.state.repository, settings=app.state.settings,
                               start_worker=False)) as client:
        assert client.post('/api/v1/cv/dev/reset').status_code == 404
