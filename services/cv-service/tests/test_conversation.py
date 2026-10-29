"""Conversation lifecycle tests: real persistence and explicit synthetic providers."""
from copy import deepcopy
import time
from threading import Event
from uuid import uuid4
import httpx
import pytest
from app.conversation.service import MAX_MESSAGES, key, now
from tests.conftest import ready, mutation
from tests.test_clarification import prepare_context
from tests.test_interpretation import mixed_output, PERSONAL
from tests.test_conversation_security import open_chat, settled, send, PREFIX


class Router:
    def __init__(self, actions=None):
        self.actions, self.calls, self.failure, self.callback = actions or [], [], None, None

    def route(self, context):
        self.calls.append(deepcopy(context))
        if self.callback: self.callback()
        if self.failure: raise ValueError(self.failure)
        actions = self.actions(context) if callable(self.actions) else deepcopy(self.actions)
        return {'reply': 'Here is what your message refers to.', 'actions': actions}, {
            'provider': 'synthetic-test', 'model': 'fixture', 'prompt_version': '1', 'schema_version': '1'}


def actions(chat, kind): return [a for m in chat['messages'] for a in m['actions'] if a['kind'] == kind]


def decide(client, chat, action, decision='save', **fields):
    response = client.post(PREFIX + '/' + chat['id'] + '/actions/' + action['id'], json={
        'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'decision': decision, **fields})
    assert response.status_code == 200, response.text
    return settled(client, chat['id'])


def source_chat(harness):
    client, app, *_ = harness
    cv, questions = prepare_context(harness, ready(harness))
    question = next(q for q in questions if q['kind'] == 'project')
    chat = open_chat(client, cv['id'])
    app.state.conversations.provider = Router()
    return cv, question, chat


def test_resumes_same_conversation_and_paginates_without_duplicate_history(harness):
    client, app, *_ = harness
    chat = open_chat(client)
    app.state.conversations.provider = Router()
    for number in range(4): chat = send(client, chat, 'A read-only question ' + str(number))
    resumed = open_chat(client)
    assert resumed['id'] == chat['id']
    assert resumed['messages'] == chat['messages']
    page = client.get(PREFIX + '/' + chat['id'], params={'limit': 3}).json()
    older = client.get(PREFIX + '/' + chat['id'], params={'limit': 3, 'before': page['next_before']}).json()
    assert len(page['messages']) == len(older['messages']) == 3
    assert max(m['sequence'] for m in older['messages']) < min(m['sequence'] for m in page['messages'])
    assert len(client.get(PREFIX).json()['conversations']) == 1


def test_same_message_key_is_idempotent_and_reuse_with_new_text_conflicts(harness):
    client, app, *_ = harness
    chat = open_chat(client)
    router = app.state.conversations.provider = Router()
    body = {'text': 'Why?', 'mutation_id': str(uuid4()), 'expected_revision': chat['revision']}
    assert client.post(PREFIX + '/' + chat['id'] + '/messages', json=body).status_code == 200
    saved = settled(client, chat['id'])
    assert client.post(PREFIX + '/' + chat['id'] + '/messages', json=body).json()['revision'] == saved['revision']
    assert len(router.calls) == 1
    assert client.post(PREFIX + '/' + chat['id'] + '/messages', json={**body, 'text': 'Different'}).status_code == 409


def test_question_interruption_resume_and_skip_retain_unknown(harness):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    chat = send(client, chat, 'Review my CV', command='review')
    assert chat['active_question']['id'] == question['id']
    before = client.get('/api/v1/cv/' + cv['id']).json()
    chat = send(client, chat, 'Why are you asking?')
    assert chat['active_question']['id'] == question['id']
    assert client.get('/api/v1/cv/' + cv['id']).json()['effective_version'] == before['effective_version']
    chat = send(client, chat, 'Skip', command='skip')
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(q for q in result['clarifications'] if q['id'] == question['id'])['status'] == 'skipped'
    assert result['effective_version'] == before['effective_version']
    assert not chat['active_question'] or chat['active_question']['id'] != question['id']


def test_appended_context_and_confirmed_correction_preserve_earlier_facts_over_4000_chars(harness):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    first = (PERSONAL + ' ' + ('Context. ' * 200)).rstrip()
    router = app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': PERSONAL}])
    app.state.interpreter.payload = mixed_output
    chat = send(client, chat, first)
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'
    second = ('I cleaned data with pandas. ' + ('Extra context. ' * 200)).rstrip()
    router.actions = [{'kind': 'clarify', 'item_id': question['item_id'], 'excerpt': 'I cleaned data with pandas.'}]
    app.state.interpreter.payload = {'resolution': 'resolved', 'claims': [{'skill_id': 'skill:pandas', 'name': 'pandas',
        'attribution': 'personal', 'changed_fields': ['attribution'], 'evidence_excerpt': 'I cleaned data with pandas.'}],
        'resolved_uncertainties': ['claim'], 'remaining_uncertainties': []}
    chat = send(client, chat, second)
    assert len(first) + len(second) > 4000
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'
    before = client.get('/api/v1/cv/' + cv['id']).json()
    python = next(s for s in before['skills'] if s['name'] == 'Python')
    assert python['experience_months'] == 6 and python['sources'][0]['assistance'] == 'supervised'
    assert any(s['name'] == 'pandas' for s in before['skills'])
    correction = 'Actually, I used Python for three months, not six.'
    router.actions = [{'kind': 'correct', 'item_id': question['item_id'], 'excerpt': correction}]
    app.state.interpreter.payload = {'resolution': 'resolved', 'claims': [{'skill_id': 'skill:python', 'name': 'Python',
        'attribution': 'unknown', 'experience_months': 3, 'changed_fields': ['experience_months'], 'evidence_excerpt': correction}],
        'resolved_uncertainties': ['claim'], 'remaining_uncertainties': []}
    chat = send(client, chat, correction)
    proposal = actions(chat, 'correct')[-1]
    assert proposal['status'] == 'awaiting_confirmation'
    assert client.get('/api/v1/cv/' + cv['id']).json()['version'] == before['version']
    chat = decide(client, chat, proposal)
    assert actions(chat, 'correct')[-1]['status'] == 'saved'
    result = client.get('/api/v1/cv/' + cv['id']).json()
    python = next(s for s in result['skills'] if s['name'] == 'Python')
    assert python['experience_months'] == 3
    assert python['sources'][0]['attribution'] == 'personal'
    assert python['sources'][0]['assistance'] == 'supervised'
    assert any(q['answer'] == first for q in result['clarifications'])
    assert any(q['answer'] == second for q in result['clarifications'])
    assert any(q['answer'] == correction for q in result['clarifications'])


def test_routing_excerpt_cannot_strip_negation_from_interpreter_input(harness):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    text = 'I did not use SQL. I built the Python screens.'
    app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': 'use SQL'}])
    seen = []
    def interpret(item, q, answer_text, revision):
        seen.append(answer_text)
        return {'resolution': 'resolved', 'claims': [
            {'skill_id': 'skill:python', 'name': 'Python', 'attribution': 'personal',
             'changed_fields': ['attribution'], 'evidence_excerpt': 'I built the Python screens.'},
            {'skill_id': 'skill:sql', 'name': 'SQL', 'attribution': 'denied',
             'changed_fields': ['attribution'], 'evidence_excerpt': 'I did not use SQL.'}],
            'resolved_uncertainties': [q['uncertainty']], 'remaining_uncertainties': []}
    app.state.interpreter.payload = interpret
    chat = send(client, chat, text)
    assert seen == [text]
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert question['item_id'] not in next(s for s in result['skills'] if s['name'] == 'SQL')['item_ids']


def test_cancelled_correction_and_stale_action_do_not_change_evidence(harness):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    text = 'Rename the project to Shopping App.'
    app.state.conversations.provider = Router([{'kind': 'correct', 'item_id': question['item_id'],
        'excerpt': text, 'fields': {'title': 'Shopping App'}}])
    chat = send(client, chat, text)
    before = client.get('/api/v1/cv/' + cv['id']).json()
    chat = decide(client, chat, actions(chat, 'correct')[-1], 'cancel')
    assert client.get('/api/v1/cv/' + cv['id']).json()['version'] == before['version']
    chat = send(client, chat, text)
    client.patch('/api/v1/cv/' + cv['id'] + '/items/' + question['item_id'],
        json=mutation(before['version'], action='update', title='A newer edit'))
    chat = decide(client, chat, actions(chat, 'correct')[-1])
    assert actions(chat, 'correct')[-1]['status'] == 'stale'
    assert next(i for i in client.get('/api/v1/cv/' + cv['id']).json()['items'] if i['id'] == question['item_id'])['title'] == 'A newer edit'


def test_ambiguous_source_requires_choice_before_applying(harness):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    item_ids = [i['id'] for i in cv['items']]
    app.state.conversations.provider = Router([{'kind': 'clarify', 'excerpt': PERSONAL, 'candidate_item_ids': item_ids}])
    app.state.interpreter.payload = mixed_output
    chat = send(client, chat, PERSONAL)
    proposal = actions(chat, 'clarify')[-1]
    assert proposal['status'] == 'needs_source'
    assert client.get('/api/v1/cv/' + cv['id']).json()['version'] == cv['version']
    chat = decide(client, chat, proposal, item_id=question['item_id'])
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'


def test_failed_router_and_expired_lease_retry_original_message(harness):
    client, app, *_ = harness
    chat = open_chat(client)
    router = app.state.conversations.provider = Router()
    router.failure = 'Synthetic router unavailable.'
    chat = send(client, chat, 'Why?')
    assert actions(chat, 'route')[-1]['status'] == 'failed'
    router.failure = None
    chat = decide(client, chat, actions(chat, 'route')[-1], 'retry')
    assert actions(chat, 'route')[-1]['status'] == 'saved'
    assert len([m for m in chat['messages'] if m['role'] == 'user']) == 1
    repository = app.state.repository.conversations
    previous = repository.get('owner-a', chat['id'])
    modified = deepcopy(previous)
    action = modified['messages'][-1]['actions'][0]
    action.update(status='pending', _token='interrupted', _lease_until=now() - 1)
    modified['revision'] += 1
    repository.replace(previous, modified)
    chat = client.get(PREFIX + '/' + chat['id']).json()
    assert actions(chat, 'route')[-1]['status'] == 'failed'
    chat = decide(client, chat, actions(chat, 'route')[-1], 'retry')
    assert actions(chat, 'route')[-1]['status'] == 'saved'


def test_failed_interpretation_retry_keeps_one_saved_answer(harness):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': PERSONAL}])
    app.state.interpreter.failure = 'Synthetic interpretation outage.'
    chat = send(client, chat, PERSONAL)
    failed = actions(chat, 'clarify')[-1]
    assert failed['status'] == 'failed'
    app.state.interpreter.failure = None
    app.state.interpreter.payload = mixed_output
    chat = decide(client, chat, failed, 'retry')
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert len([q for q in result['clarifications'] if q['answer'] == PERSONAL]) == 1


def test_context_switch_on_resume_clears_old_question_without_losing_history(harness):
    client, app, _, targets, _ = harness
    cv, question, chat = source_chat(harness)
    chat = send(client, chat, 'Review', command='review')
    assert chat['active_question']
    saved_messages = deepcopy(chat['messages'])
    targets.context_value = {**targets.context_value, 'id': 'another-target', 'version': 2,
                             'selection_version': 2, 'skill_ids': ['skill:rust']}
    resumed = open_chat(client, cv['id'])
    assert resumed['context']['id'] == 'another-target'
    assert resumed['active_question'] is None
    assert resumed['messages'] == saved_messages


@pytest.mark.parametrize('byte_capacity', [False, True])
def test_capacity_rollover_retains_discoverable_old_history(harness, byte_capacity):
    client, app, *_ = harness
    chat = open_chat(client)
    repository = app.state.repository.conversations
    previous = repository.get('owner-a', chat['id'])
    full = deepcopy(previous)
    if byte_capacity: full['synthetic_capacity_padding'] = 'x' * (6 * 1024 * 1024)
    else:
        full['messages'] = [{**deepcopy(full['messages'][0]), 'id': str(uuid4()), 'sequence': n + 1}
                            for n in range(MAX_MESSAGES - 1)]
    full['revision'] += 1
    repository.replace(previous, full)
    assert client.get(PREFIX + '/' + chat['id']).json()['read_only'] is True
    resumed = open_chat(client)
    assert resumed['id'] != chat['id']
    assert resumed['previous_conversation_id'] == chat['id']
    assert {c['id'] for c in client.get(PREFIX).json()['conversations']} == {chat['id'], resumed['id']}


def test_revocation_during_provider_work_saves_message_but_no_facts(harness):
    client, app, _, _, transport = harness
    cv, question, chat = source_chat(harness)
    router = app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': PERSONAL}])
    router.callback = lambda: setattr(transport, 'revoked', True)
    response = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
        'text': PERSONAL, 'expected_revision': chat['revision'], 'mutation_id': str(uuid4())})
    assert response.status_code == 200
    deadline = time.monotonic() + 5
    while app.state.conversations.tasks and time.monotonic() < deadline: time.sleep(.01)
    transport.revoked = False
    result = settled(client, chat['id'])
    assert any(a['status'] == 'failed' for m in result['messages'] for a in m['actions'])
    assert client.get('/api/v1/cv/' + cv['id']).json()['version'] == cv['version']


