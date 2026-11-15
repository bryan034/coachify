"""Regression coverage for question publication and group navigation."""
from copy import deepcopy

from tests.test_cv_interview import opened, start, start_two_topics, evaluate
from tests.test_conversation_security import send


def test_irrelevant_classification_of_a_side_question_does_not_skip(harness):
    client, app, *_ = harness
    cv, chat, provider = start(harness)
    original = deepcopy(chat['active_question'])
    provider.evaluation = {'topic_relevant': False, 'intent': 'side_question', 'reply': 'Off topic.', 'actions': []}
    for _ in range(2):
        chat = send(client, chat, 'Why are you asking this question?')
        assert chat['active_question'] == original
        assert 'clarify what you personally did' in chat['messages'][-1]['text']
    document = app.state.conversations.cv.get('owner-a', cv['id'])
    assert len(document['clarifications']) == 1
    assert document['clarifications'][0]['status'] == 'unanswered'


def test_pause_cannot_publish_an_unaccounted_question(harness):
    client, app, *_ = harness
    cv, chat, provider = opened(harness)
    provider.plans = [{'action': 'pause', 'reply': 'What else did you build?'}]
    chat = send(client, chat, 'Review my CV', command='review')
    assert chat['interview']['status'] == 'paused'
    assert 'What else did you build?' not in chat['messages'][-1]['text']
    assert not app.state.conversations.cv.get('owner-a', cv['id'])['clarifications']


def test_free_section_can_finish_after_one_informative_answer(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness, scope='section')
    provider.evaluation = evaluate
    provider.plans = [{'action': 'finish', 'reply': 'Your review is complete.'}]
    chat = send(client, chat, 'I built the Python API with guidance.')
    assert chat['interview']['status'] == 'reviewed_with_gaps'
    assert chat['active_question'] is None
    assert chat['interview']['reviewed_items'] == chat['interview']['total_items'] == 2
    assert len(app.state.conversations.cv.get('owner-a', cv['id'])['clarifications']) == 1


def test_invalid_answers_defer_the_entire_free_section(harness):
    client, app, *_ = harness
    cv, chat, provider = start_two_topics(harness, scope='section')
    original = deepcopy(chat['active_question'])
    provider.evaluation = {'intent': 'invalid', 'reply': 'Malformed'}
    chat = send(client, chat, 'First unstructured answer.')
    chat = send(client, chat, 'Second unstructured answer.')
    assert chat['active_question'] is None
    assert chat['interview']['status'] == 'reviewed_with_gaps'
    document = app.state.conversations.cv.get('owner-a', cv['id'])
    assert len(document['clarifications']) == 1
    assert document['clarifications'][0]['id'] == original['id']
    assert document['clarifications'][0]['status'] == 'skipped'


def test_multiple_questions_and_injected_hints_are_not_published(harness):
    client, _, *_ = harness
    _, chat, provider = opened(harness)
    provider.plans = [
        lambda context: {'action': 'ask', 'reply': 'What did you build? Why did you choose it?',
                         'item_id': context['focused_source']['id'], 'targets': [{'field': 'personal_contribution'}]},
        lambda context: {'action': 'ask', 'reply': 'What did you build?',
                         'item_id': context['focused_source']['id'], 'targets': [{'field': 'personal_contribution'}],
                         'answer_hints': ['What else did you do?'], 'reason': 'What else can you tell me?'},
    ]
    chat = send(client, chat, 'Review my CV', command='review')
    active = chat['active_question']
    assert active['question'] == 'What did you build?'
    assert active['hints'] == ['Your own actions', 'Relevant decisions or constraints']
    assert active['reason'] == 'This helps clarify your experience.'
    assert 'Why did you choose it?' not in chat['messages'][-1]['text']


def test_exhausted_topic_reopen_does_not_mutate_cv(harness, monkeypatch):
    from app.conversation import interview
    client, app, *_ = harness
    cv, chat, _ = start_two_topics(harness)
    first = chat['active_question']['item_id']
    chat = send(client, chat, 'Skip this topic.', command='skip_topic', item_id=first)
    service = app.state.conversations.cv
    before = deepcopy(service.get('owner-a', cv['id']))
    monkeypatch.setattr(interview, 'question_options', lambda item, memory: [{'open_fields': []}])
    def must_not_reopen(*args, **kwargs):
        raise AssertionError('An exhausted topic cannot mutate CV state before rejecting the reopen.')
    monkeypatch.setattr(service, 'reopen_topic_skips', must_not_reopen)
    chat = send(client, chat, 'Review this topic.', command='review_topic', item_id=first)
    assert any('no questions left' in (a.get('error') or '') for a in chat['messages'][-1]['actions'])
    after = service.get('owner-a', cv['id'])
    assert after['version'] == before['version']
    assert after.get('profile_reviewed_effective_version') == before.get('profile_reviewed_effective_version')
