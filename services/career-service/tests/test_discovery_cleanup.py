"""A saved career goal removes every other discovery chat and stops its research."""
import asyncio
import threading
import time
import pytest
from tests.test_discovery import OWNER, flow, headers, start, wait

DISCOVERIES = '/api/v1/career/discoveries'


def until(condition, message):
    for _ in range(400):
        if condition():return
        time.sleep(.01)
    pytest.fail(message)


def blocked_first_plan(ai):
    release = threading.Event(); plans = []
    async def hook(request, _data):
        if request.stage != 'discovery_plan':return
        plans.append(request)
        if len(plans) == 1:
            while not release.is_set():await asyncio.sleep(.01)
    ai.hook = hook
    return release, plans


@pytest.mark.parametrize('flow', ['free', 'premium'], indirect=True)
def test_a_discovery_goal_removes_the_other_chats_and_cancels_their_research(flow):
    client, db, ai, _ = flow
    release, plans = blocked_first_plan(ai)
    idle = start(flow, 'Unsure')
    stuck = start(flow)
    until(lambda: len(plans) == 1, 'the first research did not start')
    saved = wait(flow, start(flow))
    assert saved['stage'] == 'career_goal_updated'
    for removed in (idle, stuck):
        assert client.get(f"{DISCOVERIES}/{removed['id']}", headers=headers()).status_code == 404
    assert [item['id'] for item in client.get(DISCOVERIES, headers=headers()).json()['items']] == [saved['id']]
    assert client.get(DISCOVERIES + '/current', headers=headers()).json()['session']['id'] == saved['id']
    until(lambda: stuck['id'] not in client.app.state.discovery.tasks, 'the removed research kept running')
    calls = len(ai.calls); release.set(); time.sleep(.2)
    assert len(ai.calls) == calls
    assert db.research_contexts.count_documents({'owner': OWNER, 'kind': 'career_discovery'}) == 1


def test_premium_starts_a_new_chat_that_a_repeated_cleanup_keeps(flow):
    client, db, _, _ = flow
    old = start(flow, 'Unsure')
    saved = wait(flow, start(flow))
    fresh = client.post(DISCOVERIES, headers=headers(), json={'consent': True})
    assert fresh.status_code == 200, fresh.text
    client.app.state.goal_store.clear_discoveries(OWNER)
    kept = {row['_id'] for row in db.research_contexts.find({'owner': OWNER, 'kind': 'career_discovery'})}
    assert kept == {saved['id'], fresh.json()['session']['id']} and old['id'] not in kept


@pytest.mark.parametrize('flow', ['free'], indirect=True)
def test_a_free_account_with_a_goal_cannot_start_another_chat(flow):
    wait(flow, start(flow))
    blocked = flow[0].post(DISCOVERIES, headers=headers(), json={'consent': True})
    assert blocked.status_code == 402 and blocked.json()['code'] == 'premium_required'