def test_multiple_sources_apply_only_once_and_report_each_outcome(harness):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    other = next(i for i in cv['items'] if i['kind'] == 'skill')
    app.state.conversations.provider = Router([
        {'kind': 'correct', 'item_id': question['item_id'], 'excerpt': 'Rename the project.', 'fields': {'title': 'Shopping App'}},
        {'kind': 'correct', 'item_id': other['id'], 'excerpt': 'Rename SQL.', 'fields': {'title': 'SQL basics'}}])
    chat = send(client, chat, 'Rename the project. Rename SQL.')
    first, second = actions(chat, 'correct')
    chat = decide(client, chat, first)
    chat = decide(client, chat, next(a for a in actions(chat, 'correct') if a['id'] == second['id']))
    assert [a['status'] for a in actions(chat, 'correct')] == ['saved', 'saved']
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert {'Shopping App', 'SQL basics'} <= {i['title'] for i in result['items']}


def test_revocation_during_interpretation_preserves_answer_without_applying_claims(harness):
    client, app, _, _, transport = harness
    cv, question, chat = source_chat(harness)
    app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': PERSONAL}])
    app.state.interpreter.payload = mixed_output
    app.state.interpreter.before_return = lambda: setattr(transport, 'revoked', True)
    response = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
        'text': PERSONAL, 'expected_revision': chat['revision'], 'mutation_id': str(uuid4())})
    assert response.status_code == 200
    deadline = time.monotonic() + 5
    while app.state.conversations.tasks and time.monotonic() < deadline: time.sleep(.01)
    transport.revoked = False
    result = client.get('/api/v1/cv/' + cv['id']).json()
    saved = next(q for q in result['clarifications'] if q['id'] == question['id'])
    assert saved['answer'] == PERSONAL and saved['interpretation_status'] == 'failed'
    assert result['effective_version'] == cv['effective_version']
    app.state.interpreter.before_return = None
    chat = settled(client, chat['id'])
    chat = decide(client, chat, actions(chat, 'clarify')[-1], 'retry')
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'


