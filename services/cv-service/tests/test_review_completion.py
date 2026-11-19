import asyncio
import time
from uuid import uuid4
from app.conversation.interview import InterviewHarness
from app.domain.capabilities import skills_for
from app.domain.skill_levels import apply_skill_level_reviews
from app.schemas.cv import SkillLevelInfo
from tests.conftest import ready, mutation
from tests.test_interpretation import project_question, mixed_output, PERSONAL


BASE = {'title': 'Synthetic project', 'skill_ids': [], 'evidence': [], 'provenance': 'explicit'}


def finished_review(app, cv_id, status='reviewed'):
    app.state.repository.conversations.insert({'_id': str(uuid4()), 'user_id': 'owner-a', 'cv_id': cv_id,
        'context_key': cv_id, 'segment': 1, 'revision': 1, 'purpose': 'skills_profile', 'messages': [], 'receipts': {},
        'interview_memory': {'status': status}, 'created_at': time.time(), 'updated_at': time.time()})


def test_interpretation_that_settles_after_the_review_finished_marks_the_cv_reviewed(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    finished_review(app, cv['id'])
    app.state.interpreter.payload = mixed_output
    saved = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
    assert saved['profile_reviewed_effective_version'] == saved['effective_version']


def test_an_unfinished_review_or_failed_interpretation_leaves_the_cv_unreviewed(harness):
    client, app, *_ = harness
    cv, question, path = project_question(harness)
    finished_review(app, cv['id'], status='reviewing')
    app.state.interpreter.payload = mixed_output
    saved = client.put(path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
    assert saved['profile_reviewed_effective_version'] is None

    other, question, path = project_question(harness)
    finished_review(app, other['id'])
    def unsupported(*_):
        raise ValueError('Interpretation failed for this synthetic answer.')
    app.state.interpreter.payload = unsupported
    failed = client.put(path, json=mutation(other['version'], action='answer', answer=PERSONAL)).json()
    assert next(q for q in failed['clarifications'] if q['id'] == question['id'])['interpretation_status'] == 'failed'
    assert failed['profile_reviewed_effective_version'] is None


def test_assumed_levels_stay_labelled_and_never_outrank_a_real_rating():
    assert SkillLevelInfo(level=3, status='assumed', rationale='Assumed.', source='review', evidence=[]).status == 'assumed'
    assert SkillLevelInfo(level=None, status='assumed', rationale='Unclear.', source='review', evidence=[]).status == 'uncertain'
    claim = {'skill_id': 'skill:python', 'name': 'Python', 'attribution': 'personal', 'assistance': 'unknown', 'support_uncertain': False,
             'evidence_type': 'explicit', 'proficiency': None, 'experience_months': None, 'evidence': []}
    items = [
        {'id': 'a', 'kind': 'project', 'removed': False, **BASE, 'skill_claims': [{**claim, 'skill_level': {'level': 6, 'status': 'assumed', 'source': 'review', 'rationale': '', 'evidence': []}}]},
        {'id': 'b', 'kind': 'project', 'removed': False, **BASE, 'skill_claims': [{**claim, 'skill_level': {'level': 4, 'status': 'rated', 'source': 'review', 'rationale': '', 'evidence': []}}]},
    ]
    assert skills_for(items)[0]['skill_level']['status'] == 'rated'
    assert skills_for(items)[0]['skill_level']['level'] == 4


def test_finished_review_without_a_usable_rating_reports_assumed_levels(harness):
    client, app, *_ = harness
    cv = ready(harness)
    document = app.state.repository.get('owner-a', cv['id'])
    document['profile_reviewed_effective_version'] = document['effective_version']
    items = apply_skill_level_reviews(document, client.get('/api/v1/cv/' + cv['id']).json()['items'])
    levels = [c['skill_level'] for item in items for c in item.get('skill_claims', []) if c.get('skill_level')]
    assert levels and all(level['status'] in {'assumed', 'uncertain'} for level in levels)


def test_reading_a_finished_review_retries_ratings_once_at_a_time(harness, monkeypatch):
    client, app, *_ = harness
    cv = ready(harness)
    calls = []
    gate = asyncio.Event()
    async def rate(self, account, conversation):
        calls.append(conversation['cv_id'])
        await gate.wait()
    monkeypatch.setattr(InterviewHarness, 'rate_skill_levels', rate)
    assert client.get('/api/v1/cv/' + cv['id']).status_code == 200
    assert calls == []
    finished_review(app, cv['id'])
    client.get('/api/v1/cv/' + cv['id'])
    client.get('/api/v1/cv/' + cv['id'])
    deadline = time.time() + 2
    while not calls and time.time() < deadline: time.sleep(0.01)
    assert calls == [cv['id']]
    assert app.state.conversations.rating == {cv['id']}
