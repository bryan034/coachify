"""End-to-end synthetic interview fixture regression for saved follow-ups."""
import importlib.util
from pathlib import Path
from uuid import uuid4

from app.clients.conversation import interview_model_context
from tests.conftest import TEXT, ready
from tests.test_conversation_security import PREFIX, send
from tests.test_conversation import actions, decide

spec = importlib.util.spec_from_file_location('cv_model_resume_fixture',
    Path(__file__).resolve().parents[3] / 'infrastructure/testing/cv-model.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class FixtureProvider:
    configured = True

    def route(self, context):
        result = (fixture.interview_fixture(interview_model_context(context)) if context.get('task') in {'cv_interview_interpret', 'cv_interview_plan'}
                  else fixture.conversation_fixture(context))
        return result, {'provider': 'synthetic-test', 'model': 'fixture',
            'prompt_version': '1', 'schema_version': '1'}

    def verify_evidence(self, blocks, refs, **_):
        return frozenset((r['block_id'], r['excerpt']) for r in refs)


def test_mixed_answer_keeps_a_valid_followup_and_resumes_it(harness):
    client, app, extractor, *_ = harness
    extractor.payload = {'items': [
        {'kind': 'project', 'title': 'Team dashboard', 'description': TEXT[1], 'explicit': True,
         'evidence': [{'block_id': 'b2', 'excerpt': TEXT[1]}], 'skill_names': ['Python', 'SQL'],
         'uncertainties': ['personal_contribution']},
    ]}
    cv = ready(harness)
    provider = app.state.conversations.provider = FixtureProvider()
    app.state.interpreter.verify_evidence = provider.verify_evidence
    response = client.post(PREFIX, json={'cv_id': cv['id'], 'purpose': 'skills_profile', 'mutation_id': str(uuid4())})
    assert response.status_code == 200, response.text
    chat = send(client, response.json(), 'Review my CV', command='review')
    first = chat['active_question']
    assert first, chat['messages'][-1]
    chat = send(client, chat, fixture.CHAT_MIXED_ANSWER)
    assert chat['active_question'], chat['messages'][-1]
    assert chat['active_question']['id'] != first['id']
    detail = client.get('/api/v1/cv/' + cv['id']).json()
    assert sum(q['answer'] == fixture.CHAT_MIXED_ANSWER for q in detail['clarifications']) == 1
    resumed = client.post(PREFIX, json={'cv_id': cv['id'], 'purpose': 'skills_profile', 'mutation_id': str(uuid4())})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()['active_question'] == chat['active_question']


def test_complete_chat_fixture_journey_preserves_evidence_and_question_budget(harness):
    client, app, extractor, *_ = harness
    extractor.payload = {'items': [
        {'kind': 'project', 'title': 'Team dashboard', 'description': TEXT[1], 'explicit': True,
         'evidence': [{'block_id': 'b2', 'excerpt': TEXT[1]}], 'skill_names': ['Python', 'SQL'],
         'uncertainties': ['personal_contribution']},
        {'kind': 'experience', 'title': 'Synthetic reporting internship', 'description': TEXT[2], 'explicit': True,
         'evidence': [{'block_id': 'b3', 'excerpt': TEXT[2]}], 'skill_names': ['SQL'],
         'uncertainties': ['responsibility']},
    ]}
    cv = ready(harness)
    provider = app.state.conversations.provider = FixtureProvider()
    app.state.interpreter.verify_evidence = provider.verify_evidence
    chat = client.post(PREFIX, json={'cv_id': cv['id'], 'purpose': 'skills_profile', 'mutation_id': str(uuid4())}).json()
    chat = send(client, chat, 'Review my CV', command='review')
    first = chat['active_question']; assert first
    chat = send(client, chat, fixture.CHAT_MIXED_ANSWER)
    assert chat['active_question'] and chat['active_question']['id'] != first['id']
    detail = lambda: client.get('/api/v1/cv/' + cv['id']).json()
    def months(name):
        skill = next((skill for skill in detail()['skills'] if skill['skill_id'] == 'skill:' + name), None)
        return skill.get('experience_months') if skill else None
    assert months('python') == 6
    before = detail()
    chat = send(client, chat, 'Why are you asking?')
    assert detail() == before
    assert 'It does not establish whether you used the skill elsewhere.' in chat['messages'][-1]['text']
    chat = send(client, chat, 'What if I had six months of SQL experience?')
    assert detail() == before
    chat = send(client, chat, fixture.CHAT_EXTRA_CONTEXT)
    assert months('python') == 6 and months('power bi') == 2
    assert any(question['answer'] == fixture.CHAT_MIXED_ANSWER for question in detail()['clarifications'])
    chat = send(client, chat, fixture.CHAT_CORRECTION)
    action = actions(chat, 'correct')[-1]
    assert action['status'] == 'awaiting_confirmation' and months('python') == 6
    chat = decide(client, chat, action, decision='cancel')
    assert months('python') == 6
    chat = send(client, chat, fixture.CHAT_CORRECTION)
    action = actions(chat, 'correct')[-1]
    assert action['status'] == 'awaiting_confirmation'
    chat = decide(client, chat, action, decision='save')
    assert months('python') == 3 and months('power bi') == 2
    before = chat
    resumed = client.post(PREFIX, json={'cv_id': cv['id'], 'purpose': 'skills_profile', 'mutation_id': str(uuid4())})
    assert resumed.status_code == 200, resumed.text
    chat = resumed.json()
    assert chat['id'] == before['id'] and chat['messages'] == before['messages']
    assert chat['active_question'], chat['messages'][-1]
    skipped = chat['active_question']['id']; before = detail()
    chat = send(client, chat, 'Skip', command='skip')
    after = detail()
    assert next(question for question in after['clarifications'] if question['id'] == skipped)['status'] == 'skipped'
    assert after['effective_version'] == before['effective_version']