def test_side_question_while_interpreting_does_not_invalidate_facts(harness):
    client, app, *_ = harness
    from dataclasses import replace
    # Preserve this concurrent transcript/evidence-fencing scenario with two
    # synthetic owner slots; default one-slot fairness is tested separately.
    app.state.service.model_usage.settings = replace(app.state.settings, model_concurrent_per_owner=2)
    cv, question, chat = source_chat(harness)
    started, release = Event(), Event()
    app.state.conversations.provider = Router(lambda context: ([{'kind': 'clarify',
        'item_id': question['item_id'], 'question_id': question['id'], 'excerpt': PERSONAL}]
        if context['message'] == PERSONAL else []))
    def wait():
        started.set()
        assert release.wait(5), 'Synthetic interpreter was not released.'
    app.state.interpreter.before_return = wait
    app.state.interpreter.payload = mixed_output
    response = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
        'text': PERSONAL, 'expected_revision': chat['revision'], 'mutation_id': str(uuid4())})
    assert response.status_code == 200 and started.wait(3)
    current = client.get(PREFIX + '/' + chat['id']).json()
    side = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
        'text': 'Why are you asking?', 'expected_revision': current['revision'], 'mutation_id': str(uuid4())})
    assert side.status_code == 200
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        latest = client.get(PREFIX + '/' + chat['id']).json()
        if actions(latest, 'route')[-1]['status'] == 'saved': break
        time.sleep(.01)
    assert actions(latest, 'route')[-1]['status'] == 'saved'
    release.set()
    chat = settled(client, chat['id'])
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(s for s in result['skills'] if s['name'] == 'Python')['experience_months'] == 6


