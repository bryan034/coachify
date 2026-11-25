from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from tests.conftest import docx, mutation, upload


@pytest.mark.parametrize('plan', ['free', None, 'premium'])
def test_cv_upload_limits_preserve_first_upload_and_replays(harness, plan):
    client, app, _, _, profile = harness
    profile.account_type = plan
    key = str(uuid4())
    first = upload(client, mutation_id=key)
    assert first.status_code == 202, first.text
    cv = first.json()
    assert upload(client, mutation_id=key).json()['id'] == cv['id']
    second = upload(client, name='second.docx')
    if plan == 'premium':
        assert second.status_code == 202 and second.json()['id'] != cv['id']
        app.state.worker.run_once()
        reprocess = {'cv_id': cv['id'], 'expected_version': client.get('/api/v1/cv/' + cv['id']).json()['version']}
        reprocess_key = str(uuid4())
        accepted = upload(client, mutation_id=reprocess_key, **reprocess)
        assert accepted.status_code == 202, accepted.text
        profile.account_type = 'free'
        assert upload(client, mutation_id=reprocess_key, **reprocess).json()['operation_id'] == accepted.json()['operation_id']
    else:
        assert second.status_code == 402 and second.json()['code'] == 'premium_required'
        reprocess = upload(client, data=docx(['A different CV.']), cv_id=cv['id'], expected_version=cv['version'])
        assert reprocess.status_code == 402 and reprocess.json()['code'] == 'premium_required'
        assert [value['id'] for value in client.get('/api/v1/cv').json()['cvs']] == [cv['id']]


def test_free_account_can_retry_failed_extraction_on_its_first_cv(harness):
    client, app, extractor, _, profile = harness
    profile.account_type = 'free'
    cv_id = upload(client).json()['id']
    extractor.failure = 'Synthetic processing failure'
    app.state.worker.run_once()
    failed = client.get('/api/v1/cv/' + cv_id).json()
    assert failed['status'] == 'failed'
    extractor.failure = None
    retried = client.post('/api/v1/cv/operations/' + failed['operation_id'] + '/retry', json=mutation(failed['version']))
    assert retried.status_code == 200, retried.text
    app.state.worker.run_once()
    assert client.get('/api/v1/cv/' + cv_id).json()['status'] == 'ready'


def test_concurrent_first_uploads_get_one_free_slot(harness):
    client, _, _, _, profile = harness
    profile.account_type = 'free'
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: upload(client), range(2)))
    assert sorted(response.status_code for response in responses) == [202, 402]
    assert len(client.get('/api/v1/cv').json()['cvs']) == 1


def test_deleting_the_only_cv_does_not_free_the_slot(harness):
    client, app, _, _, profile = harness
    profile.account_type = 'free'
    cv = upload(client).json()
    app.state.worker.run_once()
    version = client.get('/api/v1/cv/' + cv['id']).json()['version']
    deleted = client.request('DELETE', '/api/v1/cv/' + cv['id'], json=mutation(version))
    assert deleted.status_code == 200, deleted.text
    assert client.get('/api/v1/cv').json()['cvs'] == []
    blocked = upload(client, name='second.docx')
    assert blocked.status_code == 402 and blocked.json()['code'] == 'premium_required'
    profile.account_type = 'premium'
    assert upload(client, name='second.docx').status_code == 202


def test_a_cv_deleted_before_the_limit_still_counts(harness, repository):
    client, app, _, _, profile = harness
    cv = upload(client).json()
    app.state.worker.run_once()
    version = client.get('/api/v1/cv/' + cv['id']).json()['version']
    assert client.request('DELETE', '/api/v1/cv/' + cv['id'], json=mutation(version)).status_code == 200
    assert repository.admission.read()['entries'] == {}
    profile.account_type = 'free'
    blocked = upload(client, name='second.docx')
    assert blocked.status_code == 402 and blocked.json()['code'] == 'premium_required'
