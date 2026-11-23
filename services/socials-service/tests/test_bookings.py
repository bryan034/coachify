import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from elo_shared.runtime import Problem
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import AutoReconnect

from app.bookings import Socials
from app.main import create_app

PREFIX = '/api/v1/socials'
EXPERT = 'expert-id'
OWNER = 'member-id'
OTHER = 'other-id'
OPERATOR = 'operator-id'
DIRECTORY_ID = 'developer'


class Sessions:
    goal_available = True

    async def account(self, token):
        account_id = token.removeprefix('Bearer ')
        names = {OWNER: 'Lee', OTHER: 'Tan', EXPERT: 'Rao', OPERATOR: 'Ng'}
        if account_id not in names:
            raise Problem('Sign in to continue.', 401, 'session')
        return {'id': account_id, 'name': names[account_id], 'token': token}

    async def read(self, service, path, token):
        assert (service, path) == ('career', '/api/v1/career/goals/current')
        if not self.goal_available:
            raise Problem('Career is unavailable.', 503, 'upstream')
        return {'goal': {'role': 'Developer', 'field': 'Technology'}}


@pytest.fixture
def stack():
    uri = os.getenv('MONGODB_TEST_URI')
    if not uri:
        pytest.skip('Set an explicit disposable MONGODB_TEST_URI.')
    with MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000) as mongo:
        database = mongo[f'elo_socials_test_{uuid4().hex}']
        store = Socials(database)
        upstream = Sessions()
        app = create_app(store=store, upstream=upstream, operator_ids={OPERATOR}, recover=False)
        try:
            with TestClient(app) as client:
                yield client, store, database, upstream
        finally:
            mongo.drop_database(database.name)


def call(client, method, path, actor=OWNER, body=None):
    options = {'headers': {'Authorization': f'Bearer {actor}'}}
    if body is not None:
        options['json'] = body
    return client.request(method, PREFIX + path, **options)


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def key():
    return str(uuid4())


def grant(client, actor=OWNER, credits=1, *, enabled=True, mutation_id=None):
    return ok(call(client, 'PUT', f'/operator/members/{actor}/access', OPERATOR, {
        'mutation_id': mutation_id or key(), 'enabled': enabled, 'credits': credits,
    }))


def expert(client, expert_id=DIRECTORY_ID, account_id=EXPERT):
    return ok(call(client, 'PUT', f'/operator/experts/{expert_id}', OPERATOR, {
        'account_id': account_id, 'name': 'Rao', 'role': 'Software Engineer', 'field': 'Engineering',
        'organisation': 'Example Studio', 'linkedin_url': 'https://www.linkedin.com/in/synthetic',
        'aliases': ['Developer'],
    }))


