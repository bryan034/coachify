"""Harness decisions and durable evidence use synthetic providers on both repositories."""
from copy import deepcopy
from uuid import uuid4
import pytest
from app.conversation.interview import build_context, reconcile_memory, validate_decision
from app.domain.capabilities import effective_items, validate_extraction, evidence_requiring_semantic_check
from app.schemas.interview import InterviewTurn
from tests.conftest import ready, mutation
from tests.test_conversation_security import PREFIX, send
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


def test_failed_semantic_support_keeps_literal_answer_and_prevents_next_question(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    provider.evaluation, provider.approve = evaluate, False
    chat = send(client, chat, 'I built the Python API with guidance.')
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert any(q['answer'] == 'I built the Python API with guidance.' and q['interpretation_status'] == 'failed' for q in saved['clarifications'])
    assert not any(i['review_evidence'] for i in saved['items'])
    assert len([c for c in provider.calls if c['task'] == 'cv_interview_plan']) == 1
    failures = [a for m in chat['messages'] for a in m['actions'] if a['status'] == 'failed']
    assert len(failures) == 1 and failures[0]['kind'] == 'clarify'
    assert chat['messages'][-1]['actions'][0]['status'] == 'saved'


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
    with pytest.raises(ValueError, match='personal ownership'):
        validate_decision({'action': 'finish', 'reply': 'All done.', 'coverage': [{'item_id': source, 'status': 'reviewed', 'evidence_refs': ['team', 'task']}]}, context, memory)
    memory['questions'][0]['answer_status'] = 'answered'
    decision, _ = validate_decision({'action': 'finish', 'reply': 'We reviewed this with ownership still uncertain.',
        'coverage': [{'item_id': source, 'status': 'reviewed_with_gaps', 'evidence_refs': ['team']}]}, context, memory)
    assert decision.action == 'finish'


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
    assert any(a['answer'] == 'I personally built the data importer.' for a in context['source_answers'])
    assert len(context['recent_messages']) == 10


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
    output, metadata = ConversationRouter().route({'task': task, 'message': 'Synthetic question'})
    assert output.reply == result['reply']
    assert metadata['prompt_version'] == 'cv-interview-1'
    assert len(requests) == 1 and requests[0]['max_tokens'] == 5000
    assert 'untrusted' in requests[0]['messages'][0]['content'].lower()
    assert 'synthetic-secret-for-test' not in json.dumps(requests[0]['messages'])


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
