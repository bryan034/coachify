"""Real-Mongo account/session regressions (also run in profile-integration CI)."""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from secrets import token_urlsafe
from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import AutoReconnect
from app.main import create_app
from app.repositories.accounts import AccountRepository, digest, now
from app.repositories.profile import ProfileRepository

pytestmark = pytest.mark.skipif(not os.getenv('MONGODB_TEST_URI'), reason='Requires disposable real MongoDB')
PASSWORD = 'Synthetic passphrase 2026!'

class CaptureMailer:
    def __init__(self): self.messages=[]
    def send_otp(self,email,code): self.messages.append((email,code))

BASE = '/api/v1/profile'

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('AUTH_MODE', 'local_test')
    mongo = MongoClient(os.environ['MONGODB_TEST_URI'], serverSelectionTimeoutMS=5000)
    database = mongo['elo_accounts_test_' + uuid4().hex]
    accounts = AccountRepository(database, CaptureMailer())
    with TestClient(create_app(ProfileRepository(database), accounts)) as client:
        yield client, accounts
    mongo.drop_database(database.name)
    mongo.close()


def begin(client, intent='register', flow=None, generation=1):
    data = {'flow_id': flow or token_urlsafe(32), 'attempt_id': token_urlsafe(32), 'generation': generation, 'intent': intent}
    response = client.post(BASE + '/auth/attempts', json=data)
    assert response.status_code == 200, response.text
    return {**data, 'nonce': response.json()['nonce']}


def complete(client, attempt, **fields):
    if 'credential' not in fields:
        selected = fields.pop('account_id', None)
        account = client.app.state.accounts.accounts.find_one({'id': selected}) if selected else None
        fields.setdefault('email', account['email'] if account else uuid4().hex + '@example.test')
        fields.setdefault('password', PASSWORD)
    body = {'flow_id': attempt['flow_id'], 'attempt_id': attempt['attempt_id'], 'session_token': fields.pop('session_token', token_urlsafe(32)), **fields}
    response=client.post(BASE + '/auth/complete', json=body)
    if response.status_code==200 and response.json().get('verification_required'):
        code=client.app.state.accounts.mailer.messages[-1][1]
        response=client.post(BASE+'/auth/verify-email',json={k:body[k] for k in ('flow_id','attempt_id','session_token')}|{'challenge_id':response.json()['challenge_id'],'code':code})
    return response, body


def register(client, name='Synthetic Account'):
    attempt = begin(client)
    response, body = complete(client, attempt, name=name)
    assert response.status_code == 200, response.text
    return response.json(), {'Authorization': 'Bearer ' + body['session_token']}, body, attempt


def test_registration_retries_names_and_private_ownership(setup):
    client, repo = setup
    assert client.get(BASE).status_code == 401
    assert client.get(BASE + '/auth/local-accounts').json() == []
    a, headers, body, _ = register(client, 'Same name')
    assert client.get(BASE, headers=headers).json()['onboarding_complete'] is False
    assert client.post(BASE + '/auth/complete', json=body).json() == a
    assert client.patch(BASE, json={'expected_version': 0, 'occupational_status': 'employed'}, headers=headers).status_code == 200
    b, other, _, _ = register(client, 'Same name')
    assert a['id'] != b['id']
    assert client.get(BASE, headers=other).json()['version'] == 0
    assert client.get(BASE + '/versions/1', headers=other).status_code == 404
    assert len(client.get(BASE + '/auth/local-accounts').json()) == 2
    assert client.get(BASE + '?owner=other', headers={**headers, 'X-User-Id': b['id']}).json()['version'] == 1
    assert repo.sessions.find_one({'_id': digest(body['session_token'])})
    assert not repo.sessions.find_one({'token': body['session_token']})


def test_logout_revokes_replay_and_preserves_history_and_reentry(setup):
    client, _ = setup
    a, headers, _, _ = register(client)
    client.patch(BASE, json={'expected_version': 0, 'occupational_status': 'employed'}, headers=headers)
    for _ in range(2):
        assert client.post(BASE + '/auth/logout', headers=headers).json() == {'ok': True}
    assert client.get(BASE, headers=headers).status_code == 401
    assert client.get(BASE + '/auth/session', headers=headers).status_code == 401
    attempt = begin(client, 'login')
    response, login = complete(client, attempt, account_id=a['id'])
    assert response.json()['id'] == a['id']
    assert client.get(BASE + '/versions/1', headers={'Authorization': 'Bearer ' + login['session_token']}).json()['occupational_status'] == 'employed'


def test_stale_logout_cannot_revoke_new_account_session(setup):
    client, _ = setup
    a, headers, _, attempt = register(client)
    client.post(BASE + '/auth/logout', headers=headers)
    next_attempt = begin(client, flow=attempt['flow_id'], generation=2)
    b, body = complete(client, next_attempt, name='Another account')
    client.post(BASE + '/auth/logout', headers=headers)
    assert client.get(BASE + '/auth/session', headers={'Authorization': 'Bearer ' + body['session_token']}).json()['id'] == b.json()['id']


def test_cancelled_superseded_out_of_order_and_changed_retries(setup):
    client, _ = setup
    first = begin(client)
    second = begin(client, flow=first['flow_id'], generation=2)
    assert complete(client, first, name='Old')[0].status_code == 409
    assert client.post(BASE + '/auth/attempts', json={k: first[k] for k in ('flow_id', 'attempt_id', 'generation', 'intent')}).status_code == 409
    response, body = complete(client, second, name='Current')
    assert response.status_code == 200
    assert client.post(BASE + '/auth/complete', json={**body, 'name': 'Changed'}).status_code == 409
    client.post(BASE + '/auth/attempts/cancel', json={k: second[k] for k in ('flow_id', 'attempt_id')})
    assert client.get(BASE, headers={'Authorization': 'Bearer ' + body['session_token']}).status_code == 401
    assert client.post(BASE + '/auth/complete', json=body).status_code == 409


