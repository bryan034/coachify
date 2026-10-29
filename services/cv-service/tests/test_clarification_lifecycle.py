"""Source generations, distinct answer events and admitted-result capacity."""
from copy import deepcopy
from bson import BSON
import pytest
from app.clarification.service import answer, retry_interpretation
from app.domain.answer_capacity import RESULT_BYTES, RETRY_BYTES, reserved_bytes, snapshot
from app.domain.capabilities import effective_fingerprint
from app.domain.errors import CvError
from app.domain.service import HISTORY_LIMIT_BYTES, OPERATIONAL_ALLOWANCE_BYTES
from app.schemas.cv import AnswerMutation, ItemMutation, Mutation, SavedInterpretation
from tests.conftest import ready, mutation
from tests.test_clarification import prepare_context
from tests.test_interpretation import mixed_output, PERSONAL, project_question
from tests.test_conversation import Router, actions, source_chat
from tests.test_conversation_security import send


def test_corrected_source_archives_old_facts_and_accepts_fresh_questions(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    app.state.interpreter.payload = mixed_output
    answered = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
    changed = client.patch(f"/api/v1/cv/{cv['id']}/items/{question['item_id']}",
        json=mutation(answered['version'], action='update', title='Reviewed project source')).json()
    old = next(q for q in changed['clarifications'] if q['id'] == question['id'])
    assert old['answer'] == PERSONAL and old['reconciliation_required']
    item = next(item for item in changed['items'] if item['id'] == question['item_id'])
    assert all(claim['attribution'] == 'unknown' for claim in item['skill_claims'])
    assert all(claim['experience_months'] is None for claim in item['skill_claims'])
    assert not client.get(f"/api/v1/cv/{cv['id']}/clarifications").json()['prepared']
    prepared, questions = prepare_context(harness, changed)
    current = next(q for q in questions if q['item_id'] == question['item_id'] and not q['reconciliation_required'])
    assert current['id'] != question['id']
    assert client.put(path, json=mutation(prepared['version'], action='answer', answer=PERSONAL)).status_code == 409
    response = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{current['id']}",
        json=mutation(prepared['version'], action='answer', answer=PERSONAL))
    assert response.status_code == 200, response.text
    saved = response.json()
    assert next(s for s in saved['skills'] if s['name'] == 'Python')['experience_months'] == 6
    repeated, _ = prepare_context(harness, saved)
    assert repeated['clarifications'] == saved['clarifications']
    original_title = next(item['title'] for item in repeated['original_items'] if item['id'] == question['item_id'])
    reverted = client.patch(f"/api/v1/cv/{cv['id']}/items/{question['item_id']}",
        json=mutation(repeated['version'], action='update', title=original_title)).json()
    _, questions = prepare_context(harness, reverted)
    next_generation = next(q for q in questions if q['item_id'] == question['item_id'] and not q['reconciliation_required'])
    assert next_generation['id'] not in {question['id'], current['id']}


def test_chat_can_add_new_context_after_a_source_correction(harness):
    client, app, *_ = harness
    cv, original, chat = source_chat(harness)
    router = app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': original['item_id'],
        'question_id': original['id'], 'excerpt': PERSONAL}])
    app.state.interpreter.payload = mixed_output
    chat = send(client, chat, PERSONAL)
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    changed = client.patch(f"/api/v1/cv/{cv['id']}/items/{original['item_id']}",
        json=mutation(saved['version'], action='update', description='A corrected individual Python and SQL project.'))
    assert changed.status_code == 200
    text = 'I cleaned data with pandas.'
    router.actions = [{'kind': 'clarify', 'item_id': original['item_id'], 'excerpt': text}]
    app.state.interpreter.payload = {'resolution': 'resolved', 'claims': [{'skill_id': 'skill:pandas', 'name': 'pandas',
        'attribution': 'personal', 'changed_fields': ['attribution'], 'evidence_excerpt': text}],
        'resolved_uncertainties': ['claim'], 'remaining_uncertainties': []}
    chat = send(client, chat, text)
    assert actions(chat, 'clarify')[-1]['status'] == 'saved'
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(q for q in saved['clarifications'] if q['id'] == original['id'])['reconciliation_required']
    fresh = next(q for q in saved['clarifications'] if q['answer'] == text)
    assert not fresh['reconciliation_required'] and fresh['interpretation_status'] == 'ready'


