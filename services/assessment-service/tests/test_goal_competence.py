"""Goal-skill competence from the model, its Skills Profile link and the explicit evaluation (synthetic data)."""
import time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Problem
from app.domain import OutputProblem, validate_batch
from app.main import create_app
from app.schemas import Batch
from app.skills import link_profile
from tests.test_assessment import H, Interpreter, Sources

REQUIREMENT = {'ref': 'job:req1', 'kind': 'job_skill', 'name': 'Python', 'priority': 'required'}
EVIDENCE = {'cv:item1:claim:0': {'text': 'I wrote the API myself.', 'attribution': 'personal'},
            'cv:item1:claim:1': {'text': 'The team used Python.', 'attribution': 'team'}}


def batch(refs, **levels):
    return Batch(outcomes=[{'requirement_ref': 'job:req1', 'mapping_method': 'semantic', 'mapping_reason': 'Related.',
        'components': [{'dimension': 'capability', 'status': 'uncertain', 'explanation': 'Synthetic.', 'evidence_refs': refs}], **levels}])


def test_model_levels_become_a_rubric_v1_ratio():
    [outcome] = validate_batch(batch(['cv:item1:claim:0'], demonstrated_level=6, required_level=8, score_explanation='You built an API alone.'), [REQUIREMENT], EVIDENCE)
    assert (outcome['competence_score'], outcome['demonstrated_score'], outcome['required_score']) == (8, 6, 8)
    assert outcome['scoring_rubric_version'] == 'llm-ratio-v1' and outcome['score_explanation'] == 'You built an API alone.'
    assert outcome['relevance'] == 'high' and outcome['score_status'] == 'estimated'
    [capped] = validate_batch(batch(['cv:item1:claim:0'], demonstrated_level=9, required_level=6), [REQUIREMENT], EVIDENCE)
    assert capped['competence_score'] == 10


def test_a_demonstrated_level_needs_cited_personal_evidence():
    with pytest.raises(OutputProblem) as error:
        validate_batch(batch(['cv:item1:claim:1'], demonstrated_level=6, required_level=8), [REQUIREMENT], EVIDENCE)
    assert 'demonstrated_level' in error.value.feedback


def test_only_a_required_level_leaves_the_score_unknown():
    [outcome] = validate_batch(batch([], required_level=8), [REQUIREMENT], EVIDENCE)
    assert outcome['competence_score'] is None and outcome['scoring_rubric_version'] == 'application-ratio-v1'


def test_levels_are_ignored_outside_job_skills():
    [outcome] = validate_batch(batch(['cv:item1:claim:0'], demonstrated_level=6, required_level=8),
                               [{**REQUIREMENT, 'kind': 'interview_preparation', 'priority': 'suggested'}], EVIDENCE)
    assert outcome['competence_score'] is None


def test_goal_skills_link_to_profile_skills_and_borrow_their_estimate_only_when_unscored():
    profile = {'skills': [
        {'name': 'pytest', 'canonical_skill_id': None, 'category': 'Technical coding', 'competence_score': 4, 'required_score': 8,
         'explanation': 'You wrote unit tests.', 'requirement_refs': ['job:testing']},
        {'name': 'Python', 'canonical_skill_id': 'language.python', 'category': 'Technical coding', 'competence_score': 7, 'required_score': 8,
         'explanation': 'Built an API.', 'requirement_refs': ['job:python']}]}
    outcomes = [{'ref': 'job:testing', 'kind': 'job_skill', 'competence_score': None, 'required_score': None},
                {'ref': 'job:python', 'kind': 'job_skill', 'competence_score': 9, 'required_score': 8, 'scoring_rubric_version': 'llm-ratio-v1'},
                {'ref': 'job:docker', 'kind': 'job_skill', 'competence_score': None, 'required_score': None},
                {'ref': 'interview:1', 'kind': 'interview_preparation'}]
    testing, python, docker, interview = link_profile(outcomes, profile)
    assert [s['name'] for s in testing['profile_skills']] == ['pytest'] and testing['competence_score'] == 5
    assert testing['scoring_rubric_version'] == 'profile-link-v1' and 'pytest' in testing['score_explanation']
    assert python['competence_score'] == 9 and python['scoring_rubric_version'] == 'llm-ratio-v1'
    assert python['profile_skills'][0]['name'] == 'Python'
    assert docker['profile_skills'] == [] and docker['competence_score'] is None
    assert 'profile_skills' not in interview


