from copy import deepcopy
from uuid import uuid4
import pytest
from app.domain.service import detail, now
from app.domain.errors import Conflict
from tests.conftest import ready, upload, mutation, docx


def test_saved_sparse_upload_reload_and_idempotency(harness):
    client, app, *_ = harness
    key = str(uuid4())
    first = upload(client, docx(['Education: Example University']), mutation_id=key)
    assert first.status_code == 202
    assert first.json()['status'] == 'queued'
    assert upload(client, docx(['Education: Example University']), mutation_id=key).json()['id'] == first.json()['id']
    assert upload(client, docx(['Different file']), mutation_id=key).status_code == 409
    app.state.worker.run_once()
    result = client.get('/api/v1/cv/operations/' + first.json()['operation_id'])
    assert result.status_code == 200
    assert result.json()['status'] == 'ready'
    assert result.json()['skills'] == []
    assert result.json()['items'][0]['kind'] == 'education'
    assert result.headers['cache-control'] == 'no-store'
    assert client.get('/api/v1/cv').json()['selection'] == {'cv_id': None, 'version': 0}
    saved = app.state.repository.get('owner-a', first.json()['id'])
    assert 'blocks' not in saved and 'text' not in saved and 'file_url' not in saved


def test_owner_isolation_revocation_and_onboarding(harness):
    client, app, _, _, profile = harness
    cv = ready(harness)
    client.headers['Authorization'] = 'Bearer owner-b'
    assert client.get('/api/v1/cv').json()['cvs'] == []
    assert client.get('/api/v1/cv/' + cv['id']).status_code == 404
    assert client.get('/api/v1/cv/operations/' + cv['operation_id']).status_code == 404
    assert client.put('/api/v1/cv/selection', json=mutation(0, cv_id=cv['id'])).status_code == 404
    assert client.patch(f"/api/v1/cv/{cv['id']}/items/{cv['items'][0]['id']}", json=mutation(cv['version'], action='remove')).status_code == 404
    profile.onboarding = False
    assert client.get('/api/v1/cv').status_code == 403
    profile.revoked = True
    assert client.get('/api/v1/cv').status_code == 401
    client.headers.pop('Authorization')
    assert client.get('/api/v1/cv').status_code == 401


def test_explicit_selection_failure_preserves_previous_result(harness):
    client, app, extractor, *_ = harness
    first = ready(harness)
    selected = client.put('/api/v1/cv/selection', json=mutation(0, cv_id=first['id'])).json()
    second = upload(client)
    assert second.json()['id'] != first['id']
    assert client.put('/api/v1/cv/selection', json=mutation(selected['version'], cv_id=second.json()['id'])).status_code == 409
    extractor.failure = 'Synthetic processing failure'
    app.state.worker.run_once()
    assert client.get('/api/v1/cv').json()['selection']['cv_id'] == first['id']
    assert client.get('/api/v1/cv/' + first['id']).json()['items'] == first['items']
    failed = client.get('/api/v1/cv/' + second.json()['id']).json()
    assert failed['status'] == 'failed' and failed['error']['retryable']
    extractor.failure = None
    request = mutation(failed['version'])
    assert client.post('/api/v1/cv/operations/' + failed['operation_id'] + '/retry', json=request).status_code == 200
    assert client.post('/api/v1/cv/operations/' + failed['operation_id'] + '/retry', json=request).status_code == 200
    app.state.worker.run_once()
    assert client.get('/api/v1/cv').json()['selection']['cv_id'] == first['id']