@pytest.mark.parametrize('mode', ['local_test', 'email', 'google'])
def test_unknown_email_login_directs_to_registration_without_creating_an_account(setup, mode):
    from dataclasses import replace
    client, repo = setup
    client.app.state.auth_settings = replace(client.app.state.auth_settings, mode=mode)
    attempt = begin(client, 'login')
    response, _ = complete(client, attempt, email='new@example.test')
    assert response.status_code == 404
    assert response.json()['detail'] == 'No account was found for this email address. Create a new account to get started.'
    assert repo.accounts.count_documents({}) == 0
    assert repo.sessions.count_documents({}) == 0
    assert repo.mailer.messages == []


@pytest.mark.parametrize('password', ['Test1234', 'x' * 128])
def test_registration_and_sign_in_accept_password_length_boundaries(setup, password):
    client, repo = setup
    response, body = complete(client, begin(client), password=password)
    assert response.status_code == 200, response.text
    assert response.json()['email_verified'] is True
    login, _ = complete(client, begin(client, 'login'), email=body['email'], password=password)
    assert login.status_code == 200 and login.json()['id'] == response.json()['id']
    assert repo.accounts.count_documents({}) == 1


def test_expiry_and_direct_google_bearer_rejected(setup):
    client, repo = setup
    _, headers, body, attempt = register(client)
    repo.sessions.update_one({'_id': digest(body['session_token'])}, {'$set': {'expires_at': now() - timedelta(seconds=1)}})
    assert client.get(BASE, headers=headers).status_code == 401
    assert client.get(BASE, headers={'Authorization': 'Bearer google-id-token'}).status_code == 401
    pending = begin(client)
    repo.flows.update_one({'_id': digest(pending['flow_id'])}, {'$set': {'attempt_expires_at': now() - timedelta(seconds=1)}})
    assert complete(client, pending, name='Expired')[0].status_code == 409


def google(client):
    from dataclasses import replace
    client.app.state.auth_settings = replace(client.app.state.auth_settings, mode='google', google_client_id='test-client')


def claims(attempt, **updates):
    return {'iss': 'https://accounts.google.com', 'sub': 'stable-subject', 'nonce': attempt['nonce'], 'name': 'Synthetic Google', 'email':'synthetic-google@example.test', 'email_verified':True, **updates}


def test_google_verified_registration_existing_identity_and_name_changes(setup):
    client, repo = setup
    google(client)
    assert client.get(BASE + '/auth/local-accounts').status_code == 404
    attempt = begin(client)
    with patch('app.core.auth.id_token.verify_oauth2_token', return_value=claims(attempt)):
        response, body = complete(client, attempt, credential='google-credential')
    assert response.status_code == 200
    user = response.json()
    headers = {'Authorization': 'Bearer ' + body['session_token']}
    client.patch(BASE, headers=headers, json={'expected_version': 0, 'occupational_status': 'employed'})
    existing = begin(client)
    with patch('app.core.auth.id_token.verify_oauth2_token', return_value=claims(existing, name='Changed name', email='changed@example.test')):
        assert complete(client, existing, credential='different')[0].status_code == 409
    login = begin(client, 'login')
    with patch('app.core.auth.id_token.verify_oauth2_token', return_value=claims(login, name='Changed', email='another@example.test')):
        signed_in, body = complete(client, login, credential='verified')
    assert signed_in.json()['id'] == user['id']
    assert client.get(BASE, headers={'Authorization': 'Bearer ' + body['session_token']}).json()['version'] == 1
    assert repo.accounts.count_documents({}) == 1


def test_unknown_google_identity_and_invalid_nonce_are_recoverable(setup):
    client, repo = setup
    google(client)
    for intent, updates, expected in [('login', {}, 404), ('register', {'nonce': 'wrong'}, 401), ('register', {'iss': 'evil'}, 401)]:
        attempt = begin(client, intent)
        with patch('app.core.auth.id_token.verify_oauth2_token', return_value=claims(attempt, **updates)):
            assert complete(client, attempt, credential='verified')[0].status_code == expected
    assert repo.accounts.count_documents({}) == 0


def test_retry_after_committed_account_but_failed_session_write(setup):
    client, repo = setup
    google(client)
    attempt = begin(client)
    token = token_urlsafe(32)
    with patch('app.core.auth.id_token.verify_oauth2_token', return_value=claims(attempt)):
        with patch.object(repo.sessions, 'update_one', side_effect=AutoReconnect('synthetic outage')):
            failed, body = complete(client, attempt, credential='verified', session_token=token)
        assert failed.status_code == 503
        assert repo.accounts.count_documents({}) == 1
        assert client.post(BASE + '/auth/complete', json=body).status_code == 200
    assert repo.accounts.count_documents({}) == 1