@pytest.mark.parametrize('duplicate_source_id', [False, True])
def test_reconciliation_keeps_distinct_chat_facts_and_followup_links(harness, duplicate_source_id):
    client, app, *_ = harness
    cv, original, chat = source_chat(harness)
    router = app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': original['item_id'],
        'excerpt': 'I cleaned data with pandas.'}])
    def interpret(item, question, text, revision):
        name = 'pandas' if 'pandas' in text else 'NumPy'
        return {'resolution': 'resolved', 'claims': [{'skill_id': 'skill:' + name.lower(), 'name': name,
            'attribution': 'personal', 'changed_fields': ['attribution'], 'evidence_excerpt': text}],
            'resolved_uncertainties': ['claim'], 'remaining_uncertainties': []}
    app.state.interpreter.payload = interpret
    for text in ['I cleaned data with pandas.', 'I used NumPy independently.']:
        router.actions[0]['excerpt'] = text
        chat = send(client, chat, text)
        assert actions(chat, 'clarify')[-1]['status'] == 'saved'
    source = client.get('/api/v1/cv/' + cv['id']).json()
    old_answers = [q for q in source['clarifications'] if q['answer']]
    assert len(old_answers) == 2 and {q['uncertainty'] for q in old_answers} == {'claim'}
    replacement = ready(harness)
    base = '/api/v1/cv/' + replacement['id']
    compared = client.post(base + '/reconciliation/compare', json=mutation(replacement['version'],
        source_cv_id=source['id'], source_version=source['version'])).json()
    candidate = client.get(base + '/reconciliation').json()
    if duplicate_source_id:
        previous = app.state.service.get('owner-a', replacement['id'])
        corrupted = deepcopy(previous)
        answers = [q for q in corrupted['candidate']['clarifications'] if q.get('answer')]
        answers[1]['id'] = answers[0]['id']
        corrupted['revision'] += 1
        before = app.state.service.repository.replace(previous, corrupted)
    target = next(item for item in replacement['items'] if item['kind'] == 'project')
    body = mutation(compared['version'], candidate_id=candidate['candidate_id'], action='accept_candidate',
        choices=[{'item_id': identifier, 'target_item_id': target['id'] if identifier == original['item_id'] else None}
                 for identifier in candidate['affected_item_ids']])
    response = client.post(base + '/reconciliation', json=body)
    if duplicate_source_id:
        assert response.status_code == 409 and 'ambiguous answer identities' in response.text
        assert app.state.service.get('owner-a', replacement['id']) == before
        return
    assert response.status_code == 200, response.text
    saved = response.json()
    mapped = saved['clarifications']
    assert len(mapped) == len({q['id'] for q in mapped}) == 2
    assert mapped[1]['followup_of'] == mapped[0]['id']
    assert {q['reconciled_from']['question_id'] for q in mapped} == {q['id'] for q in old_answers}
    assert client.post(base + '/reconciliation', json=body).json() == saved
    for question in mapped:
        result = client.post(base + f"/clarifications/{question['id']}/interpretation/retry",
            json=mutation(saved['version']))
        assert result.status_code == 200, result.text
        saved = result.json()
    assert all(q['interpretation_status'] == 'ready' for q in saved['clarifications'])
    assert {'skill:pandas', 'skill:numpy'} <= {s['skill_id'] for s in saved['skills']}
    assert client.get('/api/v1/cv/' + source['id']).json() == source


