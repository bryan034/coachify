from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import httpx
from fastapi.testclient import TestClient

from app.main import create_app


def test_reset_uses_the_authenticated_career_owner(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.delenv('MONGODB_URI', raising=False)

    def profile(request):
        assert request.headers['Authorization'] == 'Bearer synthetic-session'
        if request.url.path == '/api/v1/profile/auth/session':
            return httpx.Response(200, json={'id': 'synthetic-owner', 'email_verified': True})
        assert request.url.path == '/api/v1/profile'
        return httpx.Response(200, json={'onboarding_complete': True})

    profile_client = httpx.AsyncClient(base_url='http://profile.test', transport=httpx.MockTransport(profile))
    app = create_app(profile_client=profile_client)
    goals = Mock()
    goals.delete_many.return_value.deleted_count = 1
    database = MagicMock()
    database.list_collection_names.return_value = ['career_goals']
    database.__getitem__.return_value = goals

    with TestClient(app) as client:
        app.state.goal_store = SimpleNamespace(db=database)
        response = client.post('/api/v1/career/dev/reset', headers={'Authorization': 'Bearer synthetic-session'})

    assert response.status_code == 200
    assert response.json() == {'deleted': {'career_goals': 1}}
    database.__getitem__.assert_called_once_with('career_goals')
    goals.delete_many.assert_called_once_with({'$or': [
        {'user_id': 'synthetic-owner'}, {'owner': 'synthetic-owner'},
        {'account_id': 'synthetic-owner'}, {'_id': 'synthetic-owner'},
    ]})
