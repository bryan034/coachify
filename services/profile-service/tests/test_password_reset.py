"""Real MongoDB coverage for mailbox recovery and credential-generation fencing."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from fastapi import HTTPException
from app.core.security import now
from tests.test_accounts import setup, register, begin, complete, BASE, PASSWORD, pytestmark

NEW_PASSWORD = 'Reset123'


def request_reset(client, repo, email):
    with patch.object(repo.mailer, 'send_password_reset', create=True) as send:
        response = client.post(BASE+'/auth/forgot-password', json={'email': email})
    assert response.status_code == 200, response.text
    return {'challenge_id': response.json()['challenge_id'], 'code': send.call_args.args[1], 'password': NEW_PASSWORD}


def test_reset_preserves_account_data_revokes_sessions_and_blocks_replay(setup):
    client, repo = setup
    account, headers, body, _ = register(client)
    client.patch(BASE, headers=headers, json={'expected_version': 0, 'occupational_status': 'employed'})
    # Include a session from before credential binding was introduced.
    repo.sessions.update_many({}, {'$unset': {'credential_hash': ''}})
    proof = request_reset(client, repo, account['email'].upper())
    assert client.post(BASE+'/auth/reset-password', json=proof).json() == {'ok': True}
    assert client.get(BASE, headers=headers).status_code == 401
    assert client.post(BASE+'/auth/complete', json=body).status_code == 409
    assert client.post(BASE+'/auth/reset-password', json=proof).status_code == 400
    assert complete(client, begin(client, 'login'), email=account['email'], password=PASSWORD)[0].status_code == 401
    response, login = complete(client, begin(client, 'login'), email=account['email'], password=NEW_PASSWORD)
    assert response.status_code == 200 and response.json()['id'] == account['id']
    assert client.get(BASE, headers={'Authorization': 'Bearer '+login['session_token']}).json()['occupational_status'] == 'employed'
    assert repo.accounts.count_documents({}) == 1


def test_reset_expiry_guess_limit_validation_and_unknown_email(setup):
    client, repo = setup
    account, _, _, _ = register(client)
    with patch.object(repo.mailer, 'send_password_reset', create=True) as send:
        response = client.post(BASE+'/auth/forgot-password', json={'email': 'unknown@example.test'})
        assert response.status_code == 200 and 'If an email/password account exists' in response.json()['message']
        send.assert_not_called()
    proof = request_reset(client, repo, account['email'])
    assert client.post(BASE+'/auth/reset-password', json={**proof, 'password': 'short'}).status_code == 422
    wrong = '000000' if proof['code'] != '000000' else '111111'
    for _ in range(5):
        assert client.post(BASE+'/auth/reset-password', json={**proof, 'code': wrong}).status_code == 400
    assert client.post(BASE+'/auth/reset-password', json=proof).status_code == 400
    proof = request_reset(client, repo, account['email'])
    repo.password_reset.resets.update_many({}, {'$set': {'expires_at': now()-timedelta(seconds=1)}})
    assert client.post(BASE+'/auth/reset-password', json=proof).status_code == 400
    assert client.post(BASE+'/auth/forgot-password', json={'email': 'invalid'}).status_code == 422


def test_reset_delivery_failure_is_retryable_and_duplicate_registration_sends_nothing(setup):
    client, repo = setup
    account, _, _, _ = register(client)
    before = len(repo.mailer.messages)
    response, _ = complete(client, begin(client), email=account['email'])
    assert response.status_code == 409
    assert 'already exists for this email address' in response.json()['detail']
    assert len(repo.mailer.messages) == before
    with patch.object(repo.mailer, 'send_password_reset', create=True, side_effect=HTTPException(503, 'Synthetic outage')):
        assert client.post(BASE+'/auth/forgot-password', json={'email': account['email']}).status_code == 503
    assert repo.password_reset.resets.count_documents({}) == 0
    proof = request_reset(client, repo, account['email'])
    assert client.post(BASE+'/auth/reset-password', json=proof).status_code == 200


def test_concurrent_resets_have_one_winner_and_are_mode_bound(setup):
    from dataclasses import replace
    client, repo = setup
    account, _, _, _ = register(client)
    proof = request_reset(client, repo, account['email'])
    settings = client.app.state.auth_settings
    client.app.state.auth_settings = replace(settings, mode='email')
    assert client.post(BASE+'/auth/reset-password', json=proof).status_code == 400
    client.app.state.auth_settings = settings
    other = request_reset(client, repo, account['email'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: client.post(BASE+'/auth/reset-password', json=p).status_code, [proof, other]))
    assert sorted(results) == [200, 400]


def test_reset_delivery_rate_limit_applies_to_unknown_addresses(setup):
    client, _ = setup
    for _ in range(5):
        assert client.post(BASE+'/auth/forgot-password', json={'email': 'limited@example.test'}).status_code == 200
    assert client.post(BASE+'/auth/forgot-password', json={'email': 'limited@example.test'}).status_code == 429
