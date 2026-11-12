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


def test_model_levels_cannot_inflate_the_evidence_or_lower_the_role_target():
    [outcome] = validate_batch(batch(['cv:item1:claim:0'], demonstrated_level=10, required_level=2), [REQUIREMENT], EVIDENCE)
    assert (outcome['competence_score'], outcome['demonstrated_score'], outcome['required_score']) == (6, 3, 5)
    assert outcome['scoring_rubric_version'] == 'evidence-role-v4'
    assert outcome['relevance'] == 'high' and outcome['score_status'] == 'estimated'


def test_a_demonstrated_level_without_personal_evidence_stays_unrated():
    [outcome] = validate_batch(batch(['cv:item1:claim:1'], demonstrated_level=6, required_level=8), [REQUIREMENT], EVIDENCE)
    assert outcome['demonstrated_score'] is None and outcome['competence_score'] is None


def test_only_a_required_level_leaves_the_score_unknown():
    [outcome] = validate_batch(batch([], required_level=8), [REQUIREMENT], EVIDENCE)
    assert outcome['competence_score'] is None and outcome['scoring_rubric_version'] == 'evidence-role-v4'


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
    assert testing['scoring_rubric_version'] == 'evidence-role-v4' and 'pytest' in testing['score_explanation']
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


SKIPPED = {'cv:item2': {'kind': 'skills', 'text': 'Skills: SQL', 'attribution': 'unknown', 'unscoped_item': True, 'reviewed': True},
           'cv:item2:claim:0': {'kind': 'skill', 'name': 'SQL', 'text': 'SQL', 'attribution': 'unknown', 'source_kind': 'skills', 'reviewed': True}}


def test_a_finished_review_with_skipped_topics_keeps_the_models_capped_level():
    [outcome] = validate_batch(batch(['cv:item2:claim:0'], demonstrated_level=7, required_level=8), [REQUIREMENT], SKIPPED)
    assert (outcome['demonstrated_score'], outcome['required_score']) == (5, 5)
    assert outcome['score_status'] == 'estimated' and outcome['score_confidence'] == 'low'
    assert 'rough estimate' in outcome['score_explanation']


def test_an_unfinished_review_leaves_the_level_unrated_without_failing():
    evidence = {ref: {**record, 'reviewed': False} for ref, record in SKIPPED.items()}
    [outcome] = validate_batch(batch(['cv:item2:claim:0'], demonstrated_level=6, required_level=8), [REQUIREMENT], evidence)
    assert outcome['demonstrated_score'] is None and outcome['score_status'] == 'insufficient_evidence'


def test_team_only_work_stays_unrated_even_after_review():
    evidence = {'cv:item1:claim:1': {**EVIDENCE['cv:item1:claim:1'], 'reviewed': True}}
    [outcome] = validate_batch(batch(['cv:item1:claim:1'], demonstrated_level=6, required_level=8), [REQUIREMENT], evidence)
    assert outcome['demonstrated_score'] is None


def test_a_dimension_the_model_left_out_is_recorded_as_not_judged():
    from app.domain import validate_batch
    from app.schemas import Batch
    output=Batch(outcomes=[{'requirement_ref':'job:1','components':[{'dimension':'capability','status':'uncertain','explanation':'No relevant evidence.','evidence_refs':[]}],
        'recommendation':None,'mapping_method':'unresolved','mapping_reason':'Synthetic.'}])
    requirement={'ref':'job:1','kind':'job_skill','name':'Synthetic skill','required_proficiency':'intermediate','required_experience_months':24}
    result=validate_batch(output,[requirement],{})
    added={c['dimension']:c for c in result[0]['components']}
    assert set(added)=={'capability','proficiency','duration'}
    assert added['proficiency']['status']==added['duration']['status']=='uncertain' and not added['duration']['evidence_refs']
    assert result[0]['match_status']=='uncertain'


def test_repair_feedback_names_the_failing_requirement():
    import pytest
    from app.domain import OutputProblem, validate_batch
    from app.schemas import Batch
    output=Batch(outcomes=[{'requirement_ref':'job:1','components':[{'dimension':'capability','status':'supported','explanation':'Claimed.','evidence_refs':[]}],
        'recommendation':None,'mapping_method':'semantic','mapping_reason':'Synthetic.'}])
    with pytest.raises(OutputProblem) as error:validate_batch(output,[{'ref':'job:1','kind':'job_skill'}],{})
    assert "'job:1'" in error.value.feedback and 'capability' in error.value.feedback


def test_assessment_never_rates_above_the_cv_reviews_own_level():
    from app.competence import evidence_level, reviewed_estimate, role_level
    record = {'attribution': 'personal', 'assistance': 'independent', 'source_kind': 'project', 'reviewed': True,
              'review_facts': [{'field': 'outcome', 'status': 'supported', 'value': 'delivered and deployed'}]}
    assert evidence_level([record]) == 5
    # The CV review, on the same 1-10 scale, judged this skill lower: the lower level stands.
    assert evidence_level([{**record, 'cv_level': 3}]) == 3
    assert evidence_level([{**record, 'cv_level': 8}]) == 5
    # Team-only sources cannot lend their CV level.
    assert evidence_level([record, {'attribution': 'team', 'cv_level': 1}]) == 5
    unclear = {'attribution': 'unknown', 'reviewed': True, 'cv_level': 2}
    assert reviewed_estimate([unclear], 5) == 2
    # Without a Career target the role is assumed to need independent work, or complex work when stated advanced.
    assert role_level({}) == 5 and role_level({'required_proficiency': 'advanced'}) == 7
    assert role_level({'competence_target': {'level': 3}}) == 3


def test_cv_skill_level_reaches_the_evidence_record():
    import asyncio
    from app.inputs import capture
    from tests.test_assessment import Sources
    sources = Sources()
    claim = {'name': 'Python', 'attribution': 'personal', 'assistance': 'unknown', 'proficiency': None, 'experience_months': None,
             'support_uncertain': False, 'evidence_type': 'explicit', 'evidence': []}
    sources.source['items'] = [{'id': 'item1', 'kind': 'project', 'title': 'Project', 'description': 'Used Python.', 'provenance': 'explicit',
        'evidence': [], 'removed': False, 'skill_claims': [
            {**claim, 'skill_level': {'level': 3, 'status': 'rated', 'rationale': 'Guided use.', 'source': 'review', 'evidence': []}},
            {**claim, 'name': 'SQL', 'skill_level': {'level': None, 'status': 'uncertain', 'rationale': 'Conflict.', 'source': 'review', 'evidence': []}},
            {**claim, 'name': 'Go'}]}]
    evidence = asyncio.run(capture(sources, asyncio.run(sources.account('synthetic'))))['evidence']
    assert [evidence[f'cv:item1:claim:{i}']['cv_level'] for i in range(3)] == [3, None, None]
