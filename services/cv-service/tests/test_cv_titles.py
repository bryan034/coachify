"""Owner-scoped metadata titles preserve source identity and effective evidence."""
from uuid import uuid4
import pytest
from tests.conftest import ready, upload


def test_rename_persists_replays_and_preserves_evidence(harness):
    client, app, *_ = harness
    repository = app.state.repository
    cv = ready(harness)
    before = repository.get('owner-a', cv['id'])
    body = {'expected_version': cv['version'], 'mutation_id': str(uuid4()), 'display_name': '  Software engineering CV  '}
    path = f"/api/v1/cv/{cv['id']}/title"
    response = client.patch(path, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['display_name'] == 'Software engineering CV'
    assert result['file_name'] == cv['file_name']
    assert result['effective_version'] == cv['effective_version']
    assert result['items'] == cv['items'] and result['extraction_version'] == cv['extraction_version']
    after = repository.get('owner-a', cv['id'])
    assert after['history'] == before['history'] and after['source_hash'] == before['source_hash']
    assert client.patch(path, json=body).json()['version'] == result['version']
    assert client.get('/api/v1/cv').json()['cvs'][0]['display_name'] == result['display_name']
    assert client.get(f"/api/v1/cv/{cv['id']}").json()['display_name'] == result['display_name']
    assert client.patch(path, json={**body, 'mutation_id': str(uuid4()), 'display_name': 'Stale'}).status_code == 409
    assert client.patch(path, json={**body, 'display_name': 'Changed replay'}).status_code == 409
    assert client.patch(path, json=body, headers={'Authorization': 'Bearer owner-b'}).status_code == 404


@pytest.mark.parametrize('name', ['', '   ', 'x' * 201, 'bad\x00title', 'bad\ntitle', 'bad\x7ftitle'])
def test_invalid_titles_are_rejected(harness, name):
    client, *_ = harness
    cv = ready(harness)
    response = client.patch(f"/api/v1/cv/{cv['id']}/title", json={
        'expected_version': cv['version'], 'mutation_id': str(uuid4()), 'display_name': name})
    assert response.status_code == 422
    assert client.get(f"/api/v1/cv/{cv['id']}").json()['display_name'] is None


def test_queued_cv_can_be_renamed(harness):
    client, *_ = harness
    cv = upload(client).json()
    response = client.patch(f"/api/v1/cv/{cv['id']}/title", json={
        'expected_version': cv['version'], 'mutation_id': str(uuid4()), 'display_name': 'New application'})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'queued'
    assert response.json()['display_name'] == 'New application'