def test_corrections_noops_replay_stale_write_and_reprocessing(harness):
    client, app, *_ = harness
    cv = ready(harness)
    item = cv['items'][1]
    path = f"/api/v1/cv/{cv['id']}/items/{item['id']}"
    unchanged = client.patch(path, json=mutation(cv['version'], action='update', title=item['title'])).json()
    assert unchanged['version'] == cv['version'] and unchanged['effective_version'] == cv['effective_version']
    request = mutation(cv['version'], action='update', description='I built the Python API with supervision.')
    edited = client.patch(path, json=request).json()
    assert edited['version'] > cv['version']
    assert edited['items'][1]['provenance'] == 'user_corrected'
    assert client.patch(path, json=request).json()['version'] == edited['version']
    assert client.patch(path, json=mutation(cv['version'], action='remove')).status_code == 409
    removed = client.patch(path, json=mutation(edited['version'], action='remove')).json()
    assert removed['items'][1]['removed']
    repeated = client.patch(path, json=mutation(removed['version'], action='remove')).json()
    assert repeated['effective_version'] == removed['effective_version']
    queued = upload(client, cv_id=cv['id'], expected_version=removed['version'])
    assert queued.status_code == 202, queued.text
    app.state.worker.run_once()
    reprocessed = client.get('/api/v1/cv/' + cv['id']).json()
    assert reprocessed['items'][1]['removed']
    assert reprocessed['extraction_version'] == 2
    assert reprocessed['effective_version'] == removed['effective_version']
    assert upload(client, docx(['different']), cv_id=cv['id'], expected_version=reprocessed['version']).status_code == 409
    assert app.state.repository.get('owner-a', cv['id'])['history']


def test_invalid_known_months_and_blank_edits(harness):
    client, *_ = harness
    cv = ready(harness)
    path = f"/api/v1/cv/{cv['id']}/items/{cv['items'][0]['id']}"
    for changes in ({'experience_months': -1}, {'experience_months': True}, {'experience_months': '12'}, {'title': ' '}, {'title': None}):
        assert client.patch(path, json=mutation(cv['version'], action='update', **changes)).status_code == 422
    assert client.patch(path, json=mutation(cv['version'], action='update', experience_months=None)).status_code == 200


def test_capability_snapshot_selection_and_declaration_races(harness):
    client, app, _, _, profile = harness
    cv = ready(harness)
    path = f"/api/v1/cv/{cv['id']}/capability-input?expected_version={cv['version']}&expected_selection_version=1&expected_declarations_version=1"
    assert client.get(path).status_code == 409
    client.put('/api/v1/cv/selection', json=mutation(0, cv_id=cv['id']))
    result = client.get(path)
    assert result.status_code == 200, result.text
    assert result.json()['declarations'][0]['name'] == 'Pandas'
    assert result.json()['cv_id'] == cv['id']
    immutable = deepcopy(result.json())
    project = cv['items'][1]
    client.patch(f"/api/v1/cv/{cv['id']}/items/{project['id']}", json=mutation(cv['version'], action='remove'))
    assert client.get(path).status_code == 409
    assert immutable['items'][1]['removed'] is False
    cv = client.get('/api/v1/cv/' + cv['id']).json()
    profile.race, profile.calls = True, 0
    path = f"/api/v1/cv/{cv['id']}/capability-input?expected_version={cv['version']}&expected_selection_version=1&expected_declarations_version=2"
    assert client.get(path).status_code == 409


def test_expired_lease_recovery_fencing_and_cleanup(harness):
    client, app, *_ = harness
    response = upload(client).json()
    repo, worker = app.state.repository, app.state.worker
    original = repo.get('owner-a', response['id'])
    old_claim = worker.claim(original)
    expired = deepcopy(old_claim)
    expired['operation']['lease_until'] = now() - 1
    expired['revision'] += 1
    repo.replace(old_claim, expired)
    new_claim = worker.claim(expired)
    assert worker.process(old_claim) is False
    assert worker.process(new_claim) is True
    ready_doc = repo.get('owner-a', response['id'])
    assert ready_doc['operation']['status'] == 'ready'
    expiring = deepcopy(ready_doc)
    expiring['original_expires_at'] = now() - 1
    expiring['revision'] += 1
    repo.replace(ready_doc, expiring)
    worker.cleanup()
    cleaned = client.get('/api/v1/cv/' + response['id']).json()
    assert cleaned['source_available'] is False
    assert not app.state.files.exists(response['id'])
    assert cleaned['items']
    # Expired source may be resupplied with exact bytes, retaining stable CV ID.
    queued = upload(client, cv_id=response['id'], expected_version=cleaned['version'])
    assert queued.status_code == 202
    worker.run_once()
    assert client.get('/api/v1/cv/' + response['id']).json()['status'] == 'ready'