@pytest.mark.parametrize('state', ['pending', 'failed', 'unanswerable'])
def test_historical_interpretation_states_do_not_block_a_fresh_source(harness, state):
    client, app, *_ = harness
    cv, old, path = project_question(harness)
    if state == 'pending':
        class ProcessExit(BaseException): pass
        class Interrupted:
            def interpret(self, *args): raise ProcessExit()
        with pytest.raises(ProcessExit):
            answer(app.state.service, 'owner-a', cv['id'], old['id'],
                AnswerMutation.model_validate(mutation(cv['version'], action='answer', answer=PERSONAL)), Interrupted())
        saved = client.get('/api/v1/cv/' + cv['id']).json()
    else:
        if state == 'failed': app.state.interpreter.failure = 'Synthetic failure.'
        else:
            app.state.interpreter.payload = {'resolution': 'unanswerable', 'claims': [],
                'resolved_uncertainties': [], 'remaining_uncertainties': ['personal_contribution']}
        result = client.put(path, json=mutation(cv['version'], action='answer', answer='I do not know.'))
        assert result.status_code == 200, result.text
        saved = result.json()
    changed = client.patch(f"/api/v1/cv/{cv['id']}/items/{old['item_id']}",
        json=mutation(saved['version'], action='update', description='Corrected Python and SQL source.')).json()
    assert reserved_bytes(app.state.service.get('owner-a', cv['id'])) == 0
    prepared, questions = prepare_context(harness, changed)
    fresh = next(q for q in questions if q['item_id'] == old['item_id'] and not q['reconciliation_required'])
    assert fresh['id'] != old['id']
    app.state.interpreter.failure, app.state.interpreter.payload = None, mixed_output
    result = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{fresh['id']}",
        json=mutation(prepared['version'], action='answer', answer=PERSONAL))
    assert result.status_code == 200, result.text
    assert next(q for q in result.json()['clarifications'] if q['id'] == fresh['id'])['interpretation_status'] == 'ready'


def test_historical_statements_do_not_affect_fingerprint_or_unrelated_facts(harness):
    client, app, *_ = harness
    cv, questions = prepare_context(harness, ready(harness))
    proficiency = next(q for q in questions if q['uncertainty'] == 'proficiency')
    cv = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{proficiency['id']}",
        json=mutation(cv['version'], action='answer', answer='I can write basic joins independently.')).json()
    project = next(q for q in questions if q['kind'] == 'project')
    def output(*args):
        return {**mixed_output(*args), 'statement_excerpt': PERSONAL}
    app.state.interpreter.payload = output
    cv = client.put(f"/api/v1/cv/{cv['id']}/clarifications/{project['id']}",
        json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
    changed = client.patch(f"/api/v1/cv/{cv['id']}/items/{project['item_id']}",
        json=mutation(cv['version'], action='update', title='Corrected project')).json()
    sql = next(s for s in changed['skills'] if s['skill_id'] == 'skill:sql')
    assert sql['proficiency'] == 'basic joins'
    stored = app.state.service.get('owner-a', cv['id'])
    without_history = deepcopy(stored)
    without_history['clarifications'] = [q for q in stored['clarifications'] if not q['reconciliation_required']]
    assert effective_fingerprint(stored) == effective_fingerprint(without_history)


def pad_to(app, identifier, size):
    previous = app.state.service.get('owner-a', identifier)
    padded = deepcopy(previous)
    padded['revision'] += 1
    padded['synthetic_capacity_padding'] = ''
    padded['synthetic_capacity_padding'] = 'x' * (size - len(BSON.encode(padded)))
    assert len(BSON.encode(padded)) == size
    return app.state.repository.replace(previous, padded)


@pytest.mark.parametrize('operation', ['answer', 'retry'])
def test_capacity_rejects_before_accepting_a_pending_answer_or_retry(harness, operation):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    if operation == 'retry':
        app.state.interpreter.failure = 'Synthetic failure.'
        cv = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
        app.state.interpreter.failure = None
    before = pad_to(app, cv['id'], HISTORY_LIMIT_BYTES - 2048)
    calls = app.state.interpreter.calls
    if operation == 'answer':
        response = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL))
    else:
        response = client.post(path + '/interpretation/retry', json=mutation(cv['version']))
    assert response.status_code == 409 and 'history limit' in response.text
    assert app.state.interpreter.calls == calls
    assert app.state.service.get('owner-a', cv['id']) == before


def test_concurrent_edit_cannot_spend_an_accepted_answers_reserved_space(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    document = app.state.service.get('owner-a', cv['id'])
    pad_to(app, cv['id'], HISTORY_LIMIT_BYTES - RESULT_BYTES - RETRY_BYTES
           - 2 * len(BSON.encode(snapshot(document))) - 20 * 1024)
    rejected = []
    def edit_other_item():
        pending = app.state.service.get('owner-a', cv['id'])
        assert reserved_bytes(pending) > RESULT_BYTES
        other = next(item for item in pending['original_items'] if item['id'] != question['item_id'])
        with pytest.raises(CvError, match='history limit'):
            app.state.service.edit('owner-a', cv['id'], other['id'], ItemMutation.model_validate(
                mutation(pending['version'], action='update', description='🧪' * 4000)))
        rejected.append(True)
    app.state.interpreter.before_return, app.state.interpreter.payload = edit_other_item, mixed_output
    response = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL))
    assert response.status_code == 200, response.text
    assert rejected == [True]
    saved = app.state.service.get('owner-a', cv['id'])
    assert reserved_bytes(saved) == 0
    assert next(q for q in saved['clarifications'] if q['id'] == question['id'])['interpretation_status'] == 'ready'