def test_recovers_crash_after_question_creation_before_answer(harness, monkeypatch):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    app.state.conversations.provider = Router([{'kind': 'correct', 'item_id': question['item_id'], 'excerpt': PERSONAL}])
    app.state.interpreter.payload = mixed_output
    chat = send(client, chat, PERSONAL)
    original = app.state.service.mutate
    interrupted = False
    def mutation_then_crash(owner, identifier, mutation, operation, transform):
        nonlocal interrupted
        result = original(owner, identifier, mutation, operation, transform)
        if operation.startswith('chat-question:') and not interrupted:
            interrupted = True
            raise RuntimeError('Synthetic process interruption after durable question creation')
        return result
    monkeypatch.setattr(app.state.service, 'mutate', mutation_then_crash)
    chat = decide(client, chat, actions(chat, 'correct')[-1])
    assert actions(chat, 'correct')[-1]['status'] == 'failed'
    before = client.get('/api/v1/cv/' + cv['id']).json()
    created = [q for q in before['clarifications'] if q['followup_of'] == question['id']]
    assert len(created) == 1 and created[0]['status'] == 'unanswered'
    chat = decide(client, chat, actions(chat, 'correct')[-1], 'retry')
    assert actions(chat, 'correct')[-1]['status'] == 'saved'
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert len([q for q in result['clarifications'] if q['followup_of'] == question['id']]) == 1


