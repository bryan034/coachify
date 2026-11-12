"""Harness decisions and durable evidence use synthetic providers on both repositories."""
from copy import deepcopy
from uuid import uuid4
import pytest
from app.conversation.interview import build_context, reconcile_memory, validate_decision
from app.domain.capabilities import effective_items, validate_extraction, evidence_requiring_semantic_check
from app.schemas.interview import InterviewTurn
from tests.conftest import ready, mutation
from tests.test_conversation_security import PREFIX, send, settled
from tests.interview_fixture import InterviewProvider


def opened(harness):
    client, app, *_ = harness
    cv = ready(harness)
    provider = app.state.conversations.provider = InterviewProvider()
    app.state.interpreter.verify_evidence = provider.verify_evidence
    response = client.post(PREFIX, json={'cv_id': cv['id'], 'purpose': 'skills_profile', 'mutation_id': str(uuid4())})
    assert response.status_code == 200, response.text
    return cv, response.json(), provider


def start(harness):
    cv, chat, provider = opened(harness)
    chat = send(harness[0], chat, 'Review my CV', command='review')
    assert chat['active_question'], [(a['kind'], a.get('error')) for a in chat['messages'][-1]['actions']]
    return cv, chat, provider


def fact(field, quote, value=None, status='supported', skill_name=None, attribution=None):
    return {'field': field, 'skill_name': skill_name, 'status': status, 'value': value,
            'attribution': attribution, 'evidence': [{'source_id': 'answer', 'quote': quote}]}


def evaluate(context):
    active = context['active_question']
    text = context['message']
    return {'intent': 'answer', 'reply': 'I understand the contribution you described.',
        'actions': [{'kind': 'clarify', 'item_id': active['item_id'], 'question_id': active['id'], 'excerpt': text}],
        'interpretations': [{'item_id': active['item_id'], 'resolution': 'partial',
            'claims': [{'skill_id': 'skill:python', 'name': 'Python', 'attribution': 'personal',
                        'assistance': 'assisted', 'changed_fields': ['attribution', 'assistance'], 'evidence_excerpt': text}],
            'review_evidence': [fact('personal_contribution', text, 'Built the Python API', attribution='personal'),
                                fact('responsibilities', text, 'Implemented the API'),
                                fact('task_scope', text, 'A reporting API', status='partial'),
                                fact('skill_use', text, 'Implemented API handlers', skill_name='Python', attribution='personal')],
            'resolved_uncertainties': [], 'remaining_uncertainties': [active.get('uncertainty', 'claim')]}]}