def test_concurrent_google_creation_has_one_account(setup):
    client, repo = setup
    google(client)
    attempts = [begin(client), begin(client)]
    # Stub only Google's cryptographic boundary; MongoDB uniqueness remains real.
    def verify(credential, audience, nonce):
        return {'sub': 'same-subject', 'name': 'Synthetic', 'email':'same@example.test','email_verified':True}
    with patch('app.api.v1.accounts.verify_google', side_effect=verify):
        proofs = []
        for attempt in attempts:
            access = {key: attempt[key] for key in ('flow_id', 'attempt_id')}
            access['session_token'] = token_urlsafe(32)
            pending = client.post(BASE + '/auth/complete', json={**access, 'credential': 'verified'})
            assert pending.status_code == 200
            proofs.append({**access, 'challenge_id': pending.json()['challenge_id'], 'code': repo.mailer.messages[-1][1]})
    assert repo.accounts.count_documents({}) == 0
    # Account creation now races at mailbox-proof publication. Capture each
    # synthetic email before racing, so one attempt cannot read another's code.
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda proof: client.post(BASE + '/auth/verify-email', json=proof).status_code, proofs))
    assert sorted(results) == [200, 409]
    assert repo.accounts.count_documents({}) == 1


def test_logout_or_cancel_during_google_verification_cannot_start_session(setup):
    client, repo = setup
    google(client)
    attempt = begin(client)
    def verify(credential, audience, nonce):
        repo.cancel(type('Data', (), attempt))
        return {'sub': 'cancelled', 'name': 'Synthetic', 'email':'cancelled@example.test','email_verified':True}
    with patch('app.api.v1.accounts.verify_google', side_effect=verify):
        response, body = complete(client, attempt, credential='verified')
    assert response.status_code == 409
    assert client.get(BASE, headers={'Authorization': 'Bearer ' + body['session_token']}).status_code == 401


def test_invalid_fields_and_missing_google_configuration_never_fall_back(setup):
    client, repo = setup
    attempt = begin(client)
    assert complete(client, attempt, password='short')[0].status_code == 422
    response, body = complete(client, attempt, name='Synthetic')
    assert client.post(BASE + '/auth/complete', json={**body, 'owner': 'someone-else'}).status_code == 422
    google(client)
    client.app.state.auth_settings = __import__('app.core.auth', fromlist=['AuthSettings']).AuthSettings('google', '')
    assert complete(client, begin(client), credential='token')[0].status_code == 503
    assert repo.accounts.count_documents({}) == 1


def test_local_sessions_are_never_accepted_after_switch_to_google_mode(setup):
    client, _ = setup
    _, headers, _, _ = register(client)
    google(client)
    assert client.get(BASE, headers=headers).status_code == 401
    assert client.get(BASE + '/auth/session', headers=headers).status_code == 401


def test_different_google_subjects_with_same_email_are_separate_accounts(setup):
    client, repo = setup
    google(client)
    identifiers = []
    for subject in ['subject-a', 'subject-b']:
        attempt = begin(client)
        with patch('app.core.auth.id_token.verify_oauth2_token', return_value=claims(attempt, sub=subject, email='same@example.test')):
            response, _ = complete(client, attempt, credential='verified')
        assert response.status_code == 200
        identifiers.append(response.json()['id'])
    assert len(set(identifiers)) == 2
    assert repo.accounts.count_documents({}) == 2


def test_logout_storage_failure_is_retryable_without_deleting_saved_data(setup):
    client, repo = setup
    _, headers, _, _ = register(client)
    client.patch(BASE, headers=headers, json={'expected_version': 0, 'occupational_status': 'employed'})
    with patch.object(repo.sessions, 'find_one_and_update', side_effect=AutoReconnect('synthetic outage')):
        assert client.post(BASE + '/auth/logout', headers=headers).status_code == 503
    assert client.post(BASE + '/auth/logout', headers=headers).status_code == 200
    assert client.get(BASE, headers=headers).status_code == 401
    assert client.app.state.repository.collection.count_documents({}) == 1


def pending_account(client, email=None, password=PASSWORD):
    attempt=begin(client)
    body={'flow_id':attempt['flow_id'],'attempt_id':attempt['attempt_id'],'session_token':token_urlsafe(32),
          'name':'Synthetic pending','email':email or uuid4().hex+'@example.test','password':password}
    response=client.post(BASE+'/auth/complete',json=body)
    assert response.status_code==200,response.text
    assert response.json()['verification_required']
    verify={k:body[k] for k in ('flow_id','attempt_id','session_token')}
    verify.update(challenge_id=response.json()['challenge_id'],code=client.app.state.accounts.mailer.messages[-1][1])
    return body,verify,response.json()


def test_unproved_registration_does_not_reserve_email_or_create_account(setup):
    client, repo = setup
    attacker, _, _ = pending_account(client, email='available@example.test', password='Attacker chosen passphrase')
    assert repo.accounts.count_documents({}) == 0
    rightful, proof, _ = pending_account(client, email=attacker['email'])
    verified = client.post(BASE + '/auth/verify-email', json=proof)
    assert verified.status_code == 200, verified.text
    assert repo.accounts.count_documents({}) == 1
    assert client.get(BASE + '/auth/session', headers={'Authorization': 'Bearer ' + attacker['session_token']}).status_code == 401
    assert client.get(BASE + '/auth/session', headers={'Authorization': 'Bearer ' + rightful['session_token']}).status_code == 200


def legacy_reservation(client, repo, email=None):
    """Represent a pre-fix persisted signup, including its still-pending OTP."""
    body, proof, _ = pending_account(client, email=email)
    flow = repo.flows.find_one({'_id': digest(body['flow_id'])})
    account = flow['registration_candidate']
    repo.accounts.insert_one(account)
    repo.flows.update_one({'_id': flow['_id']}, {'$unset': {'registration_candidate': '', 'registration_replaces': ''}})
    return account, body, proof