def slot_body(hour=3, *, offset=0, mutation_id=None, durations=(30, 60)):
    future = (datetime.now(UTC) + timedelta(days=2)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return {'mutation_id': mutation_id or key(), 'starts_at': (future + timedelta(minutes=offset)).isoformat(),
            'durations': list(durations)}


def slot(client, **options):
    return ok(call(client, 'POST', f'/operator/experts/{DIRECTORY_ID}/slots', OPERATOR, slot_body(**options)))


def request_body(offer, duration=30):
    return {'mutation_id': key(), 'expert_id': DIRECTORY_ID, 'slot_id': offer['id'], 'slot_version': offer['version'],
            'duration_minutes': duration, 'question': 'How do you collaborate on projects?', 'adult_attested': True}


def decide(client, booking, decision, body=None):
    return call(client, 'POST', f'/bookings/{booking["id"]}/decision', EXPERT, body or {
        'mutation_id': key(), 'expected_version': booking['version'], 'decision': decision,
        **({'meeting_url': 'https://meet.example.com/synthetic'} if decision == 'accept' else {}),
    })


def workspace(client, actor=OWNER):
    return ok(call(client, 'GET', '/workspace', actor))


def test_member_and_expert_flow_privacy_and_reports(stack):
    client, _, _, upstream = stack
    expert(client)
    offer = slot(client)
    assert workspace(client) == {'access': 'locked', 'credits': 0, 'experts': [], 'recommendation': None,
                                 'bookings': [], 'expert_inbox': False}
    assert call(client, 'GET', f'/experts/{DIRECTORY_ID}/slots').status_code == 403
    assert call(client, 'GET', '/operator/reports').status_code == 403
    assert call(client, 'GET', '/expert/requests').status_code == 403
    assert call(client, 'POST', '/bookings', body=request_body(offer)).status_code == 403
    grant_id = key()
    assert grant(client, credits=2, mutation_id=grant_id)['credits'] == 2
    assert grant(client, credits=2, mutation_id=grant_id)['credits'] == 2
    assert workspace(client)['recommendation'] == {'expert_id': DIRECTORY_ID, 'role': 'Developer'}
    upstream.goal_available = False
    current = workspace(client)
    assert current['recommendation'] is None
    assert current['experts'][0]['open_slots'] == 1
    assert ok(call(client, 'GET', f'/experts/{DIRECTORY_ID}/slots')) == [offer]

    command = request_body(offer, duration=60)
    booking = ok(call(client, 'POST', '/bookings', body=command))
    assert (booking['status'], booking['credits']) == ('requested', 2)
    assert ok(call(client, 'POST', '/bookings', body=command))['id'] == booking['id']
    assert call(client, 'POST', '/bookings', body={**command, 'question': 'Different'}).status_code == 409
    assert workspace(client)['credits'] == 0
    assert workspace(client)['experts'][0]['open_slots'] == 0
    assert ok(call(client, 'GET', '/agenda')) == []
    assert ok(call(client, 'GET', '/expert/requests', EXPERT))[0]['member_name'] == 'Lee'
    decision_path = f'/bookings/{booking["id"]}/decision'
    assert call(client, 'POST', decision_path, OTHER, {
        'mutation_id': key(), 'expected_version': booking['version'], 'decision': 'decline',
    }).status_code == 404
    command = {'mutation_id': key(), 'expected_version': booking['version'], 'decision': 'accept',
               'meeting_url': 'https://meet.example.com/synthetic'}
    bad_link = {**command, 'meeting_url': 'https://meet.example.com:bad/synthetic'}
    assert decide(client, booking, 'accept', bad_link).status_code == 422
    accepted = ok(decide(client, booking, 'accept', command))
    assert accepted['status'] == 'accepted'
    assert workspace(client)['bookings'][0]['meeting_url'] == command['meeting_url']
    assert ok(call(client, 'GET', '/agenda', OTHER)) == []
    follow_up_path = f'/bookings/{booking["id"]}/follow-up'
    follow_up = {'mutation_id': key(), 'expected_version': accepted['version'], 'prep_done': True, 'notes': 'Private notes'}
    assert call(client, 'PATCH', follow_up_path, EXPERT, follow_up).status_code == 404
    assert ok(call(client, 'PATCH', follow_up_path, OWNER, follow_up))['notes'] == 'Private notes'
    assert ok(call(client, 'GET', '/agenda'))[0]['prep_done'] is True
    assigned = ok(call(client, 'GET', '/expert/requests', EXPERT))[0]
    assert (assigned['status'], assigned['meeting_url'], assigned['prep_done'], assigned['notes']) == (
        'accepted', command['meeting_url'], False, '',
    )
    assert ok(decide(client, booking, 'accept', command))['notes'] == ''

    grant(client, enabled=False, credits=0)
    assert workspace(client)['bookings'][0]['status'] == 'accepted'
    report_path = f'/bookings/{booking["id"]}/reports'
    report = {'mutation_id': key(), 'reason': 'Please review this chat.'}
    assert call(client, 'POST', report_path, OTHER, report).status_code == 404
    receipt = ok(call(client, 'POST', report_path, OWNER, report))
    assert ok(call(client, 'POST', report_path, OWNER, report)) == receipt
    assert call(client, 'POST', report_path, OWNER, {**report, 'reason': 'Different'}).status_code == 409
    expert_receipt = ok(call(client, 'POST', report_path, EXPERT, report))
    assert {row['id'] for row in ok(call(client, 'GET', '/operator/reports', OPERATOR))} == {
        receipt['id'], expert_receipt['id'],
    }


def test_daily_schedules_prevent_overlaps_and_preserve_publish_replays(stack):
    client, _, _, _ = stack
    expert(client)
    path = f'/operator/experts/{DIRECTORY_ID}/slots'
    command = slot_body()
    results = race(
        lambda: call(client, 'POST', path, OPERATOR, command),
        lambda: call(client, 'POST', path, OPERATOR, command),
    )
    assert ok(results[0]) == ok(results[1])
    conflict = call(client, 'POST', path, OPERATOR, slot_body(offset=30))
    assert (conflict.status_code, conflict.json()['code']) == (409, 'slot_overlap')
    adjacent = slot(client, offset=60)
    assert adjacent['id'] != ok(results[0])['id']
    changed = call(client, 'POST', path, OPERATOR, {**command, 'durations': [30]})
    assert (changed.status_code, changed.json()['code']) == (409, 'mutation_reused')


def race(first, second):
    start = Barrier(2)

    def execute(action):
        start.wait(timeout=5)
        return action()

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(execute, operation) for operation in (first, second)]
        return [result.result(timeout=15) for result in futures]