def test_recovers_lost_answer_receipt_without_duplicate_interpretation(harness, monkeypatch):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': PERSONAL}])
    app.state.interpreter.payload = mixed_output
    import app.conversation.service as service_module
    actual_answer = service_module.answer
    interrupted = False
    def save_then_crash(*args, **kwargs):
        nonlocal interrupted
        result = actual_answer(*args, **kwargs)
        if not interrupted:
            interrupted = True
            raise RuntimeError('Synthetic lost return after completed interpretation')
        return result
    monkeypatch.setattr(service_module, 'answer', save_then_crash)
    chat = send(client, chat, PERSONAL)
    assert actions(chat, 'clarify')[-1]['status'] == 'failed'
    before = client.get('/api/v1/cv/' + cv['id']).json()
    calls = app.state.interpreter.calls
    chat = decide(client, chat, actions(chat, 'clarify')[-1], 'retry')
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'
    assert app.state.interpreter.calls == calls
    assert client.get('/api/v1/cv/' + cv['id']).json()['version'] == before['version']


def test_late_failure_cannot_overwrite_successful_action_receipt(harness):
    client, app, *_ = harness
    chat = open_chat(client)
    app.state.conversations.provider = Router()
    chat = send(client, chat, 'Why?')
    action = actions(chat, 'route')[-1]
    # Execute through TestClient's event loop, matching a delayed worker callback.
    client.portal.call(app.state.conversations.fail, 'owner-a', chat['id'], action['id'], None, 'Late failure', 'stale')
    after = client.get(PREFIX + '/' + chat['id']).json()
    assert actions(after, 'route')[-1]['status'] == 'saved'
    assert after['revision'] == chat['revision']