def test_pending_account_requires_email_password_and_otp_before_private_session(setup):
    client,repo=setup
    body,verify,pending=pending_account(client)
    headers={'Authorization':'Bearer '+body['session_token']}
    assert client.get(BASE,headers=headers).status_code==401
    assert client.get(BASE+'/auth/session',headers=headers).status_code==401
    assert repo.accounts.count_documents({}) == 0
    flow = repo.flows.find_one({'_id':digest(body['flow_id'])})
    account = flow['registration_candidate']
    assert account['password_hash'].startswith('$argon2id$')
    assert PASSWORD not in str(account)
    assert flow['expires_at'] == flow['attempt_expires_at']
    assert verify['code'] not in str(repo.flows.find_one({'_id':digest(body['flow_id'])}))
    assert verify['code'] not in str(pending)
    result=client.post(BASE+'/auth/verify-email',json=verify)
    assert result.status_code==200
    assert result.json()['email_verified'] is True
    assert 'registration_candidate' not in repo.flows.find_one({'_id':flow['_id']})
    assert client.get(BASE,headers=headers).json()['onboarding_state']=='missing'
    assert client.post(BASE+'/auth/verify-email',json=verify).json()==result.json()
    assert client.post(BASE+'/auth/verify-email',json={**verify,'session_token':token_urlsafe(32)}).status_code==409


def test_invalid_email_password_and_owner_payloads_do_not_create_accounts(setup):
    client,repo=setup
    attempt=begin(client)
    base={'flow_id':attempt['flow_id'],'attempt_id':attempt['attempt_id'],'session_token':token_urlsafe(32),
          'email':'valid@example.test','password':PASSWORD}
    for changes in [{'email':'not-an-email'},{'password':'short'},{'password':'x'*129},{'owner':'someone-else'}]:
        response=client.post(BASE+'/auth/complete',json={**base,**changes})
        assert response.status_code==422
        assert PASSWORD not in response.text
    assert repo.accounts.count_documents({})==0


def test_wrong_otp_exhaustion_and_expiry_fail_closed(setup):
    client,repo=setup
    body,verify,_=pending_account(client)
    wrong='000000' if verify['code']!='000000' else '111111'
    for _ in range(5):
        assert client.post(BASE+'/auth/verify-email',json={**verify,'code':wrong}).status_code==400
    assert client.post(BASE+'/auth/verify-email',json=verify).status_code==400
    assert repo.accounts.count_documents({}) == 0
    body,verify,_=pending_account(client)
    repo.flows.update_one({'_id':digest(body['flow_id'])},{'$set':{'code_expires_at':now()-timedelta(seconds=1)}})
    assert client.post(BASE+'/auth/verify-email',json=verify).status_code==400
    assert client.get(BASE,headers={'Authorization':'Bearer '+body['session_token']}).status_code==401


def test_resend_cooldown_invalidates_old_code_and_preserves_guesses(setup):
    client,repo=setup
    body,verify,_=pending_account(client)
    access={k:body[k] for k in ('flow_id','attempt_id','session_token')}
    assert client.post(BASE+'/auth/resend-verification',json=access).status_code==429
    wrong='000000' if verify['code']!='000000' else '111111'
    client.post(BASE+'/auth/verify-email',json={**verify,'code':wrong})
    repo.flows.update_one({'_id':digest(body['flow_id'])},{'$set':{'resend_at':now()-timedelta(seconds=1)}})
    resent=client.post(BASE+'/auth/resend-verification',json=access)
    assert resent.status_code==200
    assert repo.flows.find_one({'_id':digest(body['flow_id'])})['otp_attempts']==1
    assert client.post(BASE+'/auth/verify-email',json=verify).status_code==409
    current={**access,'challenge_id':resent.json()['challenge_id'],'code':repo.mailer.messages[-1][1]}
    assert client.post(BASE+'/auth/verify-email',json=current).status_code==200


def test_resend_delivery_cap_is_enforced_per_email(setup):
    client,repo=setup
    body,verify,_=pending_account(client)
    access={k:body[k] for k in ('flow_id','attempt_id','session_token')}
    for _ in range(4):
        repo.flows.update_one({'_id':digest(body['flow_id'])},{'$set':{'resend_at':now()-timedelta(seconds=1)}})
        assert client.post(BASE+'/auth/resend-verification',json=access).status_code==200
    repo.flows.update_one({'_id':digest(body['flow_id'])},{'$set':{'resend_at':now()-timedelta(seconds=1)}})
    assert client.post(BASE+'/auth/resend-verification',json=access).status_code==429
    assert len(repo.mailer.messages)==5


def test_delivery_failure_and_cancelled_codes_never_activate_accounts(setup):
    from fastapi import HTTPException
    client,repo=setup
    attempt=begin(client)
    with patch.object(repo.mailer,'send_otp',side_effect=HTTPException(503,'Synthetic mail outage')):
        failed,body=complete(client,attempt)
    assert failed.status_code==503
    assert repo.accounts.count_documents({})==0
    retry=client.post(BASE+'/auth/complete',json=body)
    assert retry.json()['verification_required']
    verify={k:body[k] for k in ('flow_id','attempt_id','session_token')}
    verify.update(challenge_id=retry.json()['challenge_id'],code=repo.mailer.messages[-1][1])
    client.post(BASE+'/auth/attempts/cancel',json={k:body[k] for k in ('flow_id','attempt_id')})
    assert client.post(BASE+'/auth/verify-email',json=verify).status_code==409
    assert repo.accounts.count_documents({})==0


