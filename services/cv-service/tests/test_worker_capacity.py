"""A full history or one poison record must not stop another owner's work."""
from copy import deepcopy
from bson import BSON
import pytest
from app.domain.errors import CvError
from app.domain.service import HISTORY_LIMIT_BYTES, OPERATIONAL_ALLOWANCE_BYTES, bump, now
from tests.conftest import ready, upload
from tests.test_storage_capacity import expire, limits, send, SimulatedCrash


def fill_history(repository, identifier, remaining=20):
    previous = repository.get('owner-a', identifier)
    document = deepcopy(previous)
    document['history'].append({'retained_synthetic_history': ''})
    document['history'][-1]['retained_synthetic_history'] = 'x' * (HISTORY_LIMIT_BYTES - remaining - len(BSON.encode(document)))
    document['revision'] += 1
    return repository.replace(previous, document)


def test_near_limit_history_does_not_block_expired_original_deletion(harness):
    client, app, *_ = harness
    full = ready(harness)
    fill_history(app.state.repository, full['id'])
    expire(app.state.repository, 'owner-a', full['id'])
    other = send(app.state.service, 'owner-b')
    expire(app.state.repository, 'owner-b', other['_id'])
    before = app.state.repository.get('owner-a', full['id'])
    app.state.worker.cleanup()
    after = app.state.repository.get('owner-a', full['id'])
    assert after['original_available'] is False
    assert after['history'] == before['history'] and after['original_items'] == before['original_items']
    assert app.state.repository.get('owner-b', other['_id'])['original_available'] is False
    assert not app.state.files.exists(full['id']) and not app.state.files.exists(other['_id'])
    assert all(entry['bytes'] == 0 for entry in app.state.repository.admission.read()['entries'].values())
    assert client.get('/api/v1/cv/' + full['id']).status_code == 200


def test_operational_allowance_is_not_user_or_extraction_capacity():
    document = {'revision': 1, 'version': 1, 'updated_at': 0.0, 'history': ''}
    document['history'] = 'x' * (HISTORY_LIMIT_BYTES + 100 - len(BSON.encode(document)))
    with pytest.raises(CvError): bump(deepcopy(document), visible=False)
    operational = deepcopy(document)
    bump(operational, operational=True)
    assert len(BSON.encode(operational)) <= HISTORY_LIMIT_BYTES + OPERATIONAL_ALLOWANCE_BYTES
    operational['history'] += 'x' * OPERATIONAL_ALLOWANCE_BYTES
    with pytest.raises(CvError): bump(operational, operational=True)


def test_oversized_extraction_saves_bounded_failure_and_preserves_prior_evidence(harness):
    client, app, *_ = harness
    cv = ready(harness)
    padded = fill_history(app.state.repository, cv['id'], remaining=800)
    request = upload(client, cv_id=cv['id'], expected_version=padded['version'])
    assert request.status_code == 202, request.text
    other = send(app.state.service, 'owner-b')
    # A requeued CV may be before the saved sweep cursor; the next bounded
    # sweep still must publish its failure and process the other owner's source.
    app.state.worker.run_once()
    app.state.worker.run_once()
    result = app.state.repository.get('owner-a', cv['id'])
    assert result['operation']['status'] == 'failed'
    assert result['operation']['error']['code'] == 'history_capacity'
    assert result['original_items'] == padded['original_items']
    assert result['history'] == padded['history']
    assert result['operation']['lease_token'] is None
    assert app.state.repository.get('owner-b', other['_id'])['operation']['status'] == 'ready'


def test_cleanup_crash_after_unlink_keeps_quota_until_recovery(harness, monkeypatch):
    _, app, *_ = harness
    saved = send(app.state.service)
    expire(app.state.repository, 'owner-a', saved['_id'])
    remove = app.state.files.remove
    def crash_after_remove(identifier):
        remove(identifier)
        raise SimulatedCrash()
    monkeypatch.setattr(app.state.files, 'remove', crash_after_remove)
    with pytest.raises(SimulatedCrash): app.state.worker.cleanup()
    assert not app.state.files.exists(saved['_id'])
    assert app.state.service.capacity.entry(saved['_id'])['bytes'] > 0
    monkeypatch.setattr(app.state.files, 'remove', remove)
    app.state.worker.cleanup()
    assert app.state.service.capacity.entry(saved['_id'])['bytes'] == 0
    assert app.state.repository.get('owner-a', saved['_id'])['original_available'] is False


def test_cleanup_advances_past_a_full_page_of_poison_records(harness, monkeypatch):
    _, app, *_ = harness
    limits(app, max_saved_cvs_per_owner=200, max_saved_cvs_global=200)
    records = [send(app.state.service) for _ in range(101)]
    for record in records: expire(app.state.repository, 'owner-a', record['_id'])
    ordered = sorted(record['_id'] for record in records)
    poisoned = set(ordered[:100])
    replace = app.state.repository.replace
    def fail_poison(previous, document):
        if previous['_id'] in poisoned: raise RuntimeError('Synthetic persistent storage failure')
        return replace(previous, document)
    monkeypatch.setattr(app.state.repository, 'replace', fail_poison)
    app.state.worker.cleanup()
    assert app.state.files.exists(ordered[-1])
    app.state.worker.cleanup()
    assert not app.state.files.exists(ordered[-1])
    assert app.state.repository.get('owner-a', ordered[-1])['original_available'] is False
    assert all(app.state.files.exists(identifier) for identifier in poisoned)


def test_ingestion_advances_past_a_full_page_of_poison_records(harness, monkeypatch):
    _, app, *_ = harness
    records = [send(app.state.service) for _ in range(11)]
    ordered = sorted(record['_id'] for record in records)
    poisoned = set(ordered[:10])
    claim = app.state.worker.claim
    def fail_poison(candidate):
        if candidate['_id'] in poisoned: raise RuntimeError('Synthetic invalid legacy record')
        return claim(candidate)
    monkeypatch.setattr(app.state.worker, 'claim', fail_poison)
    app.state.worker.run_once()
    app.state.worker.run_once()
    assert app.state.repository.get('owner-a', ordered[-1])['operation']['status'] == 'ready'
    assert all(app.state.repository.get('owner-a', identifier)['operation']['status'] == 'queued' for identifier in poisoned)


def test_worker_candidate_pages_exclude_retained_history(harness):
    _, app, *_ = harness
    saved = send(app.state.service)
    assert app.state.repository.candidates(now()) == [{'_id': saved['_id'], 'user_id': 'owner-a'}]
    expire(app.state.repository, 'owner-a', saved['_id'])
    assert app.state.repository.cleanup_candidates(now()) == [{'_id': saved['_id'], 'user_id': 'owner-a'}]
