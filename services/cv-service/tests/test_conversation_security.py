"""Independent conversation trust-boundary checks using synthetic providers only."""
from copy import deepcopy
import json
import time
from threading import Event
from uuid import uuid4

import httpx
import pytest

from app.clients.conversation import ConversationRouter
from tests.conftest import ready
from tests.test_clarification import prepare_context


PREFIX = '/api/v1/cv/conversations'


class Router:
    def __init__(self, actions=None, reply='This explanation does not change your CV.'):
        self.actions, self.reply, self.calls = actions or [], reply, []

    def route(self, context):
        self.calls.append(deepcopy(context))
        return {'reply': self.reply, 'actions': deepcopy(self.actions)}, {'provider': 'synthetic-security-test'}


def open_chat(client, cv_id=None):
    response = client.post(PREFIX, json={'cv_id': cv_id, 'mutation_id': str(uuid4())})
    assert response.status_code == 200, response.text
    return response.json()


def settled(client, conversation_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(PREFIX + '/' + conversation_id)
        assert response.status_code == 200, response.text
        value = response.json()
        if not any(a['status'] == 'pending' for m in value['messages'] for a in m['actions']):
            return value
        time.sleep(.01)
    raise AssertionError('Synthetic chat processing did not finish within five seconds.')


def send(client, conversation, text, **fields):
    response = client.post(PREFIX + '/' + conversation['id'] + '/messages', json={
        'mutation_id': str(uuid4()), 'expected_revision': conversation['revision'], 'text': text, **fields})
    assert response.status_code == 200, response.text
    return settled(client, conversation['id'])


def test_conversation_and_history_enforce_owner_on_every_entry_point(harness):
    client, app, *_ = harness
    cv = ready(harness)
    chat = open_chat(client, cv['id'])
    app.state.conversations.provider = Router()
    foreign = {'Authorization': 'Bearer owner-b'}
    assert client.get(PREFIX + '/' + chat['id'], headers=foreign).status_code == 404
    assert client.get(PREFIX, params={'cv_id': cv['id']}, headers=foreign).status_code == 404
    assert client.post(PREFIX, headers=foreign, json={
        'cv_id': cv['id'], 'mutation_id': str(uuid4())}).status_code == 404
    assert client.post(PREFIX + '/' + chat['id'] + '/messages', headers=foreign, json={
        'text': 'Change my CV', 'mutation_id': str(uuid4()),
        'expected_revision': chat['revision']}).status_code == 404
    assert client.post(PREFIX + '/' + chat['id'] + '/actions/missing', headers=foreign, json={
        'decision': 'save', 'mutation_id': str(uuid4()),
        'expected_revision': chat['revision']}).status_code == 404
    assert client.get(PREFIX, headers=foreign).json()['conversations'] == []
    assert app.state.conversations.provider.calls == []


def test_revoked_session_cannot_read_or_append_saved_conversation(harness):
    client, app, _, _, transport = harness
    chat = open_chat(client)
    app.state.conversations.provider = Router()
    transport.revoked = True
    assert client.get(PREFIX + '/' + chat['id']).status_code == 401
    assert client.post(PREFIX + '/' + chat['id'] + '/messages', json={
        'text': 'Add a skill', 'mutation_id': str(uuid4()),
        'expected_revision': chat['revision']}).status_code == 401
    transport.revoked = False
    assert client.get(PREFIX + '/' + chat['id']).json()['revision'] == chat['revision']
    assert app.state.conversations.provider.calls == []


@pytest.mark.parametrize('invalid', ['foreign_item', 'foreign_question', 'invented_excerpt',
                                   'execution_control', 'unnamed_capability', 'unknown_kind'])
def test_invalid_model_actions_preserve_raw_message_without_domain_writes(harness, invalid):
    client, app, *_ = harness
    cv, questions = prepare_context(harness, ready(harness))
    question = next(q for q in questions if q['kind'] == 'project')
    chat = open_chat(client, cv['id'])
    text = 'I built the Python screens.'
    action = {'kind': 'clarify', 'item_id': question['item_id'], 'question_id': question['id'], 'excerpt': text}
    if invalid == 'foreign_item': action['item_id'] = 'another-owners-project'
    elif invalid == 'foreign_question': action['question_id'] = 'another-owners-question'
    elif invalid == 'invented_excerpt': action['excerpt'] = 'I have ten years of experience.'
    elif invalid == 'execution_control': action.update(kind='correct', fields={'expected_version': 99, 'title': 'Invented title'})
    elif invalid == 'unnamed_capability': action = {'kind': 'add_capability', 'name': 'Kubernetes', 'excerpt': text}
    else: action['kind'] = 'write_arbitrary_record'
    app.state.conversations.provider = Router([action])
    before = client.get('/api/v1/cv/' + cv['id']).json()
    result = send(client, chat, text)
    assert any(a['kind'] == 'route' and a['status'] == 'failed'
               for m in result['messages'] for a in m['actions'])
    assert any(m['role'] == 'user' and m['text'] == text for m in result['messages'])
    assert client.get('/api/v1/cv/' + cv['id']).json() == before
    assert app.state.interpreter.calls == 0


@pytest.mark.parametrize('text', ['Why are you asking about my contribution?', 'What if I had six months of React experience?'])
def test_side_question_preserves_facts_and_pending_topic(harness, text):
    client, app, *_ = harness
    cv, _ = prepare_context(harness, ready(harness))
    chat = open_chat(client, cv['id'])
    chat = send(client, chat, 'Review with me', command='review')
    assert chat['active_question'] is not None
    before = client.get('/api/v1/cv/' + cv['id']).json()
    app.state.conversations.provider = Router()
    result = send(client, chat, text)
    assert result['active_question'] == chat['active_question']
    assert result['revision'] > chat['revision']
    assert client.get('/api/v1/cv/' + cv['id']).json() == before
    assert app.state.interpreter.calls == 0


@pytest.mark.parametrize('fields', [
    {'text': 'a' * 4001}, {'text': ' '}, {'text': 'hidden\x00control'},
    {'text': 'hello', 'user_id': 'owner-b'}, {'text': 'hello', 'command': 'delete_everything'},
    {'text': 'hello', 'expected_revision': True},
])
def test_invalid_message_input_never_appends_or_calls_provider(harness, fields):
    client, app, *_ = harness
    chat = open_chat(client)
    app.state.conversations.provider = Router()
    response = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
        'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], **fields})
    assert response.status_code == 422, response.text
    assert client.get(PREFIX + '/' + chat['id']).json() == chat
    assert app.state.conversations.provider.calls == []


def test_router_does_not_receive_another_saved_cv(harness):
    client, app, *_ = harness
    first = ready(harness)
    second = ready(harness)
    provider = Router()
    app.state.conversations.provider = provider
    chat = open_chat(client, first['id'])
    send(client, chat, 'Explain what is saved here.')
    supplied_ids = {item['id'] for item in provider.calls[0]['items']}
    assert supplied_ids == {item['id'] for item in first['items']}
    assert supplied_ids.isdisjoint({item['id'] for item in second['items']})


def test_router_excerpt_cannot_strip_negation_from_interpreter_input(harness):
    client, app, *_ = harness
    cv, questions = prepare_context(harness, ready(harness))
    question = next(q for q in questions if q['kind'] == 'project')
    text = 'I did not use Python. My teammate did that work.'
    app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': 'use Python'}])
    seen = []
    def interpretation(item, current_question, answer, revision):
        seen.append(answer)
        return {'resolution': 'partial', 'claims': [], 'resolved_uncertainties': [],
                'remaining_uncertainties': [current_question['uncertainty']]}
    app.state.interpreter.payload = interpretation
    send(client, open_chat(client, cv['id']), text)
    assert seen == [text]
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(q for q in saved['clarifications'] if q['id'] == question['id'])['answer'] == text


def test_revoke_while_routing_prevents_later_evidence_mutation(harness):
    client, app, _, _, transport = harness
    cv, questions = prepare_context(harness, ready(harness))
    question = next(q for q in questions if q['kind'] == 'project')
    entered, release = Event(), Event()
    text = 'I built the Python screens.'
    class BlockingRouter(Router):
        def route(self, context):
            entered.set()
            assert release.wait(5), 'Test did not release the synthetic provider.'
            return super().route(context)
    app.state.conversations.provider = BlockingRouter([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': text}])
    chat = open_chat(client, cv['id'])
    before = client.get('/api/v1/cv/' + cv['id']).json()
    try:
        response = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
            'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'text': text})
        assert response.status_code == 200, response.text
        assert entered.wait(2), 'Synthetic provider did not start.'
        transport.revoked = True
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            saved = app.state.conversations.get('owner-a', chat['id'])
            actions = [a for m in saved['messages'] for a in m['actions']]
            if actions and all(a['status'] != 'pending' for a in actions): break
            time.sleep(.01)
        else: raise AssertionError('Revoked action did not finish safely.')
        assert any(a['status'] == 'failed' for a in actions)
        assert app.state.interpreter.calls == 0
    finally:
        release.set()
        transport.revoked = False
    assert client.get('/api/v1/cv/' + cv['id']).json() == before


def test_busy_provider_capacity_keeps_message_without_starting_provider(harness):
    client, app, *_ = harness
    chat = open_chat(client)
    provider = Router()
    app.state.conversations.provider = provider
    slots = app.state.conversations.slots
    assert slots.acquire(blocking=False)
    assert slots.acquire(blocking=False)
    try:
        value = send(client, chat, 'Please explain the saved information.')
        assert any(m['role'] == 'user' and m['text'] == 'Please explain the saved information.' for m in value['messages'])
        assert any(a['kind'] == 'route' and a['status'] == 'failed' for m in value['messages'] for a in m['actions'])
        assert provider.calls == []
    finally:
        slots.release()
        slots.release()


def configure_http_router(monkeypatch, handler):
    monkeypatch.setenv('CV_LLM_API_KEY', 'synthetic-test-key')
    monkeypatch.setenv('CV_LLM_MODEL', 'synthetic-test-model')
    monkeypatch.setenv('CV_LLM_BASE_URL', 'https://synthetic.invalid/v1')
    original_client = httpx.Client
    monkeypatch.setattr('app.clients.conversation.httpx.Client',
                        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    return ConversationRouter()


@pytest.mark.parametrize('failure', ['oversize', 'truncated', 'invalid_json', 'invalid_action'])
def test_http_router_rejects_unusable_provider_responses(monkeypatch, failure):
    def handler(request):
        assert request.url.host == 'synthetic.invalid'
        if failure == 'oversize': return httpx.Response(200, content=b'x' * (256 * 1024 + 1))
        if failure == 'invalid_json': return httpx.Response(200, content=b'not-json')
        output = {'reply': 'Explanation only.', 'actions': []}
        if failure == 'invalid_action': output['actions'] = [{'kind': 'delete_database'}]
        return httpx.Response(200, json={'choices': [{'finish_reason': 'length' if failure == 'truncated' else 'stop',
            'message': {'content': json.dumps(output)}}]})
    router = configure_http_router(monkeypatch, handler)
    with pytest.raises(ValueError): router.route({'task': 'cv_conversation', 'message': 'Explain this.'})


def test_provider_redirect_is_not_followed(monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(307, headers={'location': 'https://other.invalid/collect'})
    router = configure_http_router(monkeypatch, handler)
    with pytest.raises(ValueError): router.route({'task': 'cv_conversation', 'message': 'Explain this.'})
    assert len(requests) == 1
    assert requests[0].url.host == 'synthetic.invalid'