class Reviewed(Sources):
    """A selected CV whose review covers its current evidence."""
    def __init__(self, reviewed=True, research=None):
        super().__init__();self.reviewed = reviewed;self.research = research

    async def read(self, service, path, token, params=None):
        value = await super().read(service, path, token, params)
        if service == 'career':
            return {**value, 'research': self.research}
        if path == '/api/v1/cv/cv1':
            return {**value, 'effective_version': 1, 'profile_reviewed_effective_version': 1 if self.reviewed else None}
        return value


def settle(client):
    for _ in range(100):
        state = client.get('/api/v1/assessments/current', headers=H).json()
        if not state['operation'] or state['operation']['status'] in ('succeeded', 'failed'):
            return state
        time.sleep(.01)
    raise AssertionError('operation did not settle')


def evaluate(client):
    """The explicit command behind "Evaluate skills with career goal"."""
    version = client.get('/api/v1/assessments/current', headers=H).json()['version']
    response = client.post('/api/v1/assessments', headers=H, json={'expected_version': version, 'mutation_id': str(uuid4()), 'allow_partial': True})
    assert response.status_code == 202, response.text
    return settle(client)


def test_reading_a_set_goal_and_reviewed_profile_never_starts_an_evaluation():
    model = Interpreter()
    with TestClient(create_app(MemoryStore(), Reviewed(), model)) as client:
        state = settle(client)
        assert client.get('/api/v1/assessments/context', headers=H).json()['ready'] is True
        settle(client)
    assert state['operation'] is None and state['result'] is None
    assert model.calls == 0 and model.skill_calls == 0


def test_the_explicit_command_evaluates_once_and_links_profile_skills():
    model = Interpreter()
    with TestClient(create_app(MemoryStore(), Reviewed(), model)) as client:
        state = evaluate(client)
        assert state['operation']['status'] == 'succeeded' and state['stale'] is False
        assert state['result']['skill_profile']['status'] == 'evaluated'
        assert state['result']['job_skill_gaps'][0]['profile_skills'][0]['name'] == 'Python'
        settle(client);settle(client)
    assert model.calls == 1 and model.skill_calls == 1


@pytest.mark.parametrize('sources,reviewed,pending', [
    (Reviewed(), True, False), (Reviewed(reviewed=False), False, False),
    (Reviewed(research={'_id': 'r1', 'version': 1, 'research_status': 'processing'}), True, True)])
def test_context_reports_the_setup_state_for_the_evaluate_banner(sources, reviewed, pending):
    with TestClient(create_app(MemoryStore(), sources, Interpreter())) as client:
        context = client.get('/api/v1/assessments/context', headers=H).json()
    assert (context['ready'], context['cv_reviewed'], context['research_pending']) == (True, reviewed, pending)


def test_context_leaves_setup_state_unknown_until_both_sources_exist():
    class NoGoal(Reviewed):
        async def read(self, service, path, token, params=None):
            return {'ready': False, 'reason': 'Set a Career goal first.'} if service == 'career' else await super().read(service, path, token, params)

    with TestClient(create_app(MemoryStore(), NoGoal(), Interpreter())) as client:
        context = client.get('/api/v1/assessments/context', headers=H).json()
    assert context['ready'] is False and context['cv_reviewed'] is None and context['research_pending'] is None
    assert [(issue['source'], issue['href']) for issue in context['issues']] == [('career', '/career-goal')]


def test_changed_inputs_mark_the_result_stale_until_evaluated_again():
    sources = Reviewed();model = Interpreter()
    with TestClient(create_app(MemoryStore(), sources, model)) as client:
        first = evaluate(client)['result']['id']
        sources.goal = {**sources.goal, 'version': 2}
        changed = settle(client)
        assert changed['stale'] is True and changed['result']['id'] == first and model.calls == 1
        second = evaluate(client)
    assert second['result']['id'] != first and second['stale'] is False and model.calls == 2


def test_dashboard_reads_never_start_a_comparison():
    model = Interpreter()
    with TestClient(create_app(MemoryStore(), Reviewed(), model)) as client:
        assert client.get('/api/v1/assessments/dashboard-source', headers=H).json()['freshness'] == 'missing'
    assert model.calls == 0