def test_model_failure_does_not_publish_partial_extraction(harness):
    client, app, extractor, *_ = harness
    extractor.payload = {'items': [{'kind': 'skill', 'title': 'Invented', 'description': 'invalid source', 'explicit': True,
        'evidence': [{'block_id': 'b1', 'excerpt': 'never appeared'}]}]}
    cv = upload(client).json()
    app.state.worker.run_once()
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert result['status'] == 'failed'
    assert result['items'] == [] and result['extraction_version'] == 0


def test_explicit_skill_rename_preserves_claim_identity(harness):
    client, *_ = harness
    cv = ready(harness)
    item = cv['items'][2]
    result = client.patch(f"/api/v1/cv/{cv['id']}/items/{item['id']}", json=mutation(cv['version'], action='update', title='Python')).json()
    renamed = next(current for current in result['items'] if current['id'] == item['id'])
    assert renamed['skill_ids'] == ['skill:python'] and renamed['skill_names'] == ['Python']
    python = next(skill for skill in result['skills'] if skill['skill_id'] == 'skill:python')
    assert len(python['item_ids']) == 2
    assert len(set(python['item_ids'])) == 2
    assert result['original_items'][2]['title'] == 'SQL'


def test_same_source_changed_interpretation_requires_reconciliation(harness):
    client, app, extractor, *_ = harness
    cv = ready(harness)
    item = cv['items'][1]
    corrected = client.patch(f"/api/v1/cv/{cv['id']}/items/{item['id']}", json=mutation(cv['version'], action='remove')).json()
    extractor.payload = {'items': [{'kind': 'education', 'title': 'Example University', 'description': 'Computing degree',
        'explicit': True, 'evidence': [{'block_id': 'b1', 'excerpt': 'Education: Example University, Computing'}]}]}
    assert upload(client, cv_id=cv['id'], expected_version=corrected['version']).status_code == 202
    app.state.worker.run_once()
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert result['status'] == 'failed' and result['error']['code'] == 'reconciliation_required'
    assert result['items'][1]['removed'] is True
    assert result['extraction_version'] == cv['extraction_version']
    assert result['reconciliation']


def test_cleanup_recovers_after_file_deleted_before_tracking(harness, monkeypatch):
    client, app, *_ = harness
    cv = ready(harness)
    repo = app.state.repository
    original = repo.get('owner-a', cv['id'])
    expired = deepcopy(original)
    expired['original_expires_at'] = now()-1
    expired['revision'] += 1
    repo.replace(original, expired)
    replace = repo.replace
    def fail_tracking(previous, document):
        if previous.get('cleanup_token') and not document.get('cleanup_token'):
            raise RuntimeError('Synthetic process interruption before deletion tracking')
        return replace(previous, document)
    monkeypatch.setattr(repo, 'replace', fail_tracking)
    with pytest.raises(RuntimeError): app.state.worker.cleanup()
    assert not app.state.files.exists(cv['id'])
    assert repo.get('owner-a', cv['id'])['original_available'] is True
    monkeypatch.setattr(repo, 'replace', replace)
    app.state.worker.cleanup()
    assert repo.get('owner-a', cv['id'])['original_available'] is False


def test_concurrent_corrections_have_single_winner(harness):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.schemas.cv import ItemMutation
    client, app, *_ = harness
    cv = ready(harness)
    gate = Barrier(2)
    def edit(title):
        gate.wait()
        try:
            app.state.service.edit('owner-a', cv['id'], cv['items'][0]['id'],
                ItemMutation(**mutation(cv['version'], action='update', title=title)))
            return 'saved'
        except Conflict: return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ['First corrected title', 'Second corrected title']))
    assert sorted(results) == ['conflict', 'saved']
    assert app.state.repository.get('owner-a', cv['id'])['effective_version'] == cv['effective_version'] + 1


