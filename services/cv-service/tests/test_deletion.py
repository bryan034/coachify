"""Deletion erases CV content, fences writers and recovers across resource failures."""
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4
import pytest
from pymongo.errors import AutoReconnect
from app.schemas.cv import Mutation, SelectionMutation
from app.domain.errors import Conflict
from tests.conftest import docx, ready, upload, mutation
from tests.test_storage_capacity import reset_ledger


def remove(client, cv, **fields):
    return client.request('DELETE', '/api/v1/cv/' + cv['id'], json=mutation(cv['version'], **fields))


def test_delete_selected_cv_erases_content_chats_file_and_capacity(harness):
    client, app, *_ = harness
    cv = ready(harness)
    selected = client.put('/api/v1/cv/selection', json=mutation(0, cv_id=cv['id'])).json()
    chat = client.post('/api/v1/cv/conversations', json={'cv_id': cv['id'], 'mutation_id': str(uuid4())}).json()
    manual = client.post('/api/v1/cv/conversations', json={'cv_id': None, 'mutation_id': str(uuid4())}).json()
    manual_version = harness[4].declaration_version
    response = remove(client, cv)
    assert response.status_code == 200, response.text
    assert response.json() == {'cv_id': cv['id'], 'deleted': True,
        'selection': {'cv_id': None, 'version': selected['version'] + 1}}
    assert response.headers['cache-control'] == 'no-store'
    assert client.get('/api/v1/cv').json()['cvs'] == []
    assert client.get('/api/v1/cv/' + cv['id']).status_code == 404
    assert client.get('/api/v1/cv/operations/' + cv['operation_id']).status_code == 404
    assert client.get('/api/v1/cv/conversations/' + chat['id']).status_code == 404
    assert client.get('/api/v1/cv/conversations/' + manual['id']).status_code == 200
    assert harness[4].declaration_version == manual_version
    assert not app.state.files.exists(cv['id'])
    assert cv['id'] not in app.state.repository.admission.read()['entries']
    receipt = app.state.repository.get_for_deletion('owner-a', cv['id'])
    assert receipt['deletion']['state'] == 'complete'
    assert not ({'file_name', 'source_hash', 'original_items', 'overlays', 'clarifications',
                 'history', 'extraction', 'candidate', 'prepared_context'} & receipt.keys())


def test_delete_retry_is_idempotent_and_does_not_clear_new_selection(harness):
    client, app, *_ = harness
    first, second = ready(harness), ready(harness)
    selected = client.put('/api/v1/cv/selection', json=mutation(0, cv_id=first['id'])).json()
    request = mutation(first['version'])
    path = '/api/v1/cv/' + first['id']
    assert client.request('DELETE', path, json=request).status_code == 200
    selected = client.put('/api/v1/cv/selection', json=mutation(selected['version'] + 1, cv_id=second['id'])).json()
    again = client.request('DELETE', path, json=request)
    assert again.status_code == 200 and again.json()['selection'] == selected
    assert client.get('/api/v1/cv').json()['selection'] == selected
    assert app.state.files.exists(second['id'])


def test_delete_requires_owner_authentication_version_and_valid_identifier(harness):
    client, app, _, _, profile = harness
    cv = ready(harness)
    assert remove(client, {**cv, 'version': cv['version'] - 1}).status_code == 409
    client.headers['Authorization'] = 'Bearer owner-b'
    assert remove(client, cv).status_code == 404
    client.headers['Authorization'] = 'Bearer owner-a'
    assert client.request('DELETE', '/api/v1/cv/not-a-uuid', json=mutation(1)).status_code == 422
    assert remove(client, {**cv, 'id': str(uuid4())}).status_code == 404
    profile.onboarding = False
    assert remove(client, cv).status_code == 403
    profile.revoked = True
    assert remove(client, cv).status_code == 401
    assert app.state.files.exists(cv['id']) and app.state.repository.get('owner-a', cv['id']) is not None


@pytest.mark.parametrize('state', ['queued', 'failed', 'expired'])
def test_delete_queued_failed_and_expired_originals(harness, state):
    client, app, extractor, *_ = harness
    cv = upload(client).json()
    if state != 'queued':
        if state == 'failed': extractor.failure = 'Synthetic provider failure'
        app.state.worker.run_once()
        cv = client.get('/api/v1/cv/' + cv['id']).json()
    if state == 'expired':
        old = app.state.repository.get('owner-a', cv['id'])
        changed = deepcopy(old)
        changed['original_expires_at'] = 0
        changed['revision'] += 1
        app.state.repository.replace(old, changed)
        app.state.worker.cleanup()
        cv = client.get('/api/v1/cv/' + cv['id']).json()
    assert remove(client, cv).status_code == 200
    app.state.worker.run_once()
    assert client.get('/api/v1/cv/' + cv['id']).status_code == 404