def test_concurrent_otp_verification_is_single_use_and_idempotent(setup):
    client,repo=setup
    body,verify,_=pending_account(client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post(BASE+'/auth/verify-email',json=verify),range(2)))
    assert [r.status_code for r in results]==[200,200]
    assert len({r.json()['id'] for r in results})==1
    assert repo.accounts.count_documents({})==1
    assert repo.sessions.count_documents({})==1


def test_email_case_normalization_password_check_and_no_duplicate_registration(setup):
    client,repo=setup
    body,verify,_=pending_account(client,email='Case.Test@EXAMPLE.test')
    response=client.post(BASE+'/auth/verify-email',json=verify)
    assert response.json()['email']=='case.test@example.test'
    wrong,_=complete(client,begin(client,'login'),email='CASE.TEST@example.test',password='A different passphrase')
    unknown,_=complete(client,begin(client,'login'),email='unknown@example.test',password=PASSWORD)
    assert wrong.status_code==401
    assert wrong.json()['detail']=='Email or password is incorrect.'
    assert unknown.status_code==404
    assert 'No account was found for this email address' in unknown.json()['detail']
    good,_=complete(client,begin(client,'login'),email='CASE.TEST@example.test',password=PASSWORD)
    assert good.json()['id']==response.json()['id']
    duplicate,_=complete(client,begin(client),email='case.test@example.test',password='A different passphrase')
    assert duplicate.status_code==409
    assert repo.accounts.count_documents({})==1


def test_legacy_pending_account_resumes_verification_only_after_password_proof(setup):
    client,repo=setup
    legacy, body, _ = legacy_reservation(client, repo)
    bad,_=complete(client,begin(client,'login'),email=body['email'],password='Incorrect passphrase')
    assert bad.status_code==401
    recovered,_=complete(client,begin(client,'login'),email=body['email'],password=PASSWORD)
    assert recovered.status_code==200
    assert recovered.json()['email_verified']
    assert recovered.json()['id'] == legacy['id']
    assert repo.accounts.count_documents({})==1


@pytest.mark.parametrize('ending', ['cancelled', 'superseded', 'expired'])
def test_unverified_candidates_expire_or_cancel_without_reserving_identity(setup, ending):
    client, repo = setup
    body, proof, _ = pending_account(client)
    if ending == 'cancelled':
        client.post(BASE + '/auth/attempts/cancel', json={key: body[key] for key in ('flow_id', 'attempt_id')})
    elif ending == 'superseded':
        begin(client, flow=body['flow_id'], generation=2)
    else:
        repo.flows.update_one({'_id': digest(body['flow_id'])}, {'$set': {'attempt_expires_at': now() - timedelta(seconds=1)}})
    assert client.post(BASE + '/auth/verify-email', json=proof).status_code == 409
    assert repo.accounts.count_documents({}) == 0
    _, fresh_proof, _ = pending_account(client, email=body['email'])
    assert client.post(BASE + '/auth/verify-email', json=fresh_proof).status_code == 200


def test_pending_registration_retries_keep_one_candidate_and_cannot_change_credentials(setup):
    client, repo = setup
    body, proof, receipt = pending_account(client)
    flow = repo.flows.find_one({'_id': digest(body['flow_id'])})
    assert client.post(BASE + '/auth/complete', json=body).json() == receipt
    changed = client.post(BASE + '/auth/complete', json={**body, 'password': 'Another synthetic passphrase'})
    assert changed.status_code == 409
    assert repo.flows.find_one({'_id': flow['_id']})['registration_candidate'] == flow['registration_candidate']
    assert repo.accounts.count_documents({}) == 0
    login, _ = complete(client, begin(client, 'login'), email=body['email'])
    # An unverified registration candidate has not created an account yet.
    assert login.status_code == 404
    assert client.post(BASE + '/auth/verify-email', json=proof).status_code == 200


def test_two_proved_registrations_cannot_adopt_each_others_account(setup):
    client, repo = setup
    first, first_proof, _ = pending_account(client, email='concurrent@example.test')
    second, second_proof, _ = pending_account(client, email=first['email'], password='Another synthetic passphrase')
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda proof: client.post(BASE + '/auth/verify-email', json=proof), [first_proof, second_proof]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json()['id'] for response in responses if response.status_code == 200)
    loser_body, loser_proof = (first, first_proof) if responses[0].status_code == 409 else (second, second_proof)
    assert client.post(BASE + '/auth/verify-email', json=loser_proof).status_code == 409
    assert client.post(BASE + '/auth/complete', json=loser_body).status_code == 409
    assert repo.accounts.find_one({})['id'] == winner
    assert repo.accounts.count_documents({}) == repo.sessions.count_documents({}) == 1


def test_committed_signup_with_lost_insert_response_recovers_only_its_original_proof(setup):
    client, repo = setup
    body, proof, _ = pending_account(client)
    insert = repo.accounts.insert_one
    def commit_then_fail(document):
        insert(document)
        raise AutoReconnect('Synthetic response lost after account insert')
    with patch.object(repo.accounts, 'insert_one', side_effect=commit_then_fail):
        assert client.post(BASE + '/auth/verify-email', json=proof).status_code == 503
    assert repo.accounts.count_documents({}) == 1
    assert repo.sessions.count_documents({}) == 0
    wrong = '000000' if proof['code'] != '000000' else '111111'
    assert client.post(BASE + '/auth/verify-email', json={**proof, 'code': wrong}).status_code == 400
    recovered = client.post(BASE + '/auth/verify-email', json=proof)
    assert recovered.status_code == 200
    assert client.post(BASE + '/auth/complete', json=body).json() == recovered.json()
    assert repo.accounts.count_documents({}) == repo.sessions.count_documents({}) == 1


