from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app


class Accounts:
    def __init__(self):
        self.records = {
            'free-token': {'id': 'free', 'cv_review_scope': 'section'},
            'paid-token': {'id': 'paid', 'cv_review_scope': 'item'},
            'legacy-token': {'id': 'legacy'},
        }

    def session(self, token, settings):
        return {'name': 'Synthetic', 'email': 'person@example.test', 'email_verified': True,
                'provider': 'email', 'expires_at': datetime.now(timezone.utc), **self.records[token]}


def test_session_exposes_only_server_owned_review_scope():
    with TestClient(create_app(repository=object(), accounts=Accounts(), capabilities=object())) as client:
        for token, expected in [('free-token', 'section'), ('paid-token', 'item'), ('legacy-token', 'section')]:
            response = client.get('/api/v1/profile/auth/session?cv_review_scope=item',
                                  headers={'Authorization': 'Bearer ' + token, 'X-Review-Scope': 'item'})
            assert response.status_code == 200
            assert response.json()['cv_review_scope'] == expected
            assert response.json()['cv_review_policy_version'] == 1
