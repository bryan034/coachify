from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app


class Accounts:
    def session(self, token, settings):
        return {'id': 'synthetic', 'name': 'Synthetic', 'email': 'person@example.test', 'email_verified': True,
                'provider': 'email', 'expires_at': datetime.now(timezone.utc)}

    def finish(self, data, settings, verify_google, source):
        return self.session('token', settings)

    def verify_email(self, data, settings):
        return self.session('token', settings)


def test_session_returns_item_review_policy_regardless_of_request():
    with TestClient(create_app(repository=object(), accounts=Accounts(), capabilities=object())) as client:
        response = client.get('/api/v1/profile/auth/session?cv_review_scope=section',
                              headers={'Authorization': 'Bearer token', 'X-Review-Scope': 'section'})
        assert response.status_code == 200
        assert (response.json()['cv_review_scope'], response.json()['cv_review_policy_version']) == ('item', 1)


def test_sign_in_and_verification_return_item_review_policy():
    body = {'flow_id': 'f' * 32, 'attempt_id': 'a' * 32, 'session_token': 's' * 32}
    with TestClient(create_app(repository=object(), accounts=Accounts(), capabilities=object())) as client:
        complete = client.post('/api/v1/profile/auth/complete', json=body)
        verify = client.post('/api/v1/profile/auth/verify-email', json={**body, 'challenge_id': 'c' * 32, 'code': '123456'})
        for response in (complete, verify):
            assert response.status_code == 200
            assert (response.json()['cv_review_scope'], response.json()['cv_review_policy_version']) == ('item', 1)