def test_one_slot_and_one_wallet_cannot_be_spent_twice(stack, monkeypatch):
    client, store, _, _ = stack
    expert(client)
    shared_slot = slot(client)
    grant(client)
    grant(client, OTHER)
    ready_to_claim = Barrier(2)
    original_claim = store.schedules.claim

    def race_claim(booking):
        ready_to_claim.wait(timeout=5)
        return original_claim(booking)

    with monkeypatch.context() as patch:
        patch.setattr(store.schedules, 'claim', race_claim)
        requests = race(
            lambda: call(client, 'POST', '/bookings', OWNER, request_body(shared_slot)),
            lambda: call(client, 'POST', '/bookings', OTHER, request_body(shared_slot)),
        )
    assert {ok(response)['status'] for response in requests} == {'requested', 'slot_unavailable'}
    assert sorted(workspace(client, actor)['credits'] for actor in (OWNER, OTHER)) == [0, 1]
    refunded_member = next(actor for actor in (OWNER, OTHER) if workspace(client, actor)['credits'] == 1)
    assert call(client, 'POST', '/bookings', refunded_member, request_body(shared_slot)).json()['code'] == 'slot_unavailable'

    grant(client, OPERATOR)
    first, second = slot(client, hour=5), slot(client, hour=6)
    requests = race(
        lambda: call(client, 'POST', '/bookings', OPERATOR, request_body(first)),
        lambda: call(client, 'POST', '/bookings', OPERATOR, request_body(second)),
    )
    assert sorted(response.status_code for response in requests) == [200, 409]
    assert workspace(client, OPERATOR)['credits'] == 0
    assert len(workspace(client, OPERATOR)['bookings']) == 1


def test_decline_and_accept_race_settles_once(stack):
    client, store, _, _ = stack
    expert(client)
    offer = slot(client)
    grant(client)
    booking = ok(call(client, 'POST', '/bookings', body=request_body(offer)))
    results = race(
        lambda: decide(client, booking, 'accept'),
        lambda: decide(client, booking, 'decline'),
    )
    assert sorted(response.status_code for response in results) == [200, 409]
    status = workspace(client)['bookings'][0]['status']
    refunded = int(status == 'declined')
    store.recover()
    assert workspace(client)['credits'] == refunded
    assert workspace(client)['experts'][0]['open_slots'] == refunded