def test_delete_during_extraction_fences_late_publication(harness, monkeypatch):
    client, app, extractor, *_ = harness
    queued = upload(client).json()
    extract = extractor.extract
    def finish_after_delete(blocks, **kwargs):
        current = app.state.repository.get('owner-a', queued['id'])
        app.state.service.deletion.delete('owner-a', queued['id'], Mutation(**mutation(current['version'])))
        return extract(blocks, **kwargs)
    monkeypatch.setattr(extractor, 'extract', finish_after_delete)
    app.state.worker.run_once()
    assert client.get('/api/v1/cv/' + queued['id']).status_code == 404
    assert app.state.repository.get_for_deletion('owner-a', queued['id'])['deletion']['state'] == 'complete'
    assert not app.state.files.exists(queued['id'])


def test_inflight_edit_cannot_resurrect_tombstone(harness):
    client, app, *_ = harness
    cv = ready(harness)
    old = app.state.repository.get('owner-a', cv['id'])
    assert remove(client, cv).status_code == 200
    stale = deepcopy(old)
    stale['revision'] += 1
    with pytest.raises(Conflict): app.state.repository.replace(old, stale)


def test_file_failure_hides_content_and_worker_recovers(harness, monkeypatch):
    client, app, *_ = harness
    cv = ready(harness)
    original = app.state.files.remove
    def fail(*args): raise OSError('Synthetic filesystem outage')
    monkeypatch.setattr(app.state.files, 'remove', fail)
    assert remove(client, cv).status_code == 503
    assert client.get('/api/v1/cv/' + cv['id']).status_code == 404
    assert app.state.repository.get_for_deletion('owner-a', cv['id'])['deletion']['state'] == 'pending'
    assert cv['id'] in app.state.repository.admission.read()['entries']
    monkeypatch.setattr(app.state.files, 'remove', original)
    app.state.worker.run_once()
    assert not app.state.files.exists(cv['id'])
    assert cv['id'] not in app.state.repository.admission.read()['entries']
    assert remove(client, cv).status_code == 200


def test_quota_release_interruption_recovers_without_double_credit(harness, monkeypatch):
    client, app, *_ = harness
    cv = ready(harness)
    release = app.state.service.capacity.release_deleted_record
    def fail(*args): raise AutoReconnect('Synthetic quota acknowledgement outage')
    monkeypatch.setattr(app.state.service.capacity, 'release_deleted_record', fail)
    assert remove(client, cv).status_code == 503
    assert app.state.repository.get_for_deletion('owner-a', cv['id'])['deletion']['state'] == 'complete'
    assert app.state.repository.admission.read()['entries'][cv['id']]['state'] == 'deleting'
    monkeypatch.setattr(app.state.service.capacity, 'release_deleted_record', release)
    app.state.worker.run_once()
    assert cv['id'] not in app.state.repository.admission.read()['entries']
    assert remove(client, cv).status_code == 200


def test_lost_tombstone_acknowledgement_is_recovered(harness, monkeypatch):
    client, app, *_ = harness
    cv = ready(harness)
    write = app.state.repository.replace
    def lose_ack(previous, document):
        saved = write(previous, document)
        if document.get('deletion', {}).get('state') == 'pending': raise AutoReconnect('Synthetic committed acknowledgement loss')
        return saved
    monkeypatch.setattr(app.state.repository, 'replace', lose_ack)
    assert remove(client, cv).status_code == 503
    monkeypatch.setattr(app.state.repository, 'replace', write)
    app.state.worker.run_once()
    assert not app.state.files.exists(cv['id']) and cv['id'] not in app.state.repository.admission.read()['entries']


def test_deletion_preserves_concurrently_selected_other_cv(harness, monkeypatch):
    client, app, *_ = harness
    first, second = ready(harness), ready(harness)
    client.put('/api/v1/cv/selection', json=mutation(0, cv_id=first['id']))
    remove_file = app.state.files.remove
    def switch_then_remove(identifier):
        app.state.service.select('owner-a', SelectionMutation(**mutation(1, cv_id=second['id'])))
        remove_file(identifier)
    monkeypatch.setattr(app.state.files, 'remove', switch_then_remove)
    result = remove(client, first)
    assert result.status_code == 200 and result.json()['selection'] == {'cv_id': second['id'], 'version': 2}


def test_deleted_upload_receipt_blocks_recreation_and_releases_capacity(harness):
    client, app, *_ = harness
    settings = replace(app.state.settings, max_saved_cvs_per_owner=1)
    app.state.service.capacity.settings = settings
    key = str(uuid4())
    cv = upload(client, mutation_id=key).json()
    assert remove(client, cv).status_code == 200
    assert upload(client, mutation_id=key).status_code == 409
    assert upload(client, cv_id=cv['id'], expected_version=cv['version']).status_code == 404
    assert client.get('/api/v1/cv').json()['cvs'] == []
    reset_ledger(app.state.repository)
    app.state.service.capacity.ensure()
    replacement = upload(client)
    assert replacement.status_code == 202 and replacement.json()['id'] != cv['id']
    assert len(app.state.repository.admission.read()['entries']) == 1