def test_legacy_reservation_reclaim_uses_new_owner_and_invalidates_old_otp(setup):
    client, repo = setup
    legacy, old_body, old_proof = legacy_reservation(client, repo)
    body, proof, _ = pending_account(client, email=old_body['email'], password='Rightful new synthetic passphrase')
    assert repo.accounts.find_one({})['id'] == legacy['id']
    verified = client.post(BASE + '/auth/verify-email', json=proof)
    assert verified.status_code == 200, verified.text
    account = repo.accounts.find_one({})
    assert account['id'] != legacy['id'] and account['owner'] != legacy['owner']
    assert repo.accounts.count_documents({}) == 1
    assert client.post(BASE + '/auth/verify-email', json=old_proof).status_code == 409
    assert client.post(BASE + '/auth/complete', json=old_body).status_code == 409
    assert client.get(BASE, headers={'Authorization': 'Bearer ' + body['session_token']}).json()['version'] == 0
    rejected, _ = complete(client, begin(client, 'login'), email=body['email'], password=old_body['password'])
    assert rejected.status_code == 401
    accepted, _ = complete(client, begin(client, 'login'), email=body['email'], password=body['password'])
    assert accepted.status_code == 200 and accepted.json()['id'] == account['id']


@pytest.mark.parametrize('protection', ['profile_versions', 'profile_mutations', 'capability_mutations',
                                      'session', 'declarations', 'migration', 'verified_history', 'unknown_metadata',
                                      'malformed_legacy'])
def test_legacy_reclaim_preserves_saved_data_and_protected_records(setup, protection):
    client, repo = setup
    legacy, old_body, _ = legacy_reservation(client, repo)
    _, proof, _ = pending_account(client, email=old_body['email'])
    database = repo.accounts.database
    if protection in ('profile_versions', 'profile_mutations'):
        database[protection].insert_one({'owner': legacy['owner'], 'version': 1, 'mutation_id': 'synthetic'})
    elif protection == 'capability_mutations':
        database.capability_mutations.insert_one({'user_id': legacy['id'], 'mutation_id': 'synthetic'})
    elif protection == 'session':
        repo.sessions.insert_one({'account_id': legacy['id'], 'revoked': True})
    else:
        changes = {'declarations': {'capability_declarations': [{'id': 'synthetic', 'statement': 'Preserve me'}]},
                   'migration': {'migration_pending': True}, 'verified_history': {'email_verified_at': now()},
                   'unknown_metadata': {'legacy_import': True}, 'malformed_legacy': {'email': None}}[protection]
        repo.accounts.update_one({'id': legacy['id']}, {'$set': changes})
    before = repo.accounts.find_one({'id': legacy['id']})
    assert client.post(BASE + '/auth/verify-email', json=proof).status_code == 409
    assert repo.accounts.find_one({'id': legacy['id']}) == before
    assert repo.accounts.count_documents({}) == 1
    response, _ = complete(client, begin(client), email=old_body['email'])
    assert response.status_code == 409


def test_legacy_replacement_rechecks_record_at_atomic_write(setup):
    client, repo = setup
    legacy, body, _ = legacy_reservation(client, repo)
    _, proof, _ = pending_account(client, email=body['email'])
    replace = repo.accounts.find_one_and_replace
    def verification_wins(query, document, **kwargs):
        repo.accounts.update_one({'id': legacy['id']}, {'$set': {'email_verified': True, 'email_verified_at': now()}})
        return replace(query, document, **kwargs)
    with patch.object(repo.accounts, 'find_one_and_replace', side_effect=verification_wins):
        assert client.post(BASE + '/auth/verify-email', json=proof).status_code == 409
    assert repo.accounts.find_one({})['id'] == legacy['id']
    assert repo.accounts.count_documents({}) == 1


def test_lost_legacy_replacement_response_replays_its_fresh_identity(setup):
    client, repo = setup
    legacy, body, old_proof = legacy_reservation(client, repo)
    _, proof, _ = pending_account(client, email=body['email'])
    replace = repo.accounts.find_one_and_replace
    def commit_then_fail(*args, **kwargs):
        replace(*args, **kwargs)
        raise AutoReconnect('Synthetic response lost after reservation replacement')
    with patch.object(repo.accounts, 'find_one_and_replace', side_effect=commit_then_fail):
        assert client.post(BASE + '/auth/verify-email', json=proof).status_code == 503
    current = repo.accounts.find_one({})
    assert current['id'] != legacy['id']
    assert client.post(BASE + '/auth/verify-email', json=old_proof).status_code == 409
    result = client.post(BASE + '/auth/verify-email', json=proof)
    assert result.status_code == 200 and result.json()['id'] == current['id']
    assert repo.accounts.count_documents({}) == repo.sessions.count_documents({}) == 1