@pytest.mark.parametrize('remaining', [RETRY_BYTES, 0])
def test_interrupted_answer_retries_at_reserved_limit_without_copying_claim_history(harness, monkeypatch, remaining):
    client, app, *_ = harness
    cv, question, _ = project_question(harness)
    class ProcessExit(BaseException): pass
    class Interrupted:
        def interpret(self, *args): raise ProcessExit()
    with pytest.raises(ProcessExit):
        answer(app.state.service, 'owner-a', cv['id'], question['id'],
            AnswerMutation.model_validate(mutation(cv['version'], action='answer', answer=PERSONAL)), Interrupted())
    pending = app.state.service.get('owner-a', cv['id'])
    assert '_capacity_' not in client.get('/api/v1/cv/' + cv['id']).text
    changed = deepcopy(pending)
    next(q for q in changed['clarifications'] if q['id'] == question['id'])['_capacity_retry_bytes'] = remaining
    changed['revision'] += 1
    pending = app.state.service.repository.replace(pending, changed)
    pending = pad_to(app, cv['id'], HISTORY_LIMIT_BYTES - reserved_bytes(pending))
    old_history = deepcopy(pending['history'])
    old_question = next(q for q in pending['clarifications'] if q['id'] == question['id'])
    monkeypatch.setattr('app.clarification.service.now', lambda: old_question['interpretation_lease_until'] + 1)
    app.state.interpreter.payload = mixed_output
    request = Mutation.model_validate(mutation(pending['version']))
    result = retry_interpretation(app.state.service, 'owner-a', cv['id'], question['id'], request, app.state.interpreter)
    assert next(q for q in result['clarifications'] if q['id'] == question['id'])['answer'] == PERSONAL
    assert next(q for q in result['clarifications'] if q['id'] == question['id'])['interpretation_status'] == ('ready' if remaining else 'failed')
    if not remaining:
        assert 'history limit' in next(q for q in result['clarifications'] if q['id'] == question['id'])['interpretation_error']
    assert result['history'][:-1] == old_history
    assert result['history'][-1]['operation'] == 'interpret:' + question['id']
    assert reserved_bytes(result) == 0 and len(BSON.encode(result)) <= HISTORY_LIMIT_BYTES
    assert retry_interpretation(app.state.service, 'owner-a', cv['id'], question['id'], request, app.state.interpreter) == result


def test_result_reservation_covers_schema_utf8_maximum_and_worker_allowance():
    maximal = SavedInterpretation.model_validate({'item_id': '🧪' * 100, 'answer_revision': 2 ** 53,
        'resolution': 'partial', 'claims': [{'skill_id': '🧪' * 3998 + f'{i:02}', 'name': '🧪' * 200,
            'attribution': 'personal', 'assistance': 'supervised', 'proficiency': '🧪' * 120,
            'experience_months': 1200.0, 'evidence_excerpt': '🧪' * 500,
            'changed_fields': ['attribution', 'assistance', 'proficiency', 'experience_months']} for i in range(20)],
        'dates': {'start_date': '0001-01-01', 'end_date': '9999-12-31', 'ongoing': False,
            'changed_fields': ['start_date', 'end_date', 'ongoing'], 'evidence_excerpt': '🧪' * 500},
        'statement_excerpt': '🧪' * 500, 'resolved_uncertainties': [],
        'remaining_uncertainties': ['personal_contribution', 'responsibility', 'proficiency', 'duration', 'claim', 'qualification', 'date'],
        'summary': '🧪' * 2000, 'metadata': {'provider': '🧪' * 255, 'model': '🧪' * 200,
            'prompt_version': '🧪' * 100, 'schema_version': '🧪' * 30},
        'applied_sequence': 2 ** 53, 'extraction_version': 2 ** 53}).model_dump()
    assert len(BSON.encode(maximal)) + OPERATIONAL_ALLOWANCE_BYTES + 16 * 1024 < RESULT_BYTES