def test_manual_only_save_duplicate_choice_and_lost_response_recovery(harness):
    client, app, _, _, transport = harness
    declarations, receipts = [], {}
    state = {'version': 0, 'lost': True, 'writes': 0}
    async def profile(request):
        if request.url.path.endswith('/capabilities'):
            if request.method == 'POST':
                import json
                body = json.loads(request.content)
                if body['mutation_id'] not in receipts:
                    assert body['expected_version'] == state['version']
                    state['writes'] += 1
                    state['version'] += 1
                    declarations.append({'id': 'saved-manual-' + str(state['version']), 'name': body['name'], 'description': body['description']})
                    receipts[body['mutation_id']] = deepcopy(body)
                    if state['lost']:
                        state['lost'] = False
                        raise httpx.ReadError('Synthetic response lost after save')
                else: assert body == receipts[body['mutation_id']]
            return httpx.Response(200, json={'version': state['version'], 'declarations': declarations})
        return await transport(request)
    replacement = httpx.AsyncClient(transport=httpx.MockTransport(profile), base_url='http://profile')
    original = app.state.profile_client
    app.state.profile_client = replacement
    try:
        chat = open_chat(client)
        text = 'I use Figma to make posters for my student society.'
        app.state.conversations.provider = Router([{'kind': 'add_capability', 'name': 'Figma', 'excerpt': text}])
        chat = send(client, chat, text)
        assert not declarations
        chat = decide(client, chat, actions(chat, 'add_capability')[-1])
        assert actions(chat, 'add_capability')[-1]['status'] == 'failed'
        chat = decide(client, chat, actions(chat, 'add_capability')[-1], 'retry')
        assert actions(chat, 'add_capability')[-1]['status'] == 'saved'
        assert state['writes'] == 1
        assert app.state.repository.list('owner-a') == []
        chat = send(client, chat, text)
        chat = decide(client, chat, actions(chat, 'add_capability')[-1])
        match = actions(chat, 'add_capability')[-1]
        assert match['status'] == 'awaiting_confirmation' and match['choices'][0]['kind'] == 'declaration'
        chat = decide(client, chat, match, mode='distinct')
        assert actions(chat, 'add_capability')[-1]['status'] == 'saved'
        assert state['writes'] == 2
    finally:
        app.state.profile_client = original
        client.portal.call(replacement.aclose)


def test_cv_history_capacity_keeps_message_and_original_evidence(harness):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    repository = app.state.repository
    previous = repository.get('owner-a', cv['id'])
    padded = deepcopy(previous)
    padded['synthetic_capacity_padding'] = 'x' * (12 * 1024 * 1024 - 256 * 1024)
    padded['revision'] += 1
    repository.replace(previous, padded)
    app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': PERSONAL}])
    chat = send(client, chat, PERSONAL)
    action = actions(chat, 'clarify')[-1]
    assert action['status'] == 'failed' and 'history limit' in action['error']
    assert any(m['text'] == PERSONAL for m in chat['messages'])
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert result['version'] == cv['version'] and result['skills'] == cv['skills']