def test_upload_enforces_exact_file_limit_and_actual_format(harness):
    from dataclasses import replace
    from app.main import create_app
    from fastapi.testclient import TestClient
    client, app, extractor, targets, _ = harness
    settings = replace(app.state.settings, max_file_bytes=2048)
    small = create_app(repository=app.state.repository, profile_client=app.state.profile_client,
        extractor=extractor, target_provider=targets, settings=settings, start_worker=False)
    with TestClient(small) as limited:
        limited.headers['Authorization'] = 'Bearer owner-a'
        exact = docx().ljust(2048, b' ')
        response = upload(limited, exact)
        assert response.status_code == 202
        small.state.worker.run_once()
        assert limited.get('/api/v1/cv/' + response.json()['id']).json()['status'] == 'ready'
        assert upload(limited, exact + b' ').status_code == 413
        assert upload(limited, b'fake PDF', name='resume.pdf').status_code == 422
        assert upload(limited, b'plain text').status_code == 422
        assert limited.get('/api/v1/cv/policy').json()['max_file_bytes'] == 2048


def test_new_worker_recovers_persisted_queued_job(harness):
    from app.workers.ingestion import IngestionWorker
    client, app, extractor, *_ = harness
    accepted = upload(client).json()
    replacement_worker = IngestionWorker(app.state.repository, app.state.files, app.state.settings, extractor)
    replacement_worker.run_once()
    result = client.get('/api/v1/cv/operations/' + accepted['operation_id']).json()
    assert result['status'] == 'ready'


def test_full_edit_form_only_applies_changed_numeric_fields(harness):
    client, app, extractor, *_ = harness
    extractor.payload = {'items': [{'kind': 'skill', 'title': 'SQL',
        'description': 'Independent SQL queries for a personal dataset.', 'explicit': True,
        'evidence': [{'block_id': 'b3', 'excerpt': 'Independent SQL queries for a personal dataset.'}]}]}
    cv = ready(harness)
    item = cv['items'][0]
    path = f"/api/v1/cv/{cv['id']}/items/{item['id']}"
    # Match the current edit form: unchanged title/description are sent alongside
    # actual numeric/proficiency changes, and must not trigger text side effects.
    edited = client.patch(path, json=mutation(cv['version'], action='update', title=item['title'],
        description=item['description'], proficiency='basic', experience_months=6)).json()
    saved_item = edited['items'][0]
    assert saved_item['title'] == item['title'] and saved_item['description'] == item['description']
    assert saved_item['evidence'] == item['evidence']
    assert saved_item['support_uncertain'] is False
    assert saved_item['proficiency'] == 'basic' and saved_item['experience_months'] == 6
    assert edited['skills'][0]['proficiency'] == 'basic' and edited['skills'][0]['experience_months'] == 6
    client.put('/api/v1/cv/selection', json=mutation(0, cv_id=cv['id']))
    inputs = client.get(f"/api/v1/cv/{cv['id']}/capability-input?expected_version={edited['version']}&expected_selection_version=1&expected_declarations_version=1")
    assert inputs.status_code == 200
    assert inputs.json()['skills'][0]['experience_months'] == 6
    assert inputs.json()['skills'][0]['proficiency'] == 'basic'
    noop = client.patch(path, json=mutation(edited['version'], action='update', title=item['title'],
        description=item['description'], proficiency='basic', experience_months=6)).json()
    assert noop['version'] == edited['version'] and noop['effective_version'] == edited['effective_version']
    changed_months = client.patch(path, json=mutation(edited['version'], action='update', title=item['title'],
        description=item['description'], proficiency='basic', experience_months=12)).json()
    assert changed_months['items'][0]['evidence'] == item['evidence']
    assert changed_months['skills'][0]['experience_months'] == 12
