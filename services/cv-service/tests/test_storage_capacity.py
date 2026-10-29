"""Storage admission across requests, crashes, retries and real Mongo CAS."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import os
import multiprocessing
from threading import Event
from uuid import uuid4
import pytest
from pymongo.errors import AutoReconnect
from app.domain.errors import Conflict
from app.domain.service import CvService, now
from app.domain.storage import CapacityError, CapacityUnavailable, UploadCapacity
from app.repositories.files import FileStore
from tests.conftest import docx, mutation, ready, upload


def limits(app, **values):
    settings = replace(app.state.settings, **values)
    app.state.settings = app.state.service.settings = settings
    app.state.service.capacity.settings = app.state.worker.settings = settings
    return settings


def send(service, owner='owner-a', key=None, data=None):
    return service.upload(owner, 4, 'synthetic.docx', 'docx', data or docx(), key or str(uuid4()))


def expire(repository, owner, identifier):
    original = repository.get(owner, identifier)
    changed = deepcopy(original)
    changed.update(original_expires_at=now() - 1, revision=original['revision'] + 1)
    return repository.replace(original, changed)


def reset_ledger(repository):
    ledger = repository.admission
    if hasattr(ledger, 'collection'): ledger.collection.delete_one({'_id': 'uploads'})
    else: ledger.document = None


def test_parallel_owner_and_global_admission_is_bounded(harness):
    _, app, *_ = harness
    limits(app, max_saved_cvs_per_owner=3, max_saved_cvs_global=4)
    other = CvService(app.state.repository, FileStore(app.state.settings.storage_path), app.state.settings)
    def attempt(index):
        try: return send(app.state.service if index % 2 else other)['_id']
        except CapacityError: return None
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(8)))
    assert len([value for value in results if value]) == 3
    send(other, 'owner-b')
    with pytest.raises(CapacityError): send(other, 'owner-b')
    ledger = app.state.repository.admission.read()
    assert len(ledger['entries']) == 4
    assert sum(entry['bytes'] for entry in ledger['entries'].values()) == 4 * len(docx())
    assert len(list(app.state.files.originals())) == 4


def test_parallel_duplicate_upload_reuses_identity_and_capacity(harness):
    _, app, *_ = harness
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: send(app.state.service, key=key)['_id'], range(12)))
    assert len(set(results)) == 1
    assert len(app.state.repository.admission.read()['entries']) == 1
    assert len(list(app.state.files.originals())) == 1
    with pytest.raises(Conflict): send(app.state.service, key=key, data=docx(['A different synthetic source']))
    assert app.state.files.read(results[0]) == docx()


def test_expiry_releases_bytes_but_preserves_saved_record_limit(harness):
    client, app, *_ = harness
    limits(app, max_saved_cvs_per_owner=2, max_original_bytes_per_owner=len(docx()))
    first = upload(client)
    assert first.status_code == 202
    denied = upload(client)
    assert denied.status_code == 409 and denied.json()['code'] == 'cv_capacity_exceeded'
    expire(app.state.repository, 'owner-a', first.json()['id'])
    app.state.worker.cleanup()
    second = upload(client)
    assert second.status_code == 202
    expire(app.state.repository, 'owner-a', second.json()['id'])
    app.state.worker.cleanup()
    denied = upload(client)
    assert denied.status_code == 409 and 'saved CV limit' in denied.json()['detail']
    assert len(app.state.repository.admission.read()['entries']) == 2
    assert all(entry['bytes'] == 0 for entry in app.state.repository.admission.read()['entries'].values())


class SimulatedCrash(BaseException):
    pass


@pytest.mark.parametrize('stage', ['reserved', 'partial-file', 'published-file', 'inserted-record'])
def test_restart_recovers_every_upload_publication_boundary(harness, monkeypatch, stage):
    _, app, *_ = harness
    service, repo, files = app.state.service, app.state.repository, app.state.files
    key = str(uuid4())
    write, insert, commit = files.write, repo.insert, service.capacity.commit
    def interrupted_write(identifier, data):
        if stage == 'partial-file': files.temporary(identifier).write_bytes(data[:20])
        raise SimulatedCrash()
    def interrupted_insert(document): raise SimulatedCrash()
    def interrupted_commit(identifier, generation): raise SimulatedCrash()
    if stage in {'reserved', 'partial-file'}: monkeypatch.setattr(files, 'write', interrupted_write)
    elif stage == 'published-file': monkeypatch.setattr(repo, 'insert', interrupted_insert)
    else: monkeypatch.setattr(service.capacity, 'commit', interrupted_commit)
    with pytest.raises(SimulatedCrash): send(service, key=key)
    assert len(repo.admission.read()['entries']) == 1
    monkeypatch.setattr(files, 'write', write)
    monkeypatch.setattr(repo, 'insert', insert)
    monkeypatch.setattr(service.capacity, 'commit', commit)
    restarted = CvService(repo, FileStore(files.root), app.state.settings)
    restarted.capacity.recover()
    if stage == 'inserted-record':
        entry = next(iter(repo.admission.read()['entries'].values()))
        assert entry['record'] and entry['state'] == 'published' and entry['bytes'] == len(docx())
        assert len(list(files.originals())) == 1
    else:
        assert repo.admission.read()['entries'] == {}
        assert list(files.storage_files()) == []
    saved = send(restarted, key=key)
    assert saved['original_available'] and files.read(saved['_id']) == docx()
    assert len(repo.admission.read()['entries']) == 1


def test_ambiguous_insert_acknowledgement_never_deletes_committed_original(harness, monkeypatch):
    _, app, *_ = harness
    service, repo = app.state.service, app.state.repository
    insert = repo.insert
    def lost_ack(document):
        insert(document)
        raise AutoReconnect('Synthetic acknowledgement loss')
    monkeypatch.setattr(repo, 'insert', lost_ack)
    key = str(uuid4())
    with pytest.raises(AutoReconnect): send(service, key=key)
    committed = repo.by_upload_key('owner-a', key)
    assert app.state.files.read(committed['_id']) == docx()
    assert repo.admission.read()['entries'][committed['_id']]['record']
    monkeypatch.setattr(repo, 'insert', insert)
    assert send(service, key=key)['_id'] == committed['_id']
    assert len(repo.admission.read()['entries']) == 1


def test_recovery_cannot_release_a_live_writer(harness, monkeypatch):
    _, app, *_ = harness
    started, release = Event(), Event()
    write = app.state.files.write
    def delayed_write(identifier, data):
        started.set()
        assert release.wait(5)
        write(identifier, data)
    monkeypatch.setattr(app.state.files, 'write', delayed_write)
    other = UploadCapacity(app.state.repository, FileStore(app.state.files.root), app.state.settings)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(send, app.state.service)
        assert started.wait(5)
        other.recover()
        entry = next(iter(app.state.repository.admission.read()['entries'].values()))
        assert entry['state'] == 'pending' and entry['bytes'] == len(docx())
        release.set()
        saved = future.result(timeout=5)
    assert app.state.files.read(saved['_id']) == docx()


def test_expired_generation_cannot_release_resupplied_bytes(harness):
    client, app, *_ = harness
    cv = ready(harness)
    old = app.state.repository.admission.read()['entries'][cv['id']]['generation']
    stale_candidate = expire(app.state.repository, 'owner-a', cv['id'])
    app.state.worker.cleanup()
    current = client.get('/api/v1/cv/' + cv['id']).json()
    supplied = upload(client, cv_id=cv['id'], expected_version=current['version'])
    assert supplied.status_code == 202
    entry = app.state.service.capacity.entry(cv['id'])
    assert entry['generation'] != old
    with app.state.files.lock(cv['id']), pytest.raises(CapacityUnavailable):
        app.state.service.capacity.release_bytes(cv['id'], old)
    assert app.state.service.capacity.entry(cv['id'])['bytes'] == len(docx())
    # A stale cleanup query must re-read expiry and cannot remove the new original.
    original_query = app.state.repository.cleanup_candidates
    app.state.repository.cleanup_candidates = lambda timestamp, after=None: [stale_candidate]
    try: app.state.worker.cleanup()
    finally: app.state.repository.cleanup_candidates = original_query
    assert app.state.files.read(cv['id']) == docx()


def test_legacy_overlimit_records_remain_readable_and_selected(harness):
    client, app, *_ = harness
    cvs = [ready(harness) for _ in range(3)]
    client.put('/api/v1/cv/selection', json=mutation(0, cv_id=cvs[0]['id']))
    for cv in cvs:
        original = app.state.repository.get('owner-a', cv['id'])
        legacy = deepcopy(original)
        legacy.pop('storage_generation')
        legacy.pop('source_bytes')
        legacy['revision'] += 1
        app.state.repository.replace(original, legacy)
    reset_ledger(app.state.repository)
    settings = limits(app, max_saved_cvs_per_owner=1, max_saved_cvs_global=2)
    restarted = CvService(app.state.repository, app.state.files, settings)
    assert len(restarted.capacity.ledger.read()['entries']) == 3
    with pytest.raises(CapacityError): send(restarted)
    assert all(client.get('/api/v1/cv/' + cv['id']).status_code == 200 for cv in cvs)
    page = client.get('/api/v1/cv', params={'limit': 1}).json()
    assert page['selection']['cv_id'] == cvs[0]['id']
    assert page['cvs'][0]['id'] != cvs[0]['id']
    seen = [page['cvs'][0]['id']]
    while page['next_cursor']:
        page = client.get('/api/v1/cv', params={'limit': 1, 'cursor': page['next_cursor']}).json()
        seen.extend(cv['id'] for cv in page['cvs'])
    assert set(seen) == {cv['id'] for cv in cvs}


def test_legacy_untracked_and_partial_files_remain_charged_until_removed(harness):
    _, app, *_ = harness
    original, partial = str(uuid4()), str(uuid4())
    app.state.files.write(original, b'x' * 100)
    app.state.files.temporary(partial).write_bytes(b'x' * 50)
    for path in app.state.files.storage_files(): os.utime(path, (now() - 7200, now() - 7200))
    reset_ledger(app.state.repository)
    settings = limits(app, max_original_bytes_global=150)
    capacity = UploadCapacity(app.state.repository, app.state.files, settings)
    assert sum(entry['bytes'] for entry in capacity.ledger.read()['entries'].values()) == 150
    with pytest.raises(CapacityError): capacity.reserve('owner-a', str(uuid4()), 1, str(uuid4()), 'a' * 64)
    capacity.cleanup_orphans(now() - 3600)
    assert list(app.state.files.storage_files()) == []
    assert capacity.ledger.read()['untracked_bytes'] == 0
    assert capacity.ledger.read()['entries'] == {}


def test_legacy_orphan_credit_recovers_after_unlink_crash(harness, monkeypatch):
    _, app, *_ = harness
    identifier = str(uuid4())
    app.state.files.write(identifier, b'x' * 100)
    os.utime(app.state.files.path(identifier), (now() - 7200, now() - 7200))
    reset_ledger(app.state.repository)
    capacity = UploadCapacity(app.state.repository, app.state.files, app.state.settings)
    remove = app.state.files.remove
    def interrupted(identifier):
        remove(identifier)
        raise SimulatedCrash()
    monkeypatch.setattr(app.state.files, 'remove', interrupted)
    with pytest.raises(SimulatedCrash): capacity.cleanup_orphans(now() - 3600)
    assert capacity.entry(identifier)['bytes'] == 100
    monkeypatch.setattr(app.state.files, 'remove', remove)
    restarted = UploadCapacity(app.state.repository, FileStore(app.state.files.root), app.state.settings)
    restarted.recover()
    assert restarted.entry(identifier) is None
    assert list(app.state.files.storage_files()) == []


def test_list_uses_bounded_projection_and_validates_cursor(harness, monkeypatch):
    client, app, *_ = harness
    saved = ready(harness)
    def no_full_read(*args, **kwargs): raise AssertionError('Listing must not load full CV histories')
    monkeypatch.setattr(app.state.repository, 'list', no_full_read)
    page = client.get('/api/v1/cv').json()
    assert page['cvs'][0]['id'] == saved['id'] and page['next_cursor'] is None
    assert not {'history', 'items', 'skills', 'clarifications'} & page['cvs'][0].keys()
    for params in ({'limit': 0}, {'limit': 101}, {'cursor': 'garbage!'}, {'cursor': 'e30'}):
        assert client.get('/api/v1/cv', params=params).status_code == 422


def test_policy_reports_owner_limits(harness):
    client, *_ = harness
    policy = client.get('/api/v1/cv/policy').json()
    assert policy['max_saved_cvs'] == 50
    assert policy['max_stored_original_bytes'] == 100 * 1024 * 1024


def hold_process_lock(directory, identifier, acquired):
    from time import sleep
    files = FileStore(directory)
    with files.lock(identifier):
        acquired.set()
        sleep(20)


def test_file_lock_excludes_another_process_and_recovers_after_process_death(tmp_path):
    context = multiprocessing.get_context('spawn')
    acquired = context.Event()
    identifier = str(uuid4())
    process = context.Process(target=hold_process_lock, args=(str(tmp_path), identifier, acquired))
    process.start()
    try:
        assert acquired.wait(10)
        files = FileStore(tmp_path)
        with files.lock(identifier, blocking=False) as locked: assert locked is False
        process.terminate()
        process.join(10)
        assert not process.is_alive()
        with files.lock(identifier, blocking=False) as locked: assert locked is True
    finally:
        if process.is_alive(): process.terminate()
        process.join(10)


def test_lock_metadata_is_bounded_for_rejected_or_distinct_identifiers(tmp_path):
    files = FileStore(tmp_path)
    for _ in range(1000):
        with files.lock(str(uuid4())): pass
    assert len(list(files.lock_root.iterdir())) <= 256
    assert list(files.storage_files()) == []