def test_lost_remove_receipt_recovers_after_item_is_already_removed(harness, monkeypatch):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    text = 'Remove Project A.'
    app.state.conversations.provider = Router([{'kind': 'remove', 'item_id': question['item_id'], 'excerpt': text}])
    chat = send(client, chat, text)
    real_edit = app.state.service.edit
    interrupted = False
    def remove_then_crash(*args, **kwargs):
        nonlocal interrupted
        result = real_edit(*args, **kwargs)
        if not interrupted:
            interrupted = True
            raise RuntimeError('Synthetic interruption after durable removal')
        return result
    monkeypatch.setattr(app.state.service, 'edit', remove_then_crash)
    chat = decide(client, chat, actions(chat, 'remove')[-1])
    assert actions(chat, 'remove')[-1]['status'] == 'failed'
    before = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(i for i in before['items'] if i['id'] == question['item_id'])['removed']
    chat = decide(client, chat, actions(chat, 'remove')[-1], 'retry')
    assert actions(chat, 'remove')[-1]['status'] == 'saved'
    assert client.get('/api/v1/cv/' + cv['id']).json()['version'] == before['version']


@pytest.mark.parametrize('guided', [False, True], ids=['routed', 'guided'])
def test_lost_skip_receipt_replays_original_question_after_resume(harness, monkeypatch, guided):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    chat = send(client, chat, 'Review my CV', command='review')
    original_question = chat['active_question']['id']
    assert original_question == question['id']
    app.state.conversations.provider = Router([{'kind': 'skip', 'item_id': question['item_id'], 'excerpt': 'Skip'}])
    import app.conversation.service as service_module
    actual_answer, attempts = service_module.answer, []
    def skip_then_crash(service, owner, identifier, question_id, body, *args):
        result = actual_answer(service, owner, identifier, question_id, body, *args)
        if body.action == 'skip':
            attempts.append((question_id, body.model_dump(mode='json')))
            if len(attempts) == 1:
                raise RuntimeError('Synthetic lost response after durable skip')
        return result
    monkeypatch.setattr(service_module, 'answer', skip_then_crash)
    chat = send(client, chat, 'Skip', **({'command': 'skip'} if guided else {}))
    failed = actions(chat, 'route' if guided else 'skip')[-1]
    assert failed['status'] == 'failed'
    # Resuming clears the answered active topic. A later review can show another
    # topic; retry must remain bound to the original skip, not the new prompt.
    chat = open_chat(client, cv['id'])
    assert chat['active_question'] is None
    chat = send(client, chat, 'Continue reviewing', command='continue')
    next_question = (chat['active_question'] or {}).get('id')
    assert next_question and next_question != original_question
    before = client.get('/api/v1/cv/' + cv['id']).json()
    chat = decide(client, chat, failed, 'retry')
    recovered = next(a for a in actions(chat, failed['kind']) if a['id'] == failed['id'])
    assert recovered['status'] == 'saved'
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(q for q in result['clarifications'] if q['id'] == next_question)['status'] == 'unanswered'
    assert [q['id'] for q in result['clarifications'] if q['status'] == 'skipped'] == [original_question]
    assert result['effective_version'] == before['effective_version']
    assert result['version'] == before['version']


@pytest.mark.parametrize('command', ['review', 'skip'])
def test_lost_guided_prepare_response_replays_exact_operation(harness, monkeypatch, command):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    if command == 'skip': chat = send(client, chat, 'Review my CV', command='review')
    import app.conversation.service as service_module
    actual_prepare, attempts = service_module.prepare, []
    def prepare_then_crash(service, owner, identifier, body, context):
        result = actual_prepare(service, owner, identifier, body, context)
        attempts.append(body.model_dump(mode='json'))
        if len(attempts) == 1:
            raise RuntimeError('Synthetic lost response after durable question preparation')
        return result
    monkeypatch.setattr(service_module, 'prepare', prepare_then_crash)
    chat = send(client, chat, command, command=command)
    failed = actions(chat, 'route')[-1]
    assert failed['status'] == 'failed'
    chat = open_chat(client, cv['id'])
    before = client.get('/api/v1/cv/' + cv['id']).json()
    chat = decide(client, chat, failed, 'retry')
    assert actions(chat, 'route')[-1]['status'] == 'saved'
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert result['version'] == before['version']
    assert result['clarifications'] == before['clarifications']
    if command == 'skip': assert chat['active_question']['id'] != question['id']


