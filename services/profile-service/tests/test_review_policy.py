from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import create_app


class Accounts:
    def __init__(self):
        self.records = {
            'free-token': {'id': 'free', 'cv_review_scope': 'section', 'cv_review_policy_version': 1},
            'paid-token': {'id': 'paid', 'cv_review_scope': 'item', 'cv_review_policy_version': 1},
            'legacy-token': {'id': 'legacy'},
        }

    def session(self, token, settings):
        return {'name': 'Synthetic', 'email': 'person@example.test', 'email_verified': True,
                'provider': 'email', 'owner': self.records[token]['id'],
                'expires_at': datetime.now(timezone.utc), **self.records[token]}

    def finish(self, data, settings, verify_google):
        return self.session('free-token', settings)

    def verify_email(self, data, settings):
        return self.session('free-token', settings)


def test_session_projects_same_current_review_policy_for_all_accounts():
    accounts = Accounts()
    with TestClient(create_app(repository=object(), accounts=accounts, capabilities=object())) as client:
        for token in ('free-token', 'paid-token', 'legacy-token'):
            response = client.get('/api/v1/profile/auth/session?cv_review_scope=section',
                                  headers={'Authorization': 'Bearer ' + token, 'X-Review-Scope': 'section'})
            assert response.status_code == 200
            assert response.json()['cv_review_scope'] == 'item'
            assert response.json()['cv_review_policy_version'] == 1
        invalid = client.patch('/api/v1/profile', headers={'Authorization': 'Bearer paid-token'},
                               json={'expected_version': 0, 'cv_review_scope': 'section'})
        assert invalid.status_code == 422
    # Project the policy on read without rewriting existing account records.
    assert accounts.records['free-token']['cv_review_scope'] == 'section'
    assert accounts.records['paid-token']['cv_review_policy_version'] == 1


def test_sign_in_and_verification_also_project_current_review_policy():
    body = {'flow_id': 'f' * 32, 'attempt_id': 'a' * 32, 'session_token': 's' * 32}
    with TestClient(create_app(repository=object(), accounts=Accounts(), capabilities=object())) as client:
        complete = client.post('/api/v1/profile/auth/complete', json=body)
        verify = client.post('/api/v1/profile/auth/verify-email', json={**body, 'challenge_id': 'c' * 32, 'code': '123456'})
        for response in (complete, verify):
            assert response.status_code == 200
            assert (response.json()['cv_review_scope'], response.json()['cv_review_policy_version']) == ('item', 1)
