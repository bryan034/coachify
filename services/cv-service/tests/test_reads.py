"""Saved-CV reads retain the upstream authentication and ownership guarantees."""
from copy import deepcopy
from tests.conftest import ready


def test_read_endpoints_require_auth_even_without_saved_records(harness):
    client, *_ = harness
    client.headers.pop('Authorization')
    assert client.get('/api/v1/cv').status_code == 401
    assert client.get('/api/v1/cv/000000000000000000000001').status_code == 401


def test_saved_cv_read_is_owner_scoped_and_read_only(harness):
    client, app, *_ = harness
    cv = ready(harness)
    before = deepcopy(app.state.repository.get('owner-a', cv['id']))
    summary = client.get('/api/v1/cv').json()['cvs'][0]
    assert summary['id'] == cv['id']
    assert 'skills' not in summary and 'file_url' not in summary
    client.headers['Authorization'] = 'Bearer owner-b'
    assert client.get('/api/v1/cv').json() == {'cvs': [], 'selection': {'cv_id': None, 'version': 0}, 'next_cursor': None}
    assert client.get('/api/v1/cv/' + cv['id']).status_code == 404
    client.headers['Authorization'] = 'Bearer owner-a'
    response = client.get('/api/v1/cv/' + cv['id'])
    assert response.status_code == 200
    assert response.json()['skills'][0]['proficiency'] is None
    assert all(field not in response.json() for field in ('user_id', 'file_url', 'source_text', 'original_path'))
    assert response.headers['cache-control'] == 'no-store'
    # Uploads use the explicit /uploads contract, never a generic record-write API.
    assert client.post('/api/v1/cv', json={}).status_code == 405
    assert app.state.repository.get('owner-a', cv['id']) == before
