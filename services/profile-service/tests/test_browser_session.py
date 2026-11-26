from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.schemas.accounts import AccountView

BASE = '/api/v1/profile/auth'
BODY = {'flow_id': 'f' * 32, 'attempt_id': 'a' * 32, 'session_token': 'm' * 64}
BROWSER = {'X-Elo-Browser': '1'}


def test_full_profile_contract_matches_generated_openapi():
    contract = Path(__file__).resolve().parents[3] / 'contracts/api/profile.yaml'
    assert json.loads(contract.read_text()) == create_app().openapi()


class Accounts:
    def __init__(self):
        self.tokens = []
        self.revoked = []
        self.pending = False

    def finish(self, data, settings, verify_google, source):
        self.tokens.append(data.session_token)
        return self.view()

    def verify_email(self, data, settings):
        self.tokens.append(data.session_token)
        return self.view()

    def resend(self, data, settings):
        self.tokens.append(data.session_token)
        self.pending = True
        return self.view()

    def logout(self, token):
        self.revoked.append(token)

    def session(self, token, settings):
        assert token == 'synthetic-session'
        return self.view()

    def view(self):
        expiry = datetime.now(timezone.utc) + timedelta(hours=24)
        if self.pending:
            return {'verification_required': True, 'challenge_id': 'c' * 32, 'masked_email': 'p***@example.test',
                    'expires_at': expiry, 'resend_at': expiry}
        return {'id': 'synthetic', 'name': 'Synthetic', 'email': 'person@example.test', 'email_verified': True,
                'provider': 'email', 'expires_at': expiry}


def test_account_schema_matches_the_session_view():
    schema = Path(__file__).resolve().parents[3] / 'contracts/api/models/account.schema.json'
    assert json.loads(schema.read_text()) == AccountView.model_json_schema()


def test_session_exposes_legacy_and_premium_account_types():
    accounts = Accounts()
    headers = {'Authorization': 'Bearer synthetic-session'}
    with TestClient(create_app(repository=object(), accounts=accounts, capabilities=object())) as client:
        assert client.get(BASE + '/session', headers=headers).json()['account_type'] == 'free'
        view = accounts.view()
        accounts.view = lambda: {**view, 'account_type': 'premium'}
        assert client.get(BASE + '/session', headers=headers).json()['account_type'] == 'premium'


def test_browser_credential_is_server_derived_stable_and_only_returned_in_httponly_cookie():
    accounts = Accounts()
    with TestClient(create_app(repository=object(), accounts=accounts, capabilities=object())) as client:
        first = client.post(BASE + '/complete', json=BODY, headers=BROWSER)
        second = client.post(BASE + '/complete', json=BODY, headers=BROWSER)
        assert first.status_code == second.status_code == 200
        cookie = first.headers['set-cookie']
        token = accounts.tokens[0]
        assert len(token) == 64 and token != BODY['session_token']
        assert accounts.tokens == [token, token]
        assert token not in first.text
        assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/api/v1' in cookie
        assert first.cookies['elo_session'] == BODY['session_token'] + '.' + token
        assert first.cookies['elo_session'] == second.cookies['elo_session']
        client.post(BASE + '/complete', json={**BODY, 'session_token': 'n' * 64}, headers=BROWSER)
        assert accounts.tokens[-1] != token


def test_pending_verification_does_not_install_session_and_verify_resend_use_same_credential():
    accounts = Accounts()
    accounts.pending = True
    with TestClient(create_app(repository=object(), accounts=accounts, capabilities=object())) as client:
        pending = client.post(BASE + '/complete', json=BODY, headers=BROWSER)
        assert pending.status_code == 200 and 'set-cookie' not in pending.headers
        assert client.post(BASE + '/resend-verification', json=BODY, headers=BROWSER).status_code == 200
        accounts.pending = False
        verified = client.post(BASE + '/verify-email', json={**BODY, 'challenge_id': 'c' * 32, 'code': '123456'}, headers=BROWSER)
        assert verified.status_code == 200 and 'HttpOnly' in verified.headers['set-cookie']
        assert len(set(accounts.tokens)) == 1


def test_production_cookie_is_secure_and_logout_cannot_clear_a_different_session():
    accounts = Accounts()
    with TestClient(create_app(repository=object(), accounts=accounts, capabilities=object())) as client:
        settings = client.app.state.auth_settings
        client.app.state.auth_settings = replace(settings, environment='production')
        response = client.post(BASE + '/complete', json=BODY, headers=BROWSER)
        assert 'Secure' in response.headers['set-cookie']
        cookie = response.cookies['elo_session']
        stale = client.post(BASE + '/logout', headers={**BROWSER, 'Cookie': 'elo_session=' + cookie})
        assert stale.status_code == 409 and 'set-cookie' not in stale.headers
        assert not accounts.revoked
        logout = client.post(BASE + '/logout', headers={**BROWSER, 'Cookie': 'elo_session=' + cookie,
                                                     'Authorization': 'Bearer ' + accounts.tokens[0]})
        assert logout.status_code == 200 and 'Max-Age=0' in logout.headers['set-cookie']
        assert accounts.revoked == [accounts.tokens[0]]


def test_nonbrowser_api_clients_keep_explicit_bearer_support_without_setting_a_cookie():
    accounts = Accounts()
    with TestClient(create_app(repository=object(), accounts=accounts, capabilities=object())) as client:
        response = client.post(BASE + '/complete', json=BODY)
        assert response.status_code == 200 and 'set-cookie' not in response.headers
        assert accounts.tokens == [BODY['session_token']]