def test_resume_memory_and_accept_rich_answer_without_another_interpretation_call(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = evaluate
    chat = send(client, chat, 'I built the Python API with guidance. I am unsure about the deployment.')
    assert chat['active_question'], [(a['kind'], a.get('error')) for a in chat['messages'][-1]['actions']]
    assert chat['active_question']['question'] == 'What was the scope of your task?', chat['messages'][-1]
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 1
    assert app.state.interpreter.calls == 0
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    item = next(i for i in saved['items'] if i['id'] == chat['active_question']['item_id'])
    assert len(item['review_evidence']) == 4
    assert next(f for f in item['review_evidence'] if f['field'] == 'task_scope')['status'] == 'partial'
    assert all(r['source_id'].startswith('answer:') for f in item['review_evidence'] for r in f['evidence'])
    assert saved['effective_version'] > cv['effective_version']
    stored = app.state.conversations.get('owner-a', chat['id'])
    assert stored['interview_memory']['questions'][-1]['targets'][0]['field'] == 'task_scope'
    # Reconstruct the coordinator, retaining only its database and configured provider.
    from app.conversation.service import ConversationService
    app.state.conversations = ConversationService(app.state.conversations.cv, provider)
    resumed = client.post(PREFIX, json={'cv_id': cv['id'], 'purpose': 'skills_profile', 'mutation_id': str(uuid4())}).json()
    assert resumed['active_question'] == chat['active_question']
    assert resumed['interview']['status'] == 'reviewing'
    assert len(provider.calls) == 3


def test_side_question_preserves_active_question_and_user_stop_pauses_without_claiming_completion(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    original = chat['active_question']
    before = client.get('/api/v1/cv/' + cv['id']).json()
    chat = send(client, chat, 'Why are you asking about ownership?')
    assert chat['active_question'] == original
    assert client.get('/api/v1/cv/' + cv['id']).json() == before
    provider.evaluation = {'intent': 'stop', 'reply': 'Stop here.', 'actions': []}
    chat = send(client, chat, 'I want to stop now.')
    assert chat['active_question'] is None
    assert chat['interview']['status'] == 'paused'
    assert client.get('/api/v1/cv/' + cv['id']).json()['profile_reviewed_effective_version'] is None
    assert client.get(PREFIX + '/' + chat['id']).json()['interview']['status'] == 'paused'


def test_skip_is_source_bound_and_does_not_make_the_entire_project_unanswerable(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    question = chat['active_question']
    chat = send(client, chat, 'Skip', command='skip')
    assert chat['active_question'] and chat['active_question']['item_id'] == question['item_id'], chat['messages'][-1]
    assert chat['active_question']['id'] != question['id']
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(q for q in saved['clarifications'] if q['id'] == question['id'])['status'] == 'skipped'
    assert chat['active_question']['question'] == 'What was the scope of your task?'


@pytest.mark.parametrize('text', ['Skip', 'skip this question.', 'Please skip that one', 'Pass',
    "I don't want to answer that", 'I don’t want to answer this question', 'do not want to answer',
    "I'd rather not say", 'Prefer not to answer!'])
def test_typed_refusal_skips_without_asking_the_model_to_interpret_it(harness, text):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    question = chat['active_question']
    chat = send(client, chat, text)
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(q for q in saved['clarifications'] if q['id'] == question['id'])['status'] == 'skipped'
    assert not [c for c in provider.calls if c['task'] == 'cv_interview_interpret']
    assert chat['active_question']['id'] != question['id']


@pytest.mark.parametrize('text', ['I skipped the tests and used Python', 'Pass rates improved after my change',
                                  "Skip, but I did use Python", "I don't want to answer for the whole team"])
def test_answers_that_merely_mention_skipping_are_not_refusals(text):
    from app.conversation.interview import is_skip_request
    assert not is_skip_request(text)


@pytest.mark.parametrize('turn', [
    {'intent': 'skip', 'reply': 'Understood.', 'actions': []},
    {'intent': 'answer', 'reply': 'Understood.', 'actions': [{'kind': 'skip', 'excerpt': 'This feels too personal to share.'}]},
])
def test_model_classified_refusal_skips_the_question(harness, turn):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    question = chat['active_question']
    provider.evaluation = turn
    chat = send(client, chat, 'This feels too personal to share.')
    assert all(a['status'] != 'failed' for a in chat['messages'][-1]['actions']), chat['messages'][-1]
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert next(q for q in saved['clarifications'] if q['id'] == question['id'])['status'] == 'skipped'
    assert chat['active_question']['id'] != question['id']


def test_skip_saves_the_field_as_reviewed_with_gaps_and_never_reasks_it(harness):
    from app.conversation.interview_memory import target_availability
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    item_id = chat['active_question']['item_id']
    field = 'personal_contribution'
    chat = send(client, chat, 'Skip this question.')
    service = app.state.conversations
    document = service.cv.get('owner-a', cv['id'])
    source = next(i for i in effective_items(document) if i['id'] == item_id)
    assert [(t['field'], t['status']) for t in source['_review_skips']] == [(field, 'reviewed_with_gaps')]
    memory = reconcile_memory(service.get('owner-a', chat['id']), document)
    assert target_availability(source, memory, field) == 'declined'


def test_skip_closes_a_topic_with_nothing_left_and_moves_to_the_next(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    from app.conversation import interview as module
    original = module.clarification_context
    # Synthetic state: the skipped field was this topic's last open gap.
    module.clarification_context = lambda item, facts=None: (
        {'clarification_targets': []} if item['id'] == first else original(item, facts))
    try:
        chat = send(client, chat, 'I would rather not. Skip', command='skip')
    finally:
        module.clarification_context = original
    assert chat['active_question']['item_id'] == second, chat['messages'][-1]
    assert next(t for t in chat['interview']['topics'] if t['id'] == first)['status'] == 'reviewed_with_gaps'


@pytest.mark.parametrize('multiple_projects', [False, True])
def test_failed_plan_after_skip_closes_the_topic_with_gaps_and_moves_on(harness, multiple_projects):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness) if multiple_projects else start(harness)
    first = chat['active_question']['item_id']
    provider.plans = [{'action': 'answer', 'reply': 'A reply with no next step.'}] * 3
    chat = send(client, chat, 'Skip this question.')
    assert not any(a['status'] == 'failed' for m in chat['messages'] for a in m['actions']), chat['messages'][-1]
    assert next(t for t in chat['interview']['topics'] if t['id'] == first)['status'] == 'reviewed_with_gaps'
    if multiple_projects:
        assert chat['active_question']['item_id'] != first
    else:
        assert chat['active_question'] is None
        assert chat['interview']['status'] == 'reviewed_with_gaps'


def test_finish_closes_a_skipped_topic_when_the_planner_omits_its_coverage(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    first = chat['active_question']['item_id']
    provider.plans = [{'action': 'finish', 'reply': 'Your review is complete.'}]
    chat = send(client, chat, 'Skip this question.')
    assert chat['active_question'] is None, chat['messages'][-1]
    assert next(t for t in chat['interview']['topics'] if t['id'] == first)['status'] == 'reviewed_with_gaps'
    assert chat['interview']['status'] == 'reviewed_with_gaps'


def test_review_accepts_user_statement_without_evidence_verification(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = evaluate
    def forbidden(*args, **kwargs):
        raise AssertionError('Review must not call an evidence verifier')
    app.state.interpreter.verify_evidence = forbidden
    chat = send(client, chat, 'I built the Python API with guidance.')
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert any(q['answer'] == 'I built the Python API with guidance.' and q['interpretation_status'] == 'ready' for q in saved['clarifications'])
    assert chat['active_question']['question'] == 'What was the scope of your task?'
    assert not any(a['status'] == 'failed' for m in chat['messages'] for a in m['actions'])


def test_review_latest_answer_overrides_cv_and_earlier_answer(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    originals = deepcopy(app.state.conversations.cv.get('owner-a', cv['id'])['original_items'])
    provider.evaluation = evaluate
    chat = send(client, chat, 'I built the Python API with guidance.')
    def revised(context):
        output = evaluate(context)
        output['interpretations'][0]['review_evidence'][0] = fact(
            'personal_contribution', context['message'], 'Only observed the API work', attribution='observed')
        output['interpretations'][0]['claims'][0]['attribution'] = 'observed'
        return output
    provider.evaluation = revised
    chat = send(client, chat, 'Actually, I only watched the team build the API.')
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    item = next(i for i in saved['items'] if i['id'] == chat['active_question']['item_id'])
    assert next(f for f in item['review_evidence'] if f['field'] == 'personal_contribution')['value'] == 'Only observed the API work'
    assert next(c for c in item['skill_claims'] if c['name'] == 'Python')['attribution'] == 'observed'
    assert len([q for q in saved['clarifications'] if q['answer']]) == 2
    original = app.state.conversations.cv.get('owner-a', cv['id'])['original_items']
    assert original == originals
    assert saved['version'] > cv['version']


def test_unrelated_review_message_cannot_write_facts_or_advance(harness):
    client, _, *_ = harness
    cv, chat, provider = start(harness)
    original = deepcopy(chat['active_question'])
    before = client.get('/api/v1/cv/' + cv['id']).json()
    provider.evaluation = {'topic_relevant': False, 'intent': 'side_question', 'reply': 'Back to your experience.', 'actions': []}
    chat = send(client, chat, 'What is the weather tomorrow?')
    assert chat['active_question'] == original
    assert client.get('/api/v1/cv/' + cv['id']).json() == before
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_plan']) == 1


def test_malformed_review_schema_has_one_automatic_retry(harness):
    client, _, *_ = harness
    _, chat, provider = start(harness)
    def repair(context):
        return evaluate(context) if context['schema_retry'] else {'intent': 'invalid', 'reply': 'Invalid'}
    provider.evaluation = repair
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['active_question']['question'] == 'What was the scope of your task?'
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 2


def test_progress_counts_topics_not_followup_questions(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    before = deepcopy(chat['interview'])
    provider.evaluation = evaluate
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['interview']['total_items'] == before['total_items'] == 1
    assert chat['interview']['reviewed_items'] == 0
    assert [t['id'] for t in chat['interview']['topics']] == [t['id'] for t in before['topics']]
    resumed = client.get(PREFIX+'/'+chat['id']).json()
    assert resumed['interview']['topics'] == chat['interview']['topics']


def test_repeated_invalid_schema_records_a_direct_numbered_followup(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    active = deepcopy(chat['active_question'])
    provider.evaluation = {'intent': 'invalid', 'reply': 'Malformed'}
    before = client.get('/api/v1/cv/' + cv['id']).json()
    chat = send(client, chat, 'A relevant but unstructured answer.')
    followup = chat['active_question']
    assert followup['id'] != active['id']
    assert (followup['number'], followup['limit']) == (2, 3)
    assert followup['question'] == active['question']
    assert chat['messages'][-1]['text'] == active['question']
    assert not any(a['status'] == 'failed' for a in chat['messages'][-1]['actions'])
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert len(saved['clarifications']) == len(before['clarifications']) + 1
    assert saved['effective_version'] == before['effective_version']
    stored = app.state.conversations.get('owner-a', chat['id'])
    memory = reconcile_memory(stored, app.state.conversations.cv.get('owner-a', cv['id']))
    assert memory['question_counts'][active['item_id']] == 2
    assert client.get(PREFIX + '/' + chat['id']).json()['active_question'] == followup
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 2


def test_schema_followup_publication_retry_keeps_the_same_number(harness, monkeypatch):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = {'intent': 'invalid', 'reply': 'Malformed'}
    service = app.state.conversations.cv
    mutate = service.mutate
    def fail_question(*args, **kwargs):
        if args[3] == 'interview-question':
            raise ValueError('Synthetic question publication failure')
        return mutate(*args, **kwargs)
    monkeypatch.setattr(service, 'mutate', fail_question)
    chat = send(client, chat, 'My saved answer.')
    route = chat['messages'][-1]['actions'][0]
    assert route['status'] == 'failed'
    monkeypatch.setattr(service, 'mutate', mutate)
    response = client.post(PREFIX + '/' + chat['id'] + '/actions/' + route['id'], json={
        'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'decision': 'retry'})
    assert response.status_code == 200, response.text
    resumed = settled(client, chat['id'])
    assert resumed['active_question']['number'] == 2
    document = service.get('owner-a', cv['id'])
    item_id = resumed['active_question']['item_id']
    assert len([q for q in document['clarifications'] if q['item_id'] == item_id and '_interview_targets' in q]) == 2
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 2


def test_invalid_schema_followups_stop_after_three_questions(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    item_id = chat['active_question']['item_id']
    provider.evaluation = {'intent': 'invalid', 'reply': 'Malformed'}
    for number in (2, 3):
        chat = send(client, chat, f'Answer before question {number}.')
        assert (chat['active_question']['number'], chat['active_question']['limit']) == (number, 3)
    chat = send(client, chat, 'Answer to the third question.')
    assert chat['active_question'] is None
    assert chat['interview']['status'] == 'reviewed_with_gaps'
    stored = app.state.conversations.cv.get('owner-a', cv['id'])
    assert len([q for q in stored['clarifications'] if q['item_id'] == item_id and '_interview_targets' in q]) == 3


def test_invalid_schema_at_question_three_moves_to_next_topic(harness):
    client, _, *_ = harness
    _, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    provider.evaluation = {'intent': 'invalid', 'reply': 'Malformed'}
    for number in (2, 3):
        chat = send(client, chat, f'Answer before question {number}.')
        assert chat['active_question']['number'] == number
    chat = send(client, chat, 'Answer to the third question.')
    assert chat['active_question']['item_id'] != first
    assert chat['active_question']['number'] == 1
    assert next(t for t in chat['interview']['topics'] if t['id'] == first)['status'] == 'reviewed_with_gaps'


def test_old_evidence_failure_retries_under_review_policy_and_resumes(harness, monkeypatch):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = evaluate
    from app.clarification import service as clarification
    original = clarification.validate_review_interpretation
    def rejected(*args):
        raise ValueError('Some interpreted skill details are not supported by your answer. Your answer is saved; clarify or retry interpretation.')
    monkeypatch.setattr(clarification, 'validate_review_interpretation', rejected)
    chat = send(client, chat, 'I built the Python API with guidance.')
    action = next(a for a in chat['messages'][-1]['actions'] if a['kind'] == 'clarify')
    assert action['status'] == 'failed'
    monkeypatch.setattr(clarification, 'validate_review_interpretation', original)
    coordinator = app.state.conversations
    resume = coordinator.resume_interview
    continuation_states = []
    async def check_continuation(app_arg, account, identifier, action_id):
        stored = coordinator.get(account['id'], identifier)
        from app.conversation.service import action_message
        turn = action_message(stored, action_id)
        parent = next(a for a in turn['actions'] if a['kind'] == 'route')
        continuation_states.append((parent['status'], parent.get('_resume_requested')))
        return await resume(app_arg, account, identifier, action_id)
    monkeypatch.setattr(coordinator, 'resume_interview', check_continuation)
    response = client.post(PREFIX+'/'+chat['id']+'/actions/'+action['id'], json={
        'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'decision': 'retry'})
    assert response.status_code == 200, response.text
    from tests.test_conversation_security import settled
    resumed = settled(client, chat['id'])
    assert resumed['active_question'], [(m['text'], [(a['kind'], a['status'], a['error']) for a in m['actions']]) for m in resumed['messages']]
    saved = client.get('/api/v1/cv/'+cv['id']).json()
    assert len([q for q in saved['clarifications'] if q['answer'] == 'I built the Python API with guidance.']) == 1
    assert all(q['interpretation_status'] == 'ready' for q in saved['clarifications'] if q['answer'])
    assert continuation_states == [('pending', True)]


def test_review_model_paraphrase_does_not_block_relevant_answer(harness):
    client, _, *_ = harness
    cv, chat, provider = start(harness)
    def paraphrase(context):
        result = evaluate(context)
        result['actions'][0]['excerpt'] = 'A model paraphrase of the answer.'
        result['memory_notes'] = [{'source_id': 'answer', 'quote': 'An invalid optional memory quote.'}]
        return result
    provider.evaluation = paraphrase
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['active_question']['question'] == 'What was the scope of your task?'
    saved = client.get('/api/v1/cv/'+cv['id']).json()
    assert any(q['answer'] == 'I built the Python API with guidance.' and q['interpretation_status'] == 'ready' for q in saved['clarifications'])


def context_for(harness):
    cv, chat, provider = start(harness)
    service = harness[1].state.conversations
    stored = service.get('owner-a', chat['id'])
    document = service.cv.get('owner-a', cv['id'])
    memory = reconcile_memory(stored, document)
    return cv, chat, provider, document, memory, build_context(stored, document, memory)


def test_known_fields_and_exhausted_targets_cannot_be_reasked(harness):
    _, _, _, _, memory, context = context_for(harness)
    item = context['focused_source']
    item['review_evidence'] = [fact('role', 'Developer', 'Developer')]
    question = {'action': 'ask', 'reply': 'What was your role?', 'item_id': item['id'], 'targets': [{'field': 'role'}]}
    with pytest.raises(ValueError, match='already known'): validate_decision(question, context, memory)
    question['targets'] = [{'field': 'complexity'}]
    memory['attempts'][item['id'] + ':complexity:'] = {'signature': 'missing', 'count': 2}
    with pytest.raises(ValueError, match='unproductive'): validate_decision(question, context, memory)


def test_finish_requires_coverage_and_team_output_cannot_support_personal_completion(harness):
    _, _, _, _, memory, context = context_for(harness)
    with pytest.raises(ValueError, match='Unvisited'): validate_decision({'action': 'finish', 'reply': 'All done.'}, context, memory)
    source = context['focused_source']['id']
    context['evidence_index'] = {'team': {'item_id': source, **fact('personal_contribution', 'The team built it', 'Team output', attribution='team')},
                                 'task': {'item_id': source, **fact('task_scope', 'A reporting API', 'Reporting API')}}
    team_only = {'action': 'finish', 'reply': 'All done.', 'coverage': [{'item_id': source, 'status': 'reviewed', 'evidence_refs': ['team', 'task']}]}
    # Downgrading never closes a topic nobody has discussed.
    with pytest.raises(ValueError, match='Discuss an experience'):
        validate_decision(team_only, context, memory)
    memory['questions'][0]['answer_status'] = 'answered'
    _, coverage = validate_decision(team_only, context, memory)
    assert coverage[source] == {'item_id': source, 'status': 'reviewed_with_gaps', 'evidence_refs': []}
    decision, coverage = validate_decision({'action': 'finish', 'reply': 'We reviewed this with ownership still uncertain.',
        'coverage': [{'item_id': source, 'status': 'reviewed_with_gaps', 'evidence_refs': ['team']}]}, context, memory)
    assert decision.action == 'finish'
    assert coverage[source]['evidence_refs'] == ['team']


@pytest.mark.parametrize('evidence, refs, reason', [
    ({'task': ('task_scope', None)}, ['task'], 'no_personal_ownership'),
    ({'mine': ('personal_contribution', None), 'task': ('task_scope', None)}, ['mine', 'task'], 'no_personal_ownership'),
    ({'mine': ('personal_contribution', 'personal')}, ['mine'], 'no_task_evidence'),
    ({}, ['gone'], 'no_personal_ownership'),
])
def test_unproven_reviewed_label_is_downgraded_without_blocking_the_next_step(harness, caplog, evidence, refs, reason):
    _, _, _, _, memory, context = context_for(harness)
    source = context['focused_source']['id']
    memory['questions'][0]['answer_status'] = 'answered'
    context['evidence_index'] = {ref: {'item_id': source, **fact(field, 'Synthetic quote', 'Synthetic value', attribution=attribution)}
                                 for ref, (field, attribution) in evidence.items()}
    with caplog.at_level('WARNING', logger='app.conversation.interview_policy'):
        decision, coverage = validate_decision({'action': 'finish', 'reply': 'Private synthetic wording.',
            'coverage': [{'item_id': source, 'status': 'reviewed', 'evidence_refs': refs}]}, context, memory)
    assert decision.action == 'finish'
    assert coverage[source] == {'item_id': source, 'status': 'reviewed_with_gaps', 'evidence_refs': []}
    assert f'reason={reason}' in caplog.text
    assert 'Private synthetic' not in caplog.text


def test_proven_reviewed_label_is_kept_and_unusable_citations_are_dropped(harness):
    _, _, _, _, memory, context = context_for(harness)
    source = context['focused_source']['id']
    memory['questions'][0]['answer_status'] = 'answered'
    context['evidence_index'] = {
        'mine': {'item_id': source, **fact('personal_contribution', 'I built it', 'Built it', attribution='personal')},
        'task': {'item_id': source, **fact('skill_use', 'I wrote it', 'Wrote it')},
        'other': {'item_id': 'another-source', **fact('task_scope', 'Elsewhere', 'Elsewhere')}}
    _, coverage = validate_decision({'action': 'finish', 'reply': 'Review complete.', 'coverage': [
        {'item_id': source, 'status': 'reviewed', 'evidence_refs': ['mine', 'task', 'other', 'gone']}]}, context, memory)
    assert coverage[source] == {'item_id': source, 'status': 'reviewed', 'evidence_refs': ['mine', 'task']}


def test_finish_keeps_saved_labels_for_topics_closed_earlier(harness):
    _, app, *_ = harness
    cv, chat, _ = start_two_topics(harness)
    service = app.state.conversations
    stored = service.get('owner-a', chat['id'])
    document = service.cv.get('owner-a', cv['id'])
    memory = reconcile_memory(stored, document)
    first = chat['active_question']['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    saved = {'item_id': first, 'status': 'reviewed', 'evidence_refs': ['fact:closed-earlier']}
    memory.update(focus_item_id=second, coverage={first: saved})
    memory['questions'] = [{**q, 'item_id': second, 'answer_status': 'answered'} for q in memory['questions']]
    context = build_context(stored, document, memory, focus_id=second)
    assert 'fact:closed-earlier' not in context['evidence_index']
    # Echoing or relabelling a closed topic neither blocks completion nor changes it.
    for status in ('reviewed', 'reviewed_with_gaps', 'deferred'):
        _, coverage = validate_decision({'action': 'finish', 'reply': 'Review complete.', 'coverage': [
            {'item_id': first, 'status': status, 'evidence_refs': ['fact:closed-earlier']},
            {'item_id': second, 'status': 'reviewed_with_gaps', 'evidence_refs': []}]}, context, memory)
        assert coverage[first] == saved
        assert coverage[second]['status'] == 'reviewed_with_gaps'


def test_coverage_for_a_source_outside_the_review_topics_is_ignored(harness):
    _, _, _, _, memory, context = context_for(harness)
    source = context['focused_source']['id']
    memory['questions'][0]['answer_status'] = 'answered'
    context['sources'].append({'id': 'education', 'kind': 'education', 'title': 'Synthetic course'})
    _, coverage = validate_decision({'action': 'finish', 'reply': 'Review complete.', 'coverage': [
        {'item_id': source, 'status': 'reviewed_with_gaps', 'evidence_refs': []},
        {'item_id': 'education', 'status': 'reviewed', 'evidence_refs': []}]}, context, memory)
    assert 'education' not in coverage


def test_estimate_requires_source_specific_personal_skill_use_and_independence(harness):
    _, _, _, _, memory, context = context_for(harness)
    source = context['focused_source']['id']
    context['evidence_index'] = {'use': {'item_id': source, **fact('skill_use', 'Python API', 'API handlers', skill_name='Python')}}
    decision = {'action': 'answer', 'reply': 'Here is the estimate.', 'estimates': [{'item_id': source, 'skill_name': 'Python',
        'level': 'independent_application', 'explanation': 'Independent API work.', 'evidence_refs': ['use']}]}
    with pytest.raises(ValueError, match='personal skill estimate'): validate_decision(decision, context, memory)
    context['focused_source']['skill_claims'][0].update(attribution='personal', assistance='assisted')
    context['evidence_index']['ownership'] = {'item_id': source, **fact('personal_contribution', 'I wrote it', 'Wrote API', skill_name='Python', attribution='personal')}
    context['evidence_index']['help'] = {'item_id': source, **fact('assistance', 'With guidance', 'Guided', skill_name='Python')}
    decision['estimates'][0]['evidence_refs'] = ['use', 'ownership', 'help']
    with pytest.raises(ValueError, match='independence'): validate_decision(decision, context, memory)
    context['focused_source']['skill_claims'][0]['assistance'] = 'independent'
    assert validate_decision(decision, context, memory)[0].estimates[0].level == 'independent_application'


def test_late_plan_cannot_publish_against_changed_source(harness):
    client, app, *_ = harness
    cv, chat, provider = opened(harness)
    def change(_):
        service = app.state.conversations.cv
        doc = service.get('owner-a', cv['id'])
        from app.schemas.cv import ItemMutation
        service.edit('owner-a', cv['id'], cv['items'][1]['id'], ItemMutation.model_validate(mutation(doc['version'], action='update', title='Changed elsewhere')))
    provider.before_plan = change
    chat = send(client, chat, 'Review', command='review')
    assert chat['active_question'] is None
    assert any(a['status'] == 'stale' for m in chat['messages'] for a in m['actions'])


def test_model_cannot_attach_question_or_stop_to_factual_updates():
    with pytest.raises(ValueError, match='cannot change'):
        InterviewTurn.model_validate({'intent': 'side_question', 'reply': 'Why?', 'actions': [{'kind': 'remove', 'item_id': 'a', 'excerpt': 'Why?'}]})


def test_extraction_and_clarification_share_grounded_fields():
    quote = 'I implemented the Python API with guidance.'
    entry = fact('personal_contribution', quote, 'Implemented the API', attribution='personal')
    entry['evidence'][0]['source_id'] = 'b1'
    payload = {'items': [{'kind': 'project', 'title': 'API', 'description': quote, 'explicit': True,
        'skill_names': ['Python'], 'evidence': [{'block_id': 'b1', 'excerpt': quote}], 'review_evidence': [entry]}]}
    blocks = [{'id': 'b1', 'text': quote, 'location': 'Paragraph 1'}]
    checks = evidence_requiring_semantic_check(payload, blocks)
    assert checks
    with pytest.raises(ValueError): validate_extraction(payload, blocks, 'cv')
    supported = frozenset((c['block_id'], c['excerpt']) for c in checks)
    assert validate_extraction(payload, blocks, 'cv', supported)[0]['review_evidence'][0]['field'] == 'personal_contribution'
    payload['items'][0]['review_evidence'][0]['evidence'][0]['quote'] = 'I owned the whole platform.'
    with pytest.raises(ValueError): validate_extraction(payload, blocks, 'cv', supported)


def test_invalid_next_question_is_repaired_without_resubmitting_the_answer(harness):
    client, app, *_ = harness
    _, chat, provider = start(harness)
    provider.evaluation = evaluate
    def duplicate(context):
        return {'action': 'ask', 'reply': 'What were your responsibilities?',
                'item_id': context['focused_source']['id'], 'targets': [{'field': 'responsibilities'}]}
    provider.plans = [duplicate]
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['active_question']['question'] == 'What was the scope of your task?', chat['messages'][-1]
    calls = [c for c in provider.calls if c['task'] == 'cv_interview_plan']
    assert calls[-1]['validation_feedback']
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 1
    assert app.state.interpreter.calls == 0


def test_planning_failure_retry_does_not_duplicate_evidence_or_reinterpret(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = evaluate
    provider.plans = [{'action': 'finish', 'reply': 'Everything is reviewed.'}] * 3
    chat = send(client, chat, 'I built the Python API with guidance.')
    route = chat['messages'][-1]['actions'][0]
    assert route['status'] == 'failed'
    before = client.get('/api/v1/cv/' + cv['id']).json()
    response = client.post(PREFIX+'/'+chat['id']+'/actions/'+route['id'], json={
        'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'decision': 'retry'})
    assert response.status_code == 200, response.text
    from tests.test_conversation_security import settled
    resumed = settled(client, chat['id'])
    assert resumed['active_question'], resumed['messages'][-1]
    after = client.get('/api/v1/cv/' + cv['id']).json()
    assert len([q for q in after['clarifications'] if q['answer']]) == len([q for q in before['clarifications'] if q['answer']]) == 1
    assert after['effective_version'] == before['effective_version']
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 1


def test_budget_pause_retains_memory_without_a_false_review_stamp(harness, monkeypatch):
    client, app, *_ = harness
    cv, chat, _ = opened(harness)
    from app.domain.model_usage import ModelAdmissionError
    def denied(*args, **kwargs): raise ModelAdmissionError('Synthetic exhausted budget')
    monkeypatch.setattr(app.state.conversations, 'route', denied)
    chat = send(client, chat, 'Review', command='review')
    assert chat['interview']['status'] == 'paused'
    assert chat['active_question'] is None
    assert client.get('/api/v1/cv/'+cv['id']).json()['profile_reviewed_effective_version'] is None


def test_memory_recovers_old_source_answers_beyond_the_recent_window(harness):
    _, chat, _, document, memory, _ = context_for(harness)
    service = harness[1].state.conversations
    conversation = service.get('owner-a', chat['id'])
    focus = memory['focus_item_id'] or chat['active_question']['item_id']
    document['clarifications'].append({'id': 'old-answer', 'item_id': focus, 'question': 'What did you build?',
        'answer': 'I personally built the data importer.', 'status': 'answered', 'resolution': 'partial', 'interpretation_status': 'ready'})
    conversation['messages'] = [{'id': str(i), 'role': 'assistant', 'text': 'Later discussion.'} for i in range(20)]
    context = build_context(conversation, document, memory, focus_id=focus)
    assert any(a['id'] == 'answer:old-answer' and 'answer' not in a for a in context['source_answers'])
    assert context['answer_retrieval_required']
    assert len(context['recent_messages']) == 4
    recalled = build_context(conversation, document, memory, focus_id=focus, recall_ids=['answer:old-answer'])
    assert next(a for a in recalled['source_answers'] if a['id'] == 'answer:old-answer')['answer'] == 'I personally built the data importer.'


def test_compaction_preserves_evidence_and_bounds_repeated_answer_payload(harness):
    import json
    _, chat, _, document, memory, _ = context_for(harness)
    conversation = harness[1].state.conversations.get('owner-a', chat['id'])
    focus = chat['active_question']['item_id']
    for n in range(100):
        document['clarifications'].append({'id': f'old-{n}', 'item_id': focus,
            'question': 'What was your contribution?', 'answer': ('Exact synthetic answer. ' * 200),
            'resolution': 'partial', 'interpretation_status': 'ready', 'status': 'answered'})
        memory['questions'].append({'id': f'old-{n}', 'item_id': focus, 'answer_status': 'answered',
            'question': 'Old question wording. ' * 100, 'targets': [{'field': 'outcome'}]})
    before = deepcopy((conversation, document, memory))
    context = build_context(conversation, document, memory, focus_id=focus)
    assert len(json.dumps(context).encode()) < 32 * 1024
    assert context['memory']['discussion'][-1]['answered'] == 100
    assert context['memory']['discussion'][-1]['latest_targets'] == [{'field': 'outcome'}]
    assert 'questions' not in context['memory']
    assert context['focused_source'] == next(i for i in effective_items(document) if i['id'] == focus)
    assert (conversation, document, memory) == before
    assert 'Exact synthetic answer.' not in json.dumps(context)
    recalled = build_context(conversation, document, memory, focus_id=focus, recall_ids=['answer:old-0'])
    assert next(a for a in recalled['source_answers'] if a['id'] == 'answer:old-0')['answer'] == document['clarifications'][-100]['answer']
    assert sum('answer' in a for a in recalled['source_answers']) == 1


def test_compact_answer_index_excludes_other_and_invalidated_sources(harness):
    _, chat, _, document, memory, _ = context_for(harness)
    conversation = harness[1].state.conversations.get('owner-a', chat['id'])
    focus = chat['active_question']['item_id']
    for identifier, item_id, stale in [('foreign', 'other-source', False), ('stale', focus, True)]:
        document['clarifications'].append({'id': identifier, 'item_id': item_id,
            'question': 'Old question', 'answer': 'Excluded answer', 'reconciliation_required': stale})
    context = build_context(conversation, document, memory, focus_id=focus,
                            recall_ids=['answer:foreign', 'answer:stale'])
    assert not {'answer:foreign', 'answer:stale'} & {a['id'] for a in context['source_answers']}


def test_compact_memory_survives_rollover_and_filters_processing_placeholders(harness):
    from app.conversation.interview_memory import discussion_summary
    _, chat, _, document, memory, _ = context_for(harness)
    conversation = harness[1].state.conversations.get('owner-a', chat['id'])
    conversation['interview_memory'] = memory
    conversation['messages'] = [
        {'id': str(n), 'role': 'user', 'text': f'Recent answer {n}'} for n in range(4)] + [
        {'id': 'pending', 'role': 'assistant', 'text': 'Your message is saved. Working on it…'}]
    context = build_context(conversation, document, reconcile_memory(conversation, document))
    assert [m['text'] for m in context['recent_messages']] == [f'Recent answer {n}' for n in range(4)]
    # A new segment inherits durable memory, without copying the old transcript.
    conversation['messages'] = []
    rebuilt = build_context(conversation, document, reconcile_memory(conversation, document))
    assert rebuilt['memory']['discussion'] == discussion_summary(memory)
    assert rebuilt['recent_messages'] == []
    assert rebuilt['evidence_index'] == context['evidence_index']


def test_oversized_recalled_answer_fails_without_truncating_saved_content(harness):
    _, chat, _, document, memory, _ = context_for(harness)
    conversation = harness[1].state.conversations.get('owner-a', chat['id'])
    document['clarifications'].append({'id': 'large', 'item_id': chat['active_question']['item_id'],
        'question': 'What did you do?', 'answer': 'Synthetic exact wording. ' * 5000,
        'status': 'answered', 'interpretation_status': 'ready', 'resolution': 'partial'})
    original = deepcopy(document)
    assert build_context(conversation, document, memory)['answer_retrieval_required']
    with pytest.raises(ValueError, match='too large'):
        build_context(conversation, document, memory, recall_ids=['answer:large'])
    assert document == original


def test_planner_recalls_exact_answer_without_extra_interpretation(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = evaluate
    def recall(context):
        answer = next(a for a in context['source_answers'] if a['interpretation_status'] == 'ready')
        assert 'answer' not in answer
        return {'action': 'recall', 'reply': 'Retrieve earlier wording.', 'recall_ids': [answer['id']]}
    def after_recall(context):
        assert any(a.get('answer') == 'I built the Python API with guidance.' for a in context['source_answers'])
        return {'action': 'ask', 'reply': 'What was the scope of your task?',
                'item_id': context['focused_source']['id'], 'targets': [{'field': 'task_scope'}]}
    provider.plans = [recall, after_recall]
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['active_question']['question'] == 'What was the scope of your task?', chat['messages'][-1]
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_plan']) == 3
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 1
    assert app.state.interpreter.calls == 0


def test_preloaded_next_topic_retains_exact_answer_recall_for_previous_topic(harness):
    client, _, *_ = harness
    _, chat, provider = start_two_topics(harness)
    first = chat['active_question']
    next_topic = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first['item_id'])
    earlier_answer = 'I built the Python API with guidance and tracked feedback in a log.'
    provider.evaluation = evaluate
    provider.plans = [{'action': 'ask', 'item_id': first['item_id'], 'reply': 'What was the scope?',
                       'targets': [{'field': 'task_scope'}]}]
    chat = send(client, chat, earlier_answer)
    provider.plans = [{'action': 'ask', 'item_id': first['item_id'], 'reply': 'Could you repeat the work?',
                       'targets': [{'field': 'replication_confidence'}]}]
    chat = send(client, chat, 'I implemented two Python API endpoints with guidance.')
    requested = 'answer:' + first['id']

    def recall(context):
        assert context['focused_source']['id'] == next_topic
        previous = next(row for row in context['source_answers'] if row['id'] == requested)
        assert previous['item_id'] == first['item_id']
        assert all('answer' not in row for row in context['source_answers'])
        return {'action': 'recall', 'reply': 'Retrieve the earlier wording.', 'recall_ids': [requested]}

    def ask_after_recall(context):
        assert context['focused_source']['id'] == next_topic
        hydrated, = [row for row in context['source_answers'] if 'answer' in row]
        assert hydrated['id'] == requested
        assert hydrated['answer'] == earlier_answer
        assert hydrated['question'] == first['question']
        return {'action': 'ask', 'item_id': next_topic, 'reply': 'What did you personally do next?',
                'targets': [{'field': 'personal_contribution'}]}

    provider.plans = [recall, ask_after_recall]
    calls_before = len(provider.calls)
    chat = send(client, chat, 'I could repeat those endpoints with guidance.')
    assert chat['active_question'] and chat['active_question']['item_id'] == next_topic, chat['messages'][-1]
    assert [call['task'] for call in provider.calls[calls_before:]] == [
        'cv_interview_interpret', 'cv_interview_plan', 'cv_interview_plan']


def test_reviewed_with_gaps_is_a_persistent_interview_outcome(harness):
    client, _, *_ = harness
    _, chat, provider = start(harness)
    provider.evaluation = evaluate
    def finish(context):
        return {'action': 'finish', 'reply': 'We have reviewed your contribution, with deployment still uncertain.',
                'coverage': [{'item_id': context['focused_source']['id'], 'status': 'reviewed_with_gaps', 'evidence_refs': list(context['evidence_index'])[:1]}]}
    provider.plans = [finish]
    chat = send(client, chat, 'I built the Python API with guidance. I do not know about deployment.')
    assert chat['interview']['status'] == 'reviewed_with_gaps', chat['messages'][-1]
    assert chat['active_question'] is None
    assert client.get(PREFIX+'/'+chat['id']).json()['interview']['status'] == 'reviewed_with_gaps'


@pytest.mark.parametrize('task,result', [
    ('cv_interview_interpret', {'intent': 'side_question', 'reply': 'Ownership distinguishes personal from team work.', 'actions': []}),
    ('cv_interview_plan', {'action': 'ask', 'reply': 'Which part did you implement?', 'item_id': 'project', 'targets': [{'field': 'personal_contribution'}]}),
])
def test_real_provider_adapter_uses_the_typed_interview_protocol(monkeypatch, task, result):
    import json
    import httpx
    from app.clients.conversation import ConversationRouter
    monkeypatch.setenv('CV_LLM_BASE_URL', 'https://synthetic-provider.example/v1')
    monkeypatch.setenv('CV_LLM_MODEL', 'synthetic-fixture')
    monkeypatch.setenv('CV_LLM_API_KEY', 'synthetic-secret-for-test')
    requests = []
    real_client = httpx.Client
    def response(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(result)}}]})
    monkeypatch.setattr('app.clients.conversation.Client', lambda **kwargs: real_client(transport=httpx.MockTransport(response), **kwargs))
    text = 'I checked the calculations, but did not build the model.'
    earlier = 'I prefer to review the finance project first.'
    fact_record = {'item_id': 'project', **fact('responsibilities', text, 'Checked calculations')}
    context = {'task': task, 'message': text, 'message_id': 'latest',
        'focused_source': {'id': 'project', 'kind': 'project', 'title': 'Forecast exercise',
            'description': 'Coursework forecast.', 'review_evidence': [fact_record],
            'skill_claims': [{'skill_id': 'skill:excel', 'name': 'Excel'}]},
        'sources': [{'id': 'project', 'kind': 'project', 'title': 'Forecast exercise',
            'listed_skills': ['Excel'], 'questions_remaining': 2, 'coverage': None}],
        'evidence_index': {'fact:checked': fact_record},
        'source_answers': [{'id': 'answer:older', 'question': 'Who built the model?',
            'answer': 'My teammate built the model.'}],
        'recent_messages': [{'id': 'earlier', 'role': 'user', 'text': earlier},
            {'id': 'latest', 'role': 'user', 'text': text}],
        'memory': {'notes': [], 'summary': []},
        'question_options': [{'skill_name': None, 'open_fields': ['personal_contribution'],
            'clarification_fields': ['personal_contribution'], 'closed_fields': {'responsibilities': 'closed'}}]}
    original = deepcopy(context)
    output, metadata = ConversationRouter().route(context)
    assert output.reply == result['reply']
    assert metadata['prompt_version'] == 'cv-interview-14'
    assert len(requests) == 1 and requests[0]['max_tokens'] == 5000
    assert 'untrusted' in requests[0]['messages'][0]['content'].lower()
    assert 'synthetic-secret-for-test' not in json.dumps(requests[0]['messages'])
    outgoing = json.loads(requests[0]['messages'][1]['content'])
    assert outgoing['evidence_index'] == context['evidence_index']
    assert outgoing['source_answers'] == context['source_answers']
    assert outgoing['focused_source']['skill_claims'][0]['skill_id'] == 'skill:excel'
    assert 'review_evidence' not in outgoing['focused_source']
    assert [message['text'] for message in outgoing['recent_messages']] == [earlier]
    assert context == original
    if task == 'cv_interview_interpret':
        assert outgoing['message'] == text
        assert 'question_options' not in outgoing
    else:
        assert 'message' not in outgoing
        assert outgoing['question_options'][0]['open_fields'] == ['personal_contribution']
        assert 'clarification_fields' not in outgoing['question_options'][0]


def test_malformed_review_fields_reach_schema_validation_instead_of_crashing_the_harness():
    payload = {'items': [{'kind': 'project', 'title': 'Synthetic', 'description': 'Synthetic source.',
        'explicit': True, 'evidence': [{'block_id': 'b1', 'excerpt': 'Synthetic source.'}],
        'review_evidence': [{'field': 'role', 'evidence': [{'source_id': 'b1', 'quote': 'Synthetic source.'}]}]}]}
    blocks = [{'id': 'b1', 'text': 'Synthetic source.', 'location': 'Paragraph 1'}]
    assert evidence_requiring_semantic_check(payload, blocks) == []
    with pytest.raises(ValueError): validate_extraction(payload, blocks, 'cv')


def test_ambiguous_source_is_a_choice_without_guessing_or_prepared_facts(harness):
    client, _, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = {'intent': 'answer', 'reply': 'Which experience do you mean?',
        'actions': [{'kind': 'clarify', 'excerpt': 'I helped with that project.',
                     'candidate_item_ids': [i['id'] for i in cv['items'] if i['kind'] in {'project', 'education'}]}]}
    before = client.get('/api/v1/cv/'+cv['id']).json()
    chat = send(client, chat, 'I helped with that project.')
    choice = next(a for a in chat['messages'][-1]['actions'] if a['kind'] == 'clarify')
    assert choice['status'] == 'needs_source' and len(choice['choices']) == 2
    assert client.get('/api/v1/cv/'+cv['id']).json() == before


def test_followup_updates_only_addressed_fields_and_preserves_known_ownership(harness):
    client, _, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = evaluate
    chat = send(client, chat, 'I built the Python API with guidance.')
    before = client.get('/api/v1/cv/'+cv['id']).json()
    def outcome(context):
        active = context['active_question']
        assert active['uncertainty'] == 'claim'
        return {'intent': 'answer', 'reply': 'Captured the result.',
            'actions': [{'kind': 'clarify', 'item_id': active['item_id'], 'question_id': active['id'], 'excerpt': context['message']}],
            'interpretations': [{'item_id': active['item_id'], 'resolution': 'resolved', 'claims': [],
                'review_evidence': [fact('outcome', context['message'], 'Released the reporting API')],
                'resolved_uncertainties': ['claim'], 'remaining_uncertainties': []}]}
    provider.evaluation = outcome
    chat = send(client, chat, 'We released the reporting API.')
    after = client.get('/api/v1/cv/'+cv['id']).json()
    source = chat['active_question']['item_id']
    previous = next(i for i in before['items'] if i['id'] == source)
    current = next(i for i in after['items'] if i['id'] == source)
    assert current['skill_claims'] == previous['skill_claims']
    assert next(f for f in current['review_evidence'] if f['field'] == 'personal_contribution')['value'] == 'Built the Python API'
    assert next(f for f in current['review_evidence'] if f['field'] == 'outcome')['value'] == 'Released the reporting API'


def test_answer_recall_does_not_spend_planner_validation_retries(harness):
    client, app, *_ = harness
    _, chat, provider = start(harness)
    provider.evaluation = evaluate

    def recall(context):
        answer = next(a for a in context['source_answers'] if a['interpretation_status'] == 'ready')
        return {'action': 'recall', 'reply': 'Retrieve the saved answer.', 'recall_ids': [answer['id']]}

    def known_target(context):
        assert any(a.get('answer') for a in context['source_answers'])
        return {'action': 'ask', 'reply': 'What were your responsibilities?',
                'item_id': context['focused_source']['id'], 'targets': [{'field': 'responsibilities'}]}

    provider.plans = [recall, known_target, known_target]
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['active_question']['question'] == 'What was the scope of your task?', chat['messages'][-1]
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_plan']) == 5
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 1
    assert app.state.interpreter.calls == 0


def start_two_topics(harness):
    from tests.conftest import TEXT
    harness[2].payload = {'items': [
        {'kind': 'project', 'title': 'Team application', 'description': TEXT[1], 'explicit': True,
         'evidence': [{'block_id': 'b2', 'excerpt': TEXT[1]}], 'skill_names': ['Python', 'SQL'],
         'uncertainties': ['personal_contribution']},
        {'kind': 'project', 'title': 'Personal data analysis', 'description': TEXT[2], 'explicit': True,
         'evidence': [{'block_id': 'b3', 'excerpt': TEXT[2]}], 'skill_names': ['SQL'],
         'uncertainties': ['personal_contribution']}]}
    return start(harness)


def test_topic_stays_current_when_model_marks_it_covered_during_followups(harness):
    client, _, *_ = harness
    _, chat, provider = start_two_topics(harness)
    topic = chat['active_question']['item_id']
    provider.evaluation = evaluate

    def followup(context):
        return {'action': 'ask', 'reply': 'What was the scope of your task?', 'item_id': topic,
                'targets': [{'field': 'task_scope'}],
                'coverage': [{'item_id': topic, 'status': 'reviewed',
                              'evidence_refs': list(context['evidence_index'])}]}

    provider.plans = [followup, followup]
    for _ in range(2):
        chat = send(client, chat, 'I built the Python API with guidance.')
        assert chat['active_question']['item_id'] == topic, chat['messages'][-1]
        assert chat['interview']['reviewed_items'] == 0
        assert chat['interview']['total_items'] == 2
        assert next(t for t in chat['interview']['topics'] if t['id'] == topic)['status'] == 'current'
        assert client.get(PREFIX + '/' + chat['id']).json()['interview'] == chat['interview']


@pytest.mark.parametrize('explicit_coverage', [False, True])
def test_progress_advances_on_transition_and_stays_stable_through_next_topic(harness, explicit_coverage):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    provider.evaluation = evaluate

    def switch(context):
        return {'action': 'ask', 'reply': 'Let’s move to your other project. What did you personally do?',
                'item_id': second, 'targets': [{'field': 'personal_contribution'}],
                'coverage': [{'item_id': first, 'status': 'reviewed',
                              'evidence_refs': [ref for ref, value in context['evidence_index'].items()
                                                if value['item_id'] == first]}] if explicit_coverage else []}

    provider.plans = [switch, switch]  # Selection, then hydration of the next source.
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['active_question']['item_id'] == second, chat['messages'][-1]
    assert chat['interview']['reviewed_items'] == 1
    assert chat['interview']['total_items'] == 2
    states = {t['id']: t['status'] for t in chat['interview']['topics']}
    assert states[first] == ('reviewed' if explicit_coverage else 'reviewed_with_gaps')
    assert states[second] == 'current'

    observed = []
    provider.before_plan = lambda _: observed.append(client.get(PREFIX + '/' + chat['id']).json()['interview']['reviewed_items'])
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert observed == [1], observed
    assert chat['active_question']['item_id'] == second
    assert chat['interview']['reviewed_items'] == 1
    assert client.get(PREFIX + '/' + chat['id']).json()['interview'] == chat['interview']

    provider.before_plan = None
    def finish(context):
        return {'action': 'finish', 'reply': 'Your review is complete.',
                'coverage': [{'item_id': second, 'status': 'reviewed_with_gaps', 'evidence_refs': []}]}
    provider.plans = [finish]
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['interview']['reviewed_items'] == chat['interview']['total_items'] == 2
    assert chat['interview']['status'] == 'reviewed_with_gaps'
    assert client.get(PREFIX + '/' + chat['id']).json()['interview'] == chat['interview']

    # Explicit source corrections still reopen the affected topic.
    from app.schemas.cv import ItemMutation
    service = app.state.conversations.cv
    document = service.get('owner-a', cv['id'])
    service.edit('owner-a', cv['id'], first, ItemMutation.model_validate(
        mutation(document['version'], action='update', title='Corrected project title')))
    reopened = client.get(PREFIX + '/' + chat['id']).json()['interview']
    assert reopened['reviewed_items'] == 1
    assert next(t for t in reopened['topics'] if t['id'] == first)['status'] == 'pending'


def test_transition_cannot_mark_conflicting_previous_ownership_fully_reviewed(harness):
    _, _, _, _, memory, context = context_for(harness)
    source = context['focused_source']['id']
    context['sources'].append({'id': 'next', 'kind': 'project', 'title': 'Next project'})
    context['focused_source'] = {'id': 'next', 'kind': 'project', 'review_evidence': [], 'skill_claims': [],
                                 'uncertainties': ['personal_contribution']}
    memory['questions'][0]['answer_status'] = 'answered'
    context['evidence_index'] = {
        'personal': {'item_id': source, **fact('personal_contribution', 'I implemented it', 'Implemented API', attribution='personal')},
        'task': {'item_id': source, **fact('task_scope', 'Reporting API', 'Reporting API')},
        'conflict': {'item_id': source, **fact('responsibilities', 'Ownership unclear', 'Ownership unclear', status='conflicting')}}
    decision, coverage = validate_decision({'action': 'ask', 'reply': 'Moving on, what did you implement?',
                      'item_id': 'next', 'targets': [{'field': 'task_scope'}],
                      'coverage': [{'item_id': source, 'status': 'reviewed', 'evidence_refs': ['personal', 'task']}]},
                     context, memory)
    assert decision.item_id == 'next'
    assert coverage[source] == {'item_id': source, 'status': 'reviewed_with_gaps', 'evidence_refs': []}


def test_planner_rejections_keep_safe_bounded_diagnostics(harness, caplog):
    client, app, *_ = harness
    _, chat, provider = start(harness)
    provider.evaluation = evaluate
    provider.plans = [{'action': 'finish', 'reply': 'Private provider wording must not be logged.'}] * 3
    answer = 'I built the Python API with guidance. Private synthetic answer.'
    chat = send(client, chat, answer)
    action = chat['messages'][-1]['actions'][0]
    assert action['status'] == 'failed'
    assert '_interview_planning' not in action
    stored = app.state.conversations.get('owner-a', chat['id'])
    from app.conversation.service import action_in
    assert action_in(stored, action['id'])['_interview_planning'] == [
        {'reason': 'finish_unvisited', 'action': 'finish'}] * 3
    assert 'reason=finish_unvisited' in caplog.text
    assert answer not in caplog.text
    assert 'Private provider wording' not in caplog.text


def test_planner_options_use_the_same_unknown_and_attempt_policy_as_validation(harness):
    from app.conversation.interview_memory import question_options, target_availability
    _, _, _, _, memory, context = context_for(harness)
    item = context['focused_source']
    item['review_evidence'] = [fact('responsibilities', 'I do not know.', status='unknown')]
    memory['attempts'][item['id'] + ':complexity:'] = {'signature': 'missing', 'count': 1}
    memory['max_target_attempts'] = 1
    options = next(o for o in question_options(item, memory) if o['skill_name'] is None)
    assert options['closed_fields']['responsibilities'] == 'closed'
    assert options['closed_fields']['complexity'] == 'exhausted'
    assert 'task_scope' not in options['open_fields']  # Missing but irrelevant to this current clarification.
    for field in ('responsibilities', 'complexity'):
        assert target_availability(item, memory, field, max_attempts=1) != 'open'
        with pytest.raises(ValueError, match='already known'):
            validate_decision({'action': 'ask', 'reply': 'Please explain the detail.',
                               'item_id': item['id'], 'targets': [{'field': field}]}, context, memory, max_attempts=1)
    memory['max_target_attempts'] = 3
    assert target_availability(item, memory, 'complexity', max_attempts=3) == 'open'
    assert 'complexity' not in next(o for o in question_options(item, memory) if o['skill_name'] is None)['open_fields']


def test_provider_schema_rejection_replans_without_resubmitting_saved_answer(harness, caplog):
    from app.schemas.interview import InterviewDecision
    client, app, *_ = harness
    _, chat, provider = start(harness)
    provider.evaluation = evaluate

    def malformed(_):
        # The real adapter validates before returning, outside validate_decision.
        return InterviewDecision.model_validate({'action': 'private-invalid-provider-value', 'reply': 'Private provider prose.'})

    provider.plans = [malformed]
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['active_question']['question'] == 'What was the scope of your task?', chat['messages'][-1]
    assert 'reason=invalid_schema' in caplog.text
    assert 'private-invalid-provider-value' not in caplog.text
    assert 'Private provider prose' not in caplog.text
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 1
    assert app.state.interpreter.calls == 0


@pytest.mark.parametrize('skip_third', [False, True])
def test_three_questions_per_topic_then_transition_without_a_fourth(harness, skip_third):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    provider.evaluation = evaluate

    def ask(field, question, item_id=first):
        return {'action': 'ask', 'reply': question, 'item_id': item_id, 'targets': [{'field': field}]}

    provider.plans = [ask('task_scope', 'What was the scope?')]
    chat = send(client, chat, 'I built the Python API with guidance.')
    provider.plans = [ask('replication_confidence', 'How confident are you about repeating a similar task?')]
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['active_question']['question'] == 'How confident are you about repeating a similar task?'
    assert chat['interview']['reviewed_items'] == 0
    provider.plans = [ask('complexity', 'A fourth question must not be published.'),
                      ask('personal_contribution', 'What did you handle in the next project?', second),
                      ask('personal_contribution', 'What did you handle in the next project?', second)]
    chat = (send(client, chat, 'Skip this question.', command='skip') if skip_third
            else send(client, chat, 'I could repeat it with guidance.'))
    assert chat['active_question']['item_id'] == second, chat['messages'][-1]
    assert chat['interview']['reviewed_items'] == 1
    assert all('fourth question' not in m['text'] for m in chat['messages'])
    document = app.state.conversations.cv.get('owner-a', cv['id'])
    assert len([q for q in document['clarifications'] if q['item_id'] == first and '_interview_targets' in q]) == 3
    stored = app.state.conversations.get('owner-a', chat['id'])
    assert stored['interview_memory']['question_counts'][first] == 3
    # Counts survive bounded memory loss/segment rollover because CV owns all issued questions.
    inherited = deepcopy(stored)
    inherited['messages'] = []
    inherited['interview_memory']['questions'] = []
    inherited['interview_memory']['question_counts'] = {}
    rebuilt = reconcile_memory(inherited, document)
    context = build_context(inherited, document, rebuilt, focus_id=first)
    assert context['topic_question_budget'] == {'asked': 3, 'remaining': 0}
    assert all(not option['open_fields'] for option in context['question_options'])
    with pytest.raises(ValueError, match='three questions'):
        validate_decision(ask('complexity', 'Try a fourth after reload.'), context, rebuilt)
    assert client.get(PREFIX + '/' + chat['id']).json()['active_question']['item_id'] == second


def test_third_answer_records_replication_confidence_and_finishes_with_gaps(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = evaluate
    topic = chat['active_question']['item_id']
    provider.plans = [{'action': 'ask', 'reply': 'What was the scope?', 'item_id': topic, 'targets': [{'field': 'task_scope'}]}]
    chat = send(client, chat, 'I built the Python API with guidance.')
    provider.plans = [{'action': 'ask', 'reply': 'Could you repeat a similar task today?', 'item_id': topic,
                       'targets': [{'field': 'replication_confidence'}]}]
    chat = send(client, chat, 'I built the Python API with guidance.')

    def confidence(context):
        result = evaluate(context)
        result['interpretations'][0]['review_evidence'].append(
            fact('replication_confidence', context['message'], 'Confident in repeating a similar task with guidance.'))
        return result

    provider.evaluation = confidence
    provider.plans = [{'action': 'finish', 'reply': 'The review is complete.'}]
    chat = send(client, chat, 'I am confident I could repeat a similar task with guidance.')
    assert chat['interview']['status'] == 'reviewed_with_gaps', chat['messages'][-1]
    assert chat['interview']['reviewed_items'] == chat['interview']['total_items'] == 1
    assert chat['active_question'] is None
    detail = client.get('/api/v1/cv/' + cv['id']).json()
    item = next(item for item in detail['items'] if item['id'] == topic)
    assert next(f for f in item['review_evidence'] if f['field'] == 'replication_confidence')['value'] == 'Confident in repeating a similar task with guidance.'
    assert len(detail['clarifications']) == 3
    assert all('_interview_targets' not in q for q in detail['clarifications'])
    raw = app.state.conversations.cv.get('owner-a', cv['id'])
    assert len([q for q in raw['clarifications'] if '_interview_targets' in q]) == 3


def test_evidence_references_are_removed_from_delivered_prose_not_structured_data(harness):
    client, app, *_ = harness
    _, chat, provider = opened(harness)
    ref = 'fact:' + 'a' * 24
    answer_ref = 'answer:11111111-1111-4111-8111-111111111111'

    def question(context):
        return {'action': 'ask', 'reply': f'What was the task scope? [Evidence IDs: {ref}, {answer_ref}]',
                'item_id': context['focused_source']['id'], 'targets': [{'field': 'task_scope'}]}

    provider.plans = [question]
    chat = send(client, chat, 'Review my CV', command='review')
    assert chat['active_question']['question'] == 'What was the task scope?'
    assert chat['messages'][-1]['text'] == 'What was the task scope?'
    assert chat['active_question']['item_id']
    # Read projection also cleans legacy prose without rewriting history or user messages.
    def legacy(current):
        current['messages'][-1]['text'] += f' [{ref}]'
        next(m for m in current['messages'] if m['role'] == 'user')['text'] = f'My exact reference: {ref}'
    app.state.conversations.update('owner-a', chat['id'], legacy)
    delivered = client.get(PREFIX + '/' + chat['id']).json()
    assert delivered['messages'][-1]['text'] == 'What was the task scope?'
    assert next(m for m in delivered['messages'] if m['role'] == 'user')['text'] == f'My exact reference: {ref}'
    stored = app.state.conversations.get('owner-a', chat['id'])
    assert ref in stored['messages'][-1]['text']


def known_cv_review_facts():
    return [fact('personal_contribution', 'I implemented the API.', 'Implemented the API', attribution='personal'),
            fact('responsibilities', 'I owned testing.', 'Owned implementation and testing', attribution='personal'),
            fact('task_scope', 'A Python reporting API.', 'Python reporting API')]


def test_clear_role_context_still_reviews_skill_baseline_without_repeating_the_cv(harness):
    client, app, *_ = harness
    cv, chat, provider = opened(harness)
    service = app.state.conversations.cv
    original = service.get('owner-a', cv['id'])
    changed = deepcopy(original)
    item = next(i for i in changed['original_items'] if i['kind'] == 'project')
    item['review_evidence'] = known_cv_review_facts()
    item['uncertainties'] = ['personal_contribution', 'proficiency', 'duration']
    from app.domain.service import bump
    bump(changed)
    service.repository.replace(original, changed)
    provider.plans = [{'action': 'ask', 'reply': 'Which Python component did you implement yourself?',
        'item_id': item['id'], 'targets': [{'field': 'skill_use', 'skill_name': 'Python'}]}]
    chat = send(client, chat, 'Review my CV', command='review')
    assert chat['interview']['status'] == 'reviewing'
    assert chat['interview']['total_items'] == 1
    assert chat['active_question']['question'] == 'Which Python component did you implement yourself?'
    assert len(provider.calls) == 1
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert saved['skills']
    assert len(saved['clarifications']) == 1
    assert saved['skill_estimates'] == []
    stored = app.state.conversations.get('owner-a', chat['id'])
    assert {e['skill_name']: e['level'] for e in stored['interview_memory']['estimates']} == {'Python': 'insufficient_evidence', 'SQL': 'insufficient_evidence'}
    assert chat['interview']['estimates'] == []


def test_review_clarifies_only_ambiguous_ownership_then_finishes_without_three_questions(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    def resolve(context):
        active = context['active_question']
        return {'intent': 'answer', 'reply': 'Understood your part.',
                'actions': [{'kind': 'clarify', 'item_id': active['item_id'], 'question_id': active['id'], 'excerpt': context['message']}],
                'interpretations': [{'item_id': active['item_id'], 'resolution': 'resolved',
                    'claims': [{'skill_id': 'skill:' + name.lower(), 'name': name, 'attribution': 'personal',
                                'assistance': 'assisted', 'changed_fields': ['attribution', 'assistance'],
                                'evidence_excerpt': context['message']} for name in ('Python', 'SQL')],
                    'review_evidence': [fact('personal_contribution', context['message'], 'Personally coordinated testing', attribution='personal'),
                                        fact('responsibilities', context['message'], 'Coordinated testing and reported issues'),
                                        *[fact('skill_use', context['message'], 'Implemented testing support', skill_name=name, attribution='personal') for name in ('Python', 'SQL')],
                                        *[fact('self_rating', context['message'], '5', skill_name=name) for name in ('Python', 'SQL')]],
                    'resolved_uncertainties': ['personal_contribution', 'claim'], 'remaining_uncertainties': []}]}
    provider.evaluation = resolve
    chat = send(client, chat, 'I personally used Python and SQL to coordinate testing with guidance and reported the issues. I rate both skills 5/10.')
    assert chat['active_question'] is None, chat['messages'][-1]
    assert chat['interview']['reviewed_items'] == chat['interview']['total_items'] == 1
    assert chat['interview']['status'] in {'reviewed', 'reviewed_with_gaps'}
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_plan']) == 1  # Opening only.
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 1
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert len(saved['clarifications']) == 1
    assert client.get(PREFIX + '/' + chat['id']).json()['interview'] == chat['interview']


def test_context_distinguishes_known_cv_skills_from_unresolved_personal_responsibility(harness):
    from app.domain.review_context import clarification_context
    _, _, _, _, memory, context = context_for(harness)
    source = context['focused_source']
    assert source['description'] and source['evidence']
    assert context['sources'][1]['listed_skills']
    targets = context['clarification_context']['clarification_targets']
    assert {t['field'] for t in targets} == {'personal_contribution', 'skill_use', 'self_rating'}
    assert {t['skill_name'] for t in targets if t['field'] == 'skill_use'} == {'Python', 'SQL'}
    clear = {**source, 'review_evidence': known_cv_review_facts(), 'uncertainties': ['proficiency', 'duration']}
    assert {t['field'] for t in clarification_context(clear, known_cv_review_facts())['clarification_targets']} == {'skill_use','self_rating'}
    context['focused_source'] = clear
    with pytest.raises(ValueError, match='already known'):
        validate_decision({'action': 'ask', 'reply': 'Repeat your responsibilities.', 'item_id': clear['id'],
                           'targets': [{'field': 'responsibilities'}]}, context, memory)


def test_three_questions_for_each_project_not_three_for_the_entire_baseline_review(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)

    def rich(context):
        active, text = context['active_question'], context['message']
        names = [c['name'] for c in context['focused_source']['skill_claims']]
        # Concrete skill use arrives only with each topic's third answer, so neither topic
        # has enough context early and both use their own full three-question budget.
        used = names if context['topic_question_budget']['asked'] >= 3 else []
        return {'intent': 'answer', 'reply': 'Your personal contribution is captured.',
            'actions': [{'kind': 'clarify', 'item_id': active['item_id'], 'question_id': active['id'], 'excerpt': text}],
            'interpretations': [{'item_id': active['item_id'], 'resolution': 'partial',
                'claims': [{'skill_id': 'skill:' + name.lower(), 'name': name, 'attribution': 'personal',
                            'assistance': 'assisted', 'changed_fields': ['attribution', 'assistance'], 'evidence_excerpt': text}
                           for name in names],
                'review_evidence': [fact('personal_contribution', text, 'Personally implemented the pipeline', attribution='personal'),
                                    fact('responsibilities', text, 'Implemented and tested the pipeline'),
                                    fact('task_scope', text, 'The scope still has a small ambiguity', status='partial'),
                                    *[fact('skill_use', text, 'Implemented the pipeline', skill_name=name, attribution='personal') for name in used]],
                'resolved_uncertainties': [], 'remaining_uncertainties': ['claim']}]}

    provider.evaluation = rich
    def ask(item, field):
        return {'action': 'ask', 'item_id': item, 'reply': f'Clarify your personal {field.replace("_", " ")} in this project.',
                'targets': [{'field': field}]}
    provider.plans = [ask(first, 'task_scope')]
    chat = send(client, chat, 'I personally implemented the Python and SQL pipeline with guidance.')
    provider.plans = [ask(first, 'complexity')]
    chat = send(client, chat, 'I personally implemented the Python and SQL pipeline with guidance.')
    before_transition = len(provider.calls)
    provider.plans = [ask(second, 'personal_contribution'), ask(second, 'personal_contribution')]
    chat = send(client, chat, 'I personally implemented the Python and SQL pipeline with guidance.')
    assert chat['active_question']['item_id'] == second
    assert chat['interview']['reviewed_items'] == 1
    interpretation, plan = provider.calls[before_transition:]
    assert interpretation['task'] == 'cv_interview_interpret'
    assert interpretation['focused_source']['id'] == first
    assert plan['task'] == 'cv_interview_plan'
    assert plan['focused_source']['id'] == second
    assert any(fact['item_id'] == first for fact in plan['evidence_index'].values())
    provider.plans = [ask(second, 'task_scope')]
    chat = send(client, chat, 'I personally implemented the SQL pipeline with guidance.')
    provider.plans = [ask(second, 'complexity')]
    chat = send(client, chat, 'I personally implemented the SQL pipeline with guidance.')
    chat = send(client, chat, 'I personally implemented the SQL pipeline with guidance.')
    assert chat['active_question'] is None
    assert chat['interview']['reviewed_items'] == chat['interview']['total_items'] == 2
    raw = app.state.conversations.cv.get('owner-a', cv['id'])
    assert {item: len([q for q in raw['clarifications'] if q['item_id'] == item]) for item in (first, second)} == {first: 3, second: 3}
    assert len(raw['clarifications']) == 6
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    baseline = {(e['item_id'], e['skill_name']): e['level'] for e in saved['skill_estimates']}
    assert baseline == {(first, 'Python'): 'guided_application', (first, 'SQL'): 'guided_application', (second, 'SQL'): 'guided_application'}
    assert {(e['item_id'], e['skill_name']) for e in chat['interview']['estimates']} == set(baseline)


def test_published_baseline_memory_is_canonical_before_status_polling(harness):
    client, app, *_ = harness
    _, chat, provider = start(harness)
    provider.evaluation = evaluate
    chat = send(client, chat, 'I built the Python API with guidance.')
    before = deepcopy(app.state.conversations.get('owner-a', chat['id']))
    first = client.get(PREFIX + '/' + chat['id']).json()
    second = client.get(PREFIX + '/' + chat['id']).json()
    after = app.state.conversations.get('owner-a', chat['id'])
    assert before['interview_memory'] == after['interview_memory']
    assert first['revision'] == second['revision'] == before['revision']
    assert first['interview'] == second['interview']


def test_supported_estimates_are_public_while_insufficient_evidence_stays_in_backend(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation = evaluate
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert {e['skill_name']: e['level'] for e in chat['interview']['estimates']} == {'Python': 'guided_application'}
    public_cv = client.get('/api/v1/cv/' + cv['id']).json()
    assert {e['skill_name']: e['level'] for e in public_cv['skill_estimates']} == {'Python': 'guided_application'}
    stored = app.state.conversations.get('owner-a', chat['id'])
    expected = {'Python': 'guided_application', 'SQL': 'insufficient_evidence'}
    assert {e['skill_name']: e['level'] for e in stored['interview_memory']['estimates']} == expected
    assert {e['skill_name']: e['level'] for e in stored['interview_progress']['estimates']} == expected
    refreshed = client.get(PREFIX + '/' + chat['id']).json()
    assert refreshed['interview']['estimates'] == chat['interview']['estimates']


def test_skipped_ownership_is_uncertain_and_cannot_block_a_topic_transition(harness):
    from app.conversation.interview_memory import target_availability
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    before = app.state.conversations.cv.get('owner-a', cv['id'])
    def next_project(context):
        return {'action': 'ask', 'reply': 'What did you personally handle in the next project?',
                'item_id': second, 'targets': [{'field': 'personal_contribution'}],
                'coverage': [{'item_id': first, 'status': 'reviewed', 'evidence_refs': ['unusable-model-reference']}]}
    provider.plans = [next_project, next_project]
    chat = send(client, chat, 'Skip this question.', command='skip')
    assert chat['active_question']['item_id'] == second, chat['messages'][-1]
    assert next(t for t in chat['interview']['topics'] if t['id'] == first)['status'] == 'reviewed_with_gaps'
    service = app.state.conversations
    document = service.cv.get('owner-a', cv['id'])
    source = next(i for i in effective_items(document) if i['id'] == first)
    assert source['_review_skips'] == [{'field': 'personal_contribution', 'skill_name': None,
                                       'status': 'reviewed_with_gaps', 'question_id': document['clarifications'][0]['id']}]
    assert document['original_items'] == before['original_items']
    assert document['clarifications'][0]['answer'] is None
    assert document['clarifications'][0]['interpretation'] is None
    memory = reconcile_memory(service.get('owner-a', chat['id']), document)
    assert target_availability(source, memory, 'personal_contribution') == 'declined'
    assert target_availability(source, memory, 'personal_contribution', 'Python') == 'declined'
    assert client.get(PREFIX + '/' + chat['id']).json()['interview'] == chat['interview']
    # A single skip cannot mark an unvisited second project complete.
    context = build_context(service.get('owner-a', chat['id']), document, memory)
    with pytest.raises(ValueError, match='Unvisited'):
        validate_decision({'action': 'finish', 'reply': 'Finish everything.'}, context, memory)


@pytest.mark.parametrize('multiple_projects', [False, True])
def test_skip_and_continue_recovers_planning_failure_without_resubmitting_answer(harness, multiple_projects):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness) if multiple_projects else start(harness)
    first = chat['active_question']['item_id']
    provider.evaluation = evaluate
    provider.plans = [{'action': 'answer', 'reply': 'A reply with no next step.'}] * 3
    chat = send(client, chat, 'I built the Python API with guidance.')
    failed = next(a for a in chat['messages'][-1]['actions'] if a['kind'] == 'route')
    assert failed['status'] == 'failed'
    assert chat['active_question'] is None
    before = app.state.conversations.cv.get('owner-a', cv['id'])
    chat = send(client, chat, 'Skip remaining questions for this experience.', command='skip')
    stored = app.state.conversations.get('owner-a', chat['id'])
    from app.conversation.service import action_in
    assert action_in(stored, failed['id'])['status'] == 'cancelled'
    assert stored['interview_memory']['deferred_topics'][first] == {'reason': 'user_skip', 'remaining_ownership': 'uncertain'}
    assert next(t for t in chat['interview']['topics'] if t['id'] == first)['status'] == 'deferred'
    after = app.state.conversations.cv.get('owner-a', cv['id'])
    answered_before = [q for q in before['clarifications'] if q.get('answer')]
    assert [q for q in after['clarifications'] if q.get('answer')] == answered_before
    assert after['effective_version'] == before['effective_version']
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_interpret']) == 1
    assert not any(a['status'] in {'pending', 'failed'} for m in chat['messages'] for a in m['actions'])
    if multiple_projects:
        assert chat['active_question']['item_id'] != first
        assert chat['interview']['reviewed_items'] == 1
    else:
        assert chat['active_question'] is None
        assert chat['interview']['status'] == 'reviewed_with_gaps'
    refreshed = client.get(PREFIX + '/' + chat['id']).json()
    assert refreshed['interview'] == chat['interview']
    assert app.state.conversations.get('owner-a', chat['id'])['interview_memory']['deferred_topics'] == stored['interview_memory']['deferred_topics']


def test_source_correction_does_not_reuse_an_old_ownership_skip(harness):
    client, app, *_ = harness
    cv, chat, _ = start(harness)
    source_id = chat['active_question']['item_id']
    chat = send(client, chat, 'Skip this question.', command='skip')
    service = app.state.conversations.cv
    document = service.get('owner-a', cv['id'])
    assert next(i for i in effective_items(document) if i['id'] == source_id)['_review_skips']
    from app.schemas.cv import ItemMutation
    service.edit('owner-a', cv['id'], source_id, ItemMutation.model_validate(
        mutation(document['version'], action='update', title='Corrected source context')))
    changed = service.get('owner-a', cv['id'])
    assert not next(i for i in effective_items(changed) if i['id'] == source_id).get('_review_skips')


def test_explicit_unknown_ownership_allows_finish_with_gaps_without_verified_ownership(harness):
    _, _, _, _, memory, context = context_for(harness)
    source = context['focused_source']['id']
    memory['questions'][0]['answer_status'] = 'answered'
    context['sources'] = [s for s in context['sources'] if s['id'] == source]
    context['sources'][0]['fields'] = [{'field': 'personal_contribution', 'skill_name': None, 'status': 'unknown'}]
    decision, coverage = validate_decision({'action': 'finish', 'reply': 'Review complete.',
        'coverage': [{'item_id': source, 'status': 'reviewed', 'evidence_refs': ['bad-model-reference']}]}, context, memory)
    assert decision.action == 'finish'
    assert coverage[source] == {'item_id': source, 'status': 'reviewed_with_gaps', 'evidence_refs': []}


def topic_status(chat, item_id):
    return next(t for t in chat['interview']['topics'] if t['id'] == item_id)['status']


def test_skip_topic_defers_the_current_topic_and_asks_about_the_next(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    before = app.state.conversations.cv.get('owner-a', cv['id'])
    chat = send(client, chat, 'Skip this topic.', command='skip_topic', item_id=first)
    assert topic_status(chat, first) == 'deferred'
    assert chat['active_question']['item_id'] == second
    assert chat['messages'][-1]['text'].startswith('Skipped Team application. I’ll use your CV as written for it.')
    stored = app.state.conversations.get('owner-a', chat['id'])['interview_memory']
    assert stored['deferred_topics'][first] == {'reason': 'user_skip', 'remaining_ownership': 'uncertain'}
    after = app.state.conversations.cv.get('owner-a', cv['id'])
    # The open question is recorded as skipped; no answer or fact is invented.
    assert next(q for q in after['clarifications'] if q['item_id'] == first)['status'] == 'skipped'
    assert after['effective_version'] == before['effective_version']
    assert not any(c['task'] == 'cv_interview_interpret' for c in provider.calls)


def test_skipping_another_topic_keeps_the_current_question(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    active = chat['active_question']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != active['item_id'])
    plans = len([c for c in provider.calls if c['task'] == 'cv_interview_plan'])
    chat = send(client, chat, 'Skip Personal data analysis.', command='skip_topic', item_id=second)
    assert topic_status(chat, second) == 'deferred'
    assert topic_status(chat, active['item_id']) == 'current'
    assert chat['active_question']['id'] == active['id']
    assert active['question'] in chat['messages'][-1]['text']
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_plan']) == plans


def test_skip_remaining_topics_completes_the_review_with_gaps(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    chat = send(client, chat, 'Skip all remaining topics.', command='skip_remaining', item_id=None)
    assert {t['status'] for t in chat['interview']['topics']} == {'deferred'}
    assert chat['interview']['status'] == 'reviewed_with_gaps'
    assert chat['interview']['reviewed_items'] == chat['interview']['total_items'] == 2
    assert chat['active_question'] is None
    assert chat['messages'][-1]['text'].startswith('Skipped the remaining topics.')
    document = app.state.conversations.cv.get('owner-a', cv['id'])
    assert document['profile_reviewed_effective_version'] == document['effective_version']


def test_a_skipped_topic_can_be_reviewed_again(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    chat = send(client, chat, 'Skip this topic.', command='skip_topic', item_id=first)
    chat = send(client, chat, 'Review Team application instead.', command='review_topic', item_id=first)
    assert chat['active_question']['item_id'] == first
    assert topic_status(chat, first) == 'current'
    assert first not in app.state.conversations.get('owner-a', chat['id'])['interview_memory']['deferred_topics']


def test_reviewing_a_skipped_topic_again_reopens_its_skipped_questions_with_a_fresh_budget(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    chat = send(client, chat, 'Skip this topic.', command='skip_topic', item_id=first)
    from app.domain.capabilities import effective_items
    skipped = [q for q in app.state.conversations.cv.get('owner-a', cv['id'])['clarifications'] if q['item_id'] == first and q['status'] == 'skipped']
    assert skipped and not any(q.get('reopened') for q in skipped)
    chat = send(client, chat, 'Review Team application instead.', command='review_topic', item_id=first)
    document = app.state.conversations.cv.get('owner-a', cv['id'])
    reopened = [q for q in document['clarifications'] if q['item_id'] == first and q['status'] == 'skipped']
    assert reopened and all(q.get('reopened') for q in reopened)
    item = next(i for i in effective_items(document) if i['id'] == first)
    assert not item.get('_review_skips')
    memory = app.state.conversations.get('owner-a', chat['id'])['interview_memory']
    assert memory['question_counts'][first] <= 1
    assert chat['active_question']['item_id'] == first


def test_cv_list_reports_how_many_review_topics_are_covered(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    listed = next(item for item in client.get(PREFIX.replace('/conversations', '')).json()['cvs'] if item['id'] == cv['id'])
    assert listed['review_progress'] == {'reviewed_topics': chat['interview']['reviewed_items'], 'total_topics': 2}


def test_review_topic_must_name_a_skipped_topic_and_skip_topic_an_open_one(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    response = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
        'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'text': 'Skip this topic.', 'command': 'skip_topic'})
    assert response.status_code == 422
    for command, text in (('review_topic', 'Only a skipped topic'), ('skip_topic', None)):
        response = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
            'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'text': 'Change topic.',
            'command': command, 'item_id': first})
        if text:
            assert response.status_code == 409 and text in response.text
    chat = settled(client, chat['id'])
    assert topic_status(chat, first) == 'deferred'
    response = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
        'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'text': 'Skip it again.',
        'command': 'skip_topic', 'item_id': first})
    assert response.status_code == 409 and 'already covered' in response.text


def test_planner_wrong_topic_after_review_request_is_rejected(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)
    chat = send(client, chat, 'Skip this topic.', command='skip_topic', item_id=first)
    assert chat['active_question']['item_id'] == second
    provider.plans = [{'action': 'ask', 'item_id': second, 'reply': 'What was your SQL work?', 'targets': [{'field': 'skill_use', 'skill_name': 'SQL'}]}]
    chat = send(client, chat, 'Review Team application instead.', command='review_topic', item_id=first)
    assert chat['active_question']['item_id'] == first
    stored = app.state.conversations.get('owner-a', chat['id'])
    from app.conversation.service import action_in
    route = next(a for a in chat['messages'][-1]['actions'] if a['kind'] == 'route')
    assert {'reason': 'question_requested_topic', 'action': 'ask'} in action_in(stored, route['id'])['_interview_planning']


def test_topic_ends_early_once_ownership_and_skill_use_are_known(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    second = next(t['id'] for t in chat['interview']['topics'] if t['id'] != first)

    def complete(context):
        active, text = context['active_question'], context['message']
        names = [c['name'] for c in context['focused_source']['skill_claims']]
        return {'intent': 'answer', 'reply': 'Thanks.',
            'actions': [{'kind': 'clarify', 'item_id': active['item_id'], 'question_id': active['id'], 'excerpt': text}],
            'interpretations': [{'item_id': active['item_id'], 'resolution': 'resolved',
                'claims': [{'skill_id': 'skill:' + n.lower(), 'name': n, 'attribution': 'personal',
                            'changed_fields': ['attribution'], 'evidence_excerpt': text} for n in names],
                'review_evidence': [fact('personal_contribution', text, 'Built the pipeline', attribution='personal'),
                                    fact('responsibilities', text, 'Built and tested the pipeline'),
                                    *[fact('skill_use', text, 'Wrote the pipeline', skill_name=n, attribution='personal') for n in names],
                                    *[fact('self_rating',text,'5',skill_name=n) for n in names]],
                'resolved_uncertainties': ['personal_contribution'], 'remaining_uncertainties': []}]}

    provider.evaluation = complete
    # The planner would keep asking about assistance; the backend ends the topic first.
    provider.plans = [{'action': 'ask', 'item_id': first, 'reply': 'Did anyone help?', 'targets': [{'field': 'assistance', 'skill_name': 'Python'}]},
                      {'action': 'ask', 'item_id': second, 'reply': 'What did you personally analyse?', 'targets': [{'field': 'personal_contribution'}]}]
    chat = send(client, chat, 'I personally built the Python and SQL pipeline and wrote its tests. I rate both skills 5/10.')
    assert topic_status(chat, first) == 'reviewed'
    assert chat['active_question']['item_id'] == second
    raw = app.state.conversations.cv.get('owner-a', cv['id'])
    assert len([q for q in raw['clarifications'] if q['item_id'] == first]) == 1
    plan = [c for c in provider.calls if c['task'] == 'cv_interview_plan'][-1]
    assert plan['just_completed_topics'] == ['Team application']
    assert next(s for s in plan['sources'] if s['id'] == first)['enough_context'] is True


def test_question_carries_its_number_answer_hints_and_reason(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']
    assert (first['number'], first['limit']) == (1, 3)
    provider.evaluation = evaluate
    provider.plans = [{'action': 'ask', 'item_id': first['item_id'], 'reply': 'What was the scope of your API work?',
                       'targets': [{'field': 'task_scope'}],
                       'answer_hints': ['What you built or decided', 'Tools or methods you used'],
                       'reason': 'It shows how much of the project you handled yourself.'}]
    chat = send(client, chat, 'I built the Python API with guidance.')
    question = chat['active_question']
    assert (question['number'], question['limit']) == (2, 3)
    assert question['hints'] == ['What you built or decided', 'Tools or methods you used']
    assert question['reason'] == 'It shows how much of the project you handled yourself.'


def test_question_number_rises_with_each_answer_and_a_topic_stops_at_three(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness)
    first = chat['active_question']['item_id']
    provider.evaluation = evaluate
    numbers = [chat['active_question']['number']]
    for index in range(4):
        provider.plans = [{'action': 'ask', 'item_id': first, 'reply': f'Follow-up {index}?', 'targets': [{'field': 'task_scope'}]}]
        chat = send(client, chat, f'Answer {index} with more detail about the API.')
        question = chat['active_question']
        if not question or question['item_id'] != first: break
        numbers.append(question['number'])
    assert numbers == [1, 2, 3]
