import asyncio
from uuid import uuid4
from app.conversation.actions import apply_requested_purpose
from app.conversation.presentation import review_reply
from app.conversation.service import public_action, view
from app.domain.error_codes import CodedError, error_code_of
from app.domain.service import now

ID = '0f25f85e-16bb-5c18-b832-ee8f1bf2451b'


def action(**fields):
    return {'id': 'a1', 'kind': 'route', 'status': 'failed', 'title': 'Message', 'summary': 'Saved.', 'changes': [], 'choices': [],
            '_lease_until': now() + 60, **fields}


def test_failed_actions_expose_a_code_including_legacy_saved_failures():
    assert public_action(action(error='Saved.', error_code='no_valid_next_step'))['error_code'] == 'no_valid_next_step'
    legacy = action(error='The interview could not choose a valid next step. It could not settle. Your answers are saved.')
    assert public_action(legacy)['error_code'] == 'no_valid_next_step'
    assert public_action(action(error='Something else went wrong.'))['error_code'] is None
    interrupted = public_action(action(status='pending', _lease_until=now() - 1))
    assert interrupted['status'] == 'failed' and interrupted['error_code'] == 'interrupted'
    assert error_code_of({'error': 'Some interpreted skill details are not supported by your answer.'}) == 'unsupported_interpretation'
    assert CodedError('no_valid_next_step', 'x').code == 'no_valid_next_step'


def test_route_failures_are_saved_with_their_code_and_marked_as_status_only(harness):
    client, app, *_ = harness
    chat = client.post('/api/v1/cv/conversations', json={'cv_id': None, 'mutation_id': str(uuid4())}).json()
    service = app.state.conversations
    token = str(uuid4())
    def pending(document):
        document['messages'][0]['actions'].append({**action(status='pending'), '_token': token})
    service.update('owner-a', chat['id'], pending)
    asyncio.run(service.fail('owner-a', chat['id'], 'a1', token, 'The interview could not choose a valid next step.', code='no_valid_next_step'))
    message = client.get('/api/v1/cv/conversations/' + chat['id']).json()['messages'][0]
    assert message['status_only'] is True
    assert message['actions'][0]['error_code'] == 'no_valid_next_step'


def test_assistant_prose_and_question_titles_hide_internal_source_ids():
    document = {'_id': 'c1', 'cv_id': None, 'revision': 1, 'purpose': None, 'messages': [
        {'id': 'm1', 'sequence': 1, 'role': 'assistant', 'text': f'Tell me about {ID} and [evidence: {"a" * 32}].', 'created_at': '2026-01-01', 'actions': []},
        {'id': 'm2', 'sequence': 2, 'role': 'user', 'text': f'My note mentions {ID}.', 'created_at': '2026-01-01', 'actions': []}],
        'active_question': {'id': 'q1', 'item_id': ID, 'title': f'Project {ID}', 'question': f'What did you do in {ID}?'},
        'interview_progress': None}
    result = view(document)
    assert ID not in result['messages'][0]['text'] and 'evidence' not in result['messages'][0]['text']
    assert result['messages'][1]['text'] == f'My note mentions {ID}.'
    assert ID not in result['active_question']['title'] and ID not in result['active_question']['question']


def test_a_purpose_requested_while_actions_are_outstanding_applies_once_they_settle(harness):
    client, app, *_ = harness
    chat = client.post('/api/v1/cv/conversations', json={'cv_id': None, 'mutation_id': str(uuid4())}).json()
    service = app.state.conversations
    service.update('owner-a', chat['id'], lambda d: d['messages'][0]['actions'].append(action(kind='correct', status='awaiting_confirmation')))
    response = client.post('/api/v1/cv/conversations', json={'cv_id': None, 'mutation_id': str(uuid4()), 'purpose': 'skills_profile'})
    assert response.status_code == 200, response.text
    opened = response.json()
    assert opened['id'] == chat['id'] and opened['purpose'] is None
    def settle(document):
        document['messages'][0]['actions'][-1]['status'] = 'cancelled'
    service.update('owner-a', chat['id'], settle)
    assert service.get('owner-a', chat['id'])['purpose'] == 'skills_profile'
    document = {'purpose': None, 'requested_purpose': 'skills_profile', 'messages': []}
    apply_requested_purpose(document)
    assert document == {'purpose': 'skills_profile', 'messages': []}


def test_presentation_removes_only_internal_references():
    commit = 'a' * 40
    answer = f'answer:{ID}'
    fact = 'fact:' + 'b' * 32
    assert review_reply(f'Source {ID} used commit {commit}.', [ID]) == f'Source used commit {commit}.'
    assert review_reply(f'Your task [Evidence IDs: {fact}, {answer}] was supported.') == 'Your task was supported.'
    assert review_reply(f'What did you do? Evidence ID: {fact}') == 'What did you do?'
    assert review_reply('Your role [b1]. English (B1).') == 'Your role. English (B1).'
    assert review_reply(f'Your role (source_id: {ID}), what changed?') == 'Your role, what changed?'