def test_recovery_resumes_claim_and_releases_decline_after_interruption(stack, monkeypatch):
    client, store, database, _ = stack
    expert(client)
    offer = slot(client)
    grant(client)
    command = request_body(offer)
    real_claim = store.schedules.claim

    def interrupt_after_claim(booking):
        assert real_claim(booking)
        raise AutoReconnect('Synthetic interruption')

    with monkeypatch.context() as patch:
        patch.setattr(store.schedules, 'claim', interrupt_after_claim)
        assert call(client, 'POST', '/bookings', body=command).status_code == 503
    assert database.wallets.find_one({'_id': OWNER})['bookings'][0]['status'] == 'submitting'
    store.recover()
    booking = ok(call(client, 'POST', '/bookings', body=command))
    assert (booking['status'], workspace(client)['credits']) == ('requested', 0)
    decision = {'mutation_id': key(), 'expected_version': booking['version'], 'decision': 'decline'}

    def unavailable(_booking):
        raise AutoReconnect('Synthetic interruption')

    with monkeypatch.context() as patch:
        patch.setattr(store.schedules, 'release', unavailable)
        assert decide(client, booking, 'decline', decision).status_code == 503
    current = workspace(client)
    assert (current['credits'], current['experts'][0]['open_slots']) == (1, 0)
    store.recover()
    assert ok(decide(client, booking, 'decline', decision))['status'] == 'declined'
    assert workspace(client)['credits'] == 1
    reopened = ok(call(client, 'GET', f'/experts/{DIRECTORY_ID}/slots'))[0]
    assert reopened['version'] > offer['version']
    assert store.schedules.claim(database.wallets.find_one({'_id': OWNER})['bookings'][0]) is False
    assert ok(call(client, 'POST', '/bookings', body=request_body(reopened)))['status'] == 'requested'


def test_database_clock_closes_expired_offer_before_refund(stack, monkeypatch):
    client, store, database, _ = stack
    expert(client)
    offer = slot(client)
    grant(client)
    command = request_body(offer)
    with monkeypatch.context() as patch:
        def interrupt_before_claim(_booking):
            raise AutoReconnect('Synthetic interruption')

        patch.setattr(store.schedules, 'claim', interrupt_before_claim)
        assert call(client, 'POST', '/bookings', body=command).status_code == 503

    previous = database.wallets.find_one({'_id': OWNER})['bookings'][0]
    past = datetime.now(UTC) - timedelta(seconds=10)
    database.schedules.update_one({'slots.id': offer['id']}, {'$set': {'slots.$.starts_at': past}})
    store.recover()
    assert ok(call(client, 'POST', '/bookings', body=command))['status'] == 'slot_unavailable'
    _, closed = store.schedules.find(offer['id'])
    assert closed['closed'] and closed['held_by'] is None
    assert store.schedules.claim(previous) is False
    assert workspace(client)['credits'] == 1


def test_expert_cannot_accept_after_start(stack):
    client, store, database, _ = stack
    expert(client)
    offer = slot(client)
    grant(client)
    booking = ok(call(client, 'POST', '/bookings', body=request_body(offer)))
    past = datetime.now(UTC) - timedelta(seconds=10)
    database.wallets.update_one({'bookings.id': booking['id']}, {'$set': {'bookings.$.starts_at': past}})
    assert decide(client, booking, 'accept').status_code == 409
    store.recover()
    current = workspace(client)
    assert current['bookings'][0]['status'] == 'expired'
    assert current['credits'] == 1
    assert ok(call(client, 'GET', '/agenda')) == []


@pytest.mark.parametrize('payload', [{'adult_attested': False}, {'adult_attested': 1}, {'duration_minutes': 45}])
def test_request_validates_age_and_duration(stack, payload):
    client, _, _, _ = stack
    expert(client)
    offer = slot(client)
    grant(client)
    response = call(client, 'POST', '/bookings', body={**request_body(offer), **payload})
    assert response.status_code == 422
    assert workspace(client)['credits'] == 1