def test_unverified_google_reservation_requires_its_subject_login_and_is_not_reclaimed(setup):
    client, repo = setup
    google(client)
    attempt = begin(client)
    access = {key: attempt[key] for key in ('flow_id', 'attempt_id')}
    access['session_token'] = token_urlsafe(32)
    with patch('app.core.auth.id_token.verify_oauth2_token', return_value=claims(attempt)):
        pending = client.post(BASE + '/auth/complete', json={**access, 'credential': 'verified'})
    assert pending.status_code == 200
    flow = repo.flows.find_one({'_id': digest(attempt['flow_id'])})
    legacy = flow['registration_candidate']
    repo.accounts.insert_one(legacy)
    repo.flows.update_one({'_id': flow['_id']}, {'$unset': {'registration_candidate': '', 'registration_replaces': ''}})
    new_attempt = begin(client)
    with patch('app.core.auth.id_token.verify_oauth2_token', return_value=claims(new_attempt)):
        rejected, _ = complete(client, new_attempt, credential='verified')
    assert rejected.status_code == 409
    assert repo.accounts.find_one({})['id'] == legacy['id']
    login = begin(client, 'login')
    with patch('app.core.auth.id_token.verify_oauth2_token', return_value=claims(login)):
        recovered, _ = complete(client, login, credential='verified')
    assert recovered.status_code == 200 and recovered.json()['id'] == legacy['id']
    assert repo.accounts.count_documents({}) == 1


def finish_setup(client,headers,version=0,key=None,**changes):
    body={'expected_version':version,'occupational_status':'employed','school_category':None,'no_previous_education':True,**changes}
    if body['occupational_status']=='employed' and 'employment' not in body:
        body['employment']={'employer':'Synthetic employer','role':'Synthetic analyst','industry':'Synthetic industry'}
    return client.post(BASE+'/onboarding/complete',headers={**headers,'Idempotency-Key':key or uuid4().hex},json=body)


@pytest.mark.parametrize('category',['secondary','ite','polytechnic','junior_college','university'])
def test_student_completion_requires_institution_and_current_year_but_not_course_or_planning(setup,category):
    client,repo=setup
    _,headers,_,_=register(client)
    saved=finish_setup(client,headers,occupational_status='student',school_category=category,no_previous_education=False,
                       education={'institution':{'kind':'custom','name':'Synthetic school'},'study_year':5})
    assert saved.status_code==200,saved.text
    profile=saved.json()
    assert profile['onboarding_state']=='complete' and profile['onboarding_complete']
    assert profile['onboarding_completed_at']
    assert profile['application_date'] is None and profile['weekly_hours'] is None
    assert profile['education']['course'] is None
    assert client.get(BASE,headers=headers).json()['onboarding_complete']


@pytest.mark.parametrize('status',['national_service','unemployed','employed'])
def test_explicit_no_previous_education_path_persists(setup,status):
    client,_=setup
    _,headers,_,_=register(client)
    result=finish_setup(client,headers,occupational_status=status,**({'previously_employed':False} if status=='unemployed' else {}))
    assert result.status_code==200
    assert result.json()['no_previous_education'] is True
    assert result.json()['onboarding_complete']


def test_partial_save_and_legacy_profile_are_not_completion(setup):
    client,repo=setup
    _,headers,_,_=register(client)
    partial=client.patch(BASE,headers=headers,json={'expected_version':0,'occupational_status':'employed'})
    assert partial.status_code==200 and not partial.json()['onboarding_complete']
    assert partial.json()['onboarding_state']=='incomplete'
    assert finish_setup(client,headers,version=1,no_previous_education=False).status_code==422
    owner=repo.session(headers['Authorization'].split()[1])['owner']
    legacy=repo.accounts.database.profile_versions.find_one({'owner':owner})
    legacy['profile'].pop('onboarding_complete',None)
    legacy['profile'].pop('onboarding_completed_at',None)
    repo.accounts.database.profile_versions.replace_one({'_id':legacy['_id']},legacy)
    restored=client.get(BASE,headers=headers).json()
    assert restored['onboarding_state']=='legacy_unconfirmed' and restored['occupational_status']=='employed'
    assert finish_setup(client,headers,version=1).json()['onboarding_complete']


def test_finish_retries_and_later_partial_edits_never_downgrade_completion(setup):
    client,repo=setup
    _,headers,_,_=register(client)
    first=finish_setup(client,headers,key='finish-key')
    again=finish_setup(client,headers,key='finish-key')
    assert first.json()==again.json()
    current=client.patch(BASE,headers=headers,json={'expected_version':1,'occupational_status':'unemployed'})
    assert current.status_code==200 and current.json()['onboarding_complete']
    assert finish_setup(client,headers,key='finish-key').json()==current.json()
    assert client.get(BASE+'/versions/1',headers=headers).json()['occupational_status']=='employed'
    assert repo.accounts.database.profile_versions.count_documents({})==2


def test_lost_committed_completion_response_is_recoverable_without_duplicate_version(setup):
    client,_=setup
    _,headers,_,_=register(client)
    collection=client.app.state.repository.collection
    insert=collection.insert_one
    def commit_then_fail(document):
        insert(document)
        raise AutoReconnect('Synthetic response lost after commit')
    with patch.object(collection,'insert_one',side_effect=commit_then_fail):
        assert finish_setup(client,headers,key='lost-completion').status_code==503
    assert client.get(BASE,headers=headers).json()['onboarding_complete']
    assert finish_setup(client,headers,key='lost-completion').json()['version']==1
    assert collection.count_documents({})==1