def test_guided_recovery_retains_original_confirmed_target_binding(harness, monkeypatch):
    client, app, _, targets, _ = harness
    cv, _, chat = source_chat(harness)
    import app.conversation.service as service_module
    actual_prepare = service_module.prepare
    def prepare_then_crash(*args):
        actual_prepare(*args)
        raise RuntimeError('Synthetic lost response after durable preparation')
    monkeypatch.setattr(service_module, 'prepare', prepare_then_crash)
    chat = send(client, chat, 'Review', command='review')
    failed = actions(chat, 'route')[-1]
    assert failed['status'] == 'failed'
    before = client.get('/api/v1/cv/' + cv['id']).json()
    targets.context_value = {**targets.context_value, 'id': 'another-target', 'version': 2,
                             'selection_version': 2, 'skill_ids': ['skill:rust']}
    chat = open_chat(client, cv['id'])
    chat = decide(client, chat, failed, 'retry')
    assert actions(chat, 'route')[-1]['status'] == 'stale'
    result = client.get('/api/v1/cv/' + cv['id']).json()
    assert result['version'] == before['version']
    assert result['clarifications'] == before['clarifications']


def test_history_listing_projects_metadata_without_loading_old_transcripts(harness, monkeypatch):
    client, app, *_ = harness
    chat = open_chat(client)
    repository = app.state.repository.conversations
    def no_full_list(*args): raise AssertionError('Do not load all full transcripts for opening or listing.')
    monkeypatch.setattr(repository, 'list', no_full_list)
    assert open_chat(client)['id'] == chat['id']
    result = client.get(PREFIX)
    assert result.status_code == 200
    assert result.json()['conversations'][0]['message_count'] == 1
    summary = repository.summaries('owner-a', None)[0]
    assert 'messages' not in summary and 'receipts' not in summary


def test_action_choices_accept_all_valid_cv_and_declaration_matches():
    from app.schemas.conversation import ChatAction
    from pydantic import ValidationError
    choices = [{'id': str(i), 'label': 'Skill', 'description': 'Retained matching evidence',
                'kind': 'item' if i < 160 else 'declaration'} for i in range(260)]
    action = {'id': str(uuid4()), 'kind': 'add_capability', 'status': 'awaiting_confirmation',
              'title': 'Choose evidence', 'summary': 'Attach or keep distinct', 'choices': choices}
    assert len(ChatAction.model_validate(action).choices) == 260
    with pytest.raises(ValidationError): ChatAction.model_validate({**action, 'choices': choices + [choices[0]]})


def test_correction_card_uses_authoritative_before_value_not_routing_summary(harness):
    client, app, *_ = harness
    cv, question, chat = source_chat(harness)
    changed = client.patch('/api/v1/cv/' + cv['id'] + '/items/' + question['item_id'],
        json=mutation(cv['version'], action='update', start_date='2025-01'))
    assert changed.status_code == 200
    text = 'The start date was February 2025.'
    app.state.conversations.provider = Router([{'kind': 'correct', 'item_id': question['item_id'],
        'excerpt': text, 'fields': {'start_date': '2025-02'}}])
    chat = send(client, chat, text)
    change = actions(chat, 'correct')[-1]['changes'][0]
    assert change == {'field': 'start date', 'before': '2025-01', 'after': '2025-02'}