def test_legacy_mapping_is_explicit_idempotent_and_preserves_history(setup):
    from app.domain.legacy import map_legacy_owner
    from app.schemas.profile import ProfilePatch
    client,repo=setup
    account,headers,_,_=register(client)
    database=repo.accounts.database
    profiles=client.app.state.repository
    profiles.update('local_test:legacy-fixture',ProfilePatch(expected_version=0,occupational_status='employed'))
    settings=client.app.state.auth_settings
    preview=map_legacy_owner(database,settings,account['id'],'local_test:legacy-fixture')
    assert not preview['mapped']
    assert map_legacy_owner(database,settings,account['id'],'local_test:legacy-fixture',True)['changed']
    assert not map_legacy_owner(database,settings,account['id'],'local_test:legacy-fixture',True)['changed']
    assert database.profile_versions.count_documents({})==1
    assert profiles.version('local_test:legacy-fixture',1)['occupational_status']=='employed'
    assert client.get(BASE,headers=headers).status_code==401
    assert repo.accounts.find_one({'id':account['id']})['owner']=='local_test:legacy-fixture'


def test_password_attempt_rate_limit_is_enforced_without_account_creation(setup):
    client,repo=setup
    email='limited@example.test'
    for _ in range(10):
        response,_=complete(client,begin(client,'login'),email=email,password=PASSWORD)
        assert response.status_code==404
    assert complete(client,begin(client,'login'),email=email,password=PASSWORD)[0].status_code==429
    assert repo.accounts.count_documents({})==0


def test_legacy_mapping_rejects_production_other_owner_and_populated_target(setup):
    from app.domain.legacy import map_legacy_owner
    from app.schemas.profile import ProfilePatch
    from dataclasses import replace
    client,repo=setup
    account,headers,_,_=register(client)
    database=repo.accounts.database
    profiles=client.app.state.repository
    settings=client.app.state.auth_settings
    profiles.update('local_test:legacy-fixture',ProfilePatch(expected_version=0,occupational_status='employed'))
    with pytest.raises(ValueError):
        map_legacy_owner(database,replace(settings,environment='production'),account['id'],'local_test:legacy-fixture',True)
    with pytest.raises(ValueError):
        map_legacy_owner(database,settings,account['id'],'google:someone',True)
    client.patch(BASE,headers=headers,json={'expected_version':0,'occupational_status':'employed'})
    with pytest.raises(ValueError):
        map_legacy_owner(database,settings,account['id'],'local_test:legacy-fixture',True)
    assert database.profile_versions.count_documents({})==2


def test_concurrent_finish_and_partial_save_cannot_overwrite_or_downgrade_completion(setup):
    client,_=setup
    _,headers,_,_=register(client)
    def finish(): return finish_setup(client,headers,key='concurrent-finish')
    def partial(): return client.patch(BASE,headers=headers,json={'expected_version':0,'occupational_status':'unemployed'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(finish),pool.submit(partial)]
        results=[future.result().status_code for future in futures]
    assert sorted(results)==[200,409]
    current=client.get(BASE,headers=headers).json()
    if not current['onboarding_complete']:
        finished=finish_setup(client,headers,version=current['version'],key='reconciled-finish',occupational_status=current['occupational_status'],previously_employed=False)
        assert finished.status_code==200
        assert finished.json()['occupational_status']=='unemployed'
    latest=client.get(BASE,headers=headers).json()
    changed=client.patch(BASE,headers=headers,json={'expected_version':latest['version'],'occupational_status':'national_service'})
    assert changed.json()['onboarding_complete']


def test_legacy_google_account_retains_owner_and_history_after_email_verification(setup):
    from app.schemas.profile import ProfilePatch
    client,repo=setup
    repo.accounts.insert_one({'id':'legacy-google-id','identity':'google:stable-subject','provider':'google',
                              'owner':'google:stable-subject','name':'Synthetic legacy Google'})
    client.app.state.repository.update('google:stable-subject',ProfilePatch(expected_version=0,occupational_status='employed'))
    google(client)
    attempt=begin(client,'login')
    with patch('app.core.auth.id_token.verify_oauth2_token',return_value=claims(attempt)):
        response,body=complete(client,attempt,credential='verified')
    assert response.status_code==200,response.text
    assert response.json()['id']=='legacy-google-id'
    assert response.json()['email_verified']
    restored=client.get(BASE,headers={'Authorization':'Bearer '+body['session_token']}).json()
    assert restored['version']==1 and restored['occupational_status']=='employed'
    assert repo.accounts.count_documents({})==1


def test_email_mode_accepts_any_domain_requires_otp_and_rejects_google(setup):
    from dataclasses import replace
    client, repo = setup
    client.app.state.auth_settings = replace(client.app.state.auth_settings, mode='email', google_client_id='')
    config = client.get(BASE+'/auth-config').json()
    assert config['mode'] == 'email' and config['google_enabled'] is False
    assert config['email_verification_required'] is True
    assert client.get(BASE+'/auth/local-accounts').status_code == 404
    rejected, _ = complete(client, begin(client), credential='unaccepted-google-credential')
    assert rejected.status_code == 401
    for domain in ('gmail.com', 'outlook.com', 'school.example.test'):
        email = 'synthetic-'+uuid4().hex+'@'+domain
        body, verify, response = pending_account(client, email=email)
        assert response['verification_required'] is True
        assert repo.mailer.messages[-1][0] == email
        assert client.get(BASE, headers={'Authorization':'Bearer '+body['session_token']}).status_code == 401
        verified = client.post(BASE+'/auth/verify-email', json=verify)
        assert verified.status_code == 200 and verified.json()['provider'] == 'email'
        assert verified.json()['email'] == email and verified.json()['email_verified'] is True
        login, _ = complete(client, begin(client,'login'), email=email, password=PASSWORD)
        assert login.status_code == 200 and login.json()['id'] == verified.json()['id']
