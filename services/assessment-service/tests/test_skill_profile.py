"""Per-skill category, relevance and competence judged by the model from reviewed evidence (synthetic data)."""
import asyncio
import time
from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from elo_shared.runtime import MemoryStore, Problem
from app.domain import OutputProblem
from app.main import create_app
from app.schemas import SkillBatch
from app.skills import profile_skills, validate_skill_batch, evaluate_skills
from tests.test_assessment import H, OWNER, Interpreter, Sources, finish

EVIDENCE = {
    'cv:item1': {'kind': 'project', 'name': 'Synthetic project', 'text': 'Built an API.'},
    'cv:item1:claim:0': {'kind': 'skill', 'name': 'Python', 'text': 'I wrote the API myself.', 'attribution': 'personal',
                         'application_level': 'independent_application', 'reviewed': True, 'canonical_skill_id': 'language.python'},
    'cv:item1:claim:1': {'kind': 'skill', 'name': 'Docker', 'text': 'A teammate set up Docker.', 'attribution': 'team'},
    'declaration:d1': {'kind': 'user_declaration', 'name': 'python', 'text': 'I use Python daily.', 'attribution': 'personal',
                       'canonical_skill_id': 'language.python'},
}


def judgement(key, **values):
    return {'skill_key': key, 'category': 'Technical coding', 'relevance': 'high', 'competence_score': None,
            'required_score': 7, 'explanation': 'Synthetic explanation.', **values}


def test_profile_skills_merge_sources_by_registry_identity_and_name_where_they_were_used():
    skills = profile_skills(EVIDENCE)
    assert [skill['name'] for skill in skills] == ['Python', 'Docker']
    python = skills[0]
    assert [source['ref'] for source in python['sources']] == ['cv:item1:claim:0', 'declaration:d1']
    assert python['sources'][0]['used_in'] == 'Synthetic project' and python['sources'][1]['used_in'] == 'Added by you'
    assert python['sources'][0]['application_level'] == 'independent_application'


def test_valid_judgements_keep_category_scores_and_drop_a_goal_level_for_unneeded_skills():
    skills = profile_skills(EVIDENCE)
    output = SkillBatch(skills=[
        judgement('s1', subcategory='Languages', competence_score=6, evidence_refs=['cv:item1:claim:0'], requirement_refs=['job:req1']),
        judgement('s2', category='Cloud & DevOps', relevance='none', required_score=5)])
    python, docker = validate_skill_batch(output, skills, {'job:req1'}, EVIDENCE)
    assert python['subcategory'] == 'Languages' and python['competence_score'] == 4
    assert python['required_score'] == 5 and python['canonical_skill_id'] == 'language.python'
    assert docker['category'] == 'Cloud & DevOps' and docker['required_score'] is None and docker['evidence_refs'] == []


@pytest.mark.parametrize('values,message', [
    ({'competence_score': 5, 'evidence_refs': ['cv:item1:claim:1']}, 'personal'),
    ({'competence_score': 5, 'evidence_refs': ['cv:item1:claim:0']}, 'not among its own sources'),
    ({'requirement_refs': ['job:invented']}, 'not in goal.requirements'),
])
def test_judgements_cannot_score_team_work_or_cite_other_evidence(values, message):
    skills = profile_skills(EVIDENCE)
    output = SkillBatch(skills=[judgement('s1'), judgement('s2', **values)])
    with pytest.raises(OutputProblem) as error:
        validate_skill_batch(output, skills, {'job:req1'}, EVIDENCE)
    assert message in error.value.feedback


def test_every_skill_must_be_judged_exactly_once():
    with pytest.raises(OutputProblem) as error:
        validate_skill_batch(SkillBatch(skills=[judgement('s1')]), profile_skills(EVIDENCE), set(), EVIDENCE)
    assert "'s2'" in error.value.feedback


def test_category_must_be_a_display_category():
    with pytest.raises(ValueError):
        SkillBatch(skills=[judgement('s1', category='Wizardry')])


def test_completed_assessment_publishes_the_skill_profile():
    model = Interpreter()
    with TestClient(create_app(MemoryStore(), Sources(), model)) as client:
        client.post('/api/v1/assessments', json={'expected_version': 0, 'mutation_id': str(uuid4()), 'allow_partial': True}, headers=H)
        state = finish(client)
    profile = state['result']['skill_profile']
    assert profile['status'] == 'evaluated' and profile['rubric_version'] == 'evidence-role-v4'
    [skill]=profile['skills']
    assert skill['name']=='Python' and skill['canonical_skill_id']=='language.python'
    assert skill['competence_score']==4 and skill['required_score']==5
    assert skill['evidence_refs']==['cv:item1:claim:0'] and skill['requirement_refs']==['job:req1']
    assert 'Self-ratings do not override' in skill['explanation']
    assert model.calls == 1 and model.skill_calls == 1


@pytest.mark.parametrize('repairs', [True, False])
def test_rejected_judgements_are_repaired_once_and_never_fail_the_comparison(repairs):
    class Forging(Interpreter):
        def __init__(self):
            super().__init__()
            self.skill_contexts = []

        async def generate(self, schema, instructions, context):
            value = await super().generate(schema, instructions, context)
            if schema is SkillBatch:
                self.skill_contexts.append(context)
                if self.skill_calls == 1 or not repairs:
                    value.skills[0].evidence_refs = ['invented']
            return value

    model = Forging()
    with TestClient(create_app(MemoryStore(), Sources(), model)) as client:
        client.post('/api/v1/assessments', json={'expected_version': 0, 'mutation_id': str(uuid4()), 'allow_partial': True}, headers=H)
        state = finish(client)
    assert state['operation']['status'] == 'succeeded' and model.skill_calls == 2
    assert "'invented'" in model.skill_contexts[1]['validation_feedback']
    profile = state['result']['skill_profile']
    assert profile['status'] == ('evaluated' if repairs else 'failed')
    assert len(profile['skills']) == (1 if repairs else 0)
    assert len(state['result']['job_skill_gaps']) == 1


def test_provider_failure_while_judging_resumes_without_repeating_requirement_comparisons(monkeypatch):
    class Busy(Interpreter):
        async def generate(self, schema, instructions, context):
            if schema is SkillBatch and not self.skill_calls:
                self.skill_calls += 1
                raise Problem('Provider capacity.', 429, 'model_quota', 30)
            return await super().generate(schema, instructions, context)

    model = Busy();store = MemoryStore()
    with TestClient(create_app(store, Sources(), model)) as client:
        body = {'expected_version': 0, 'mutation_id': str(uuid4()), 'allow_partial': True}
        client.post('/api/v1/assessments', json=body, headers=H);state = finish(client)
        assert state['operation']['status'] == 'failed' and model.calls == 1
        future = time.time() + 31
        monkeypatch.setattr('elo_shared.runtime.time.time', lambda: future)
        client.post('/api/v1/assessments', json=body, headers=H);state = finish(client)
    assert state['operation']['status'] == 'succeeded' and model.calls == 1 and model.skill_calls == 2
    assert state['result']['skill_profile']['status'] == 'evaluated'


def test_large_profiles_are_judged_in_bounded_batches_and_checkpointed():
    evidence = {f'declaration:{i}': {'kind': 'user_declaration', 'name': f'Synthetic skill {i}', 'text': 'Used it.', 'attribution': 'personal'} for i in range(20)}
    snapshot = {'evidence': evidence, 'goal': {'role': 'Developer', 'target_type': 'career_exploration'}, 'requirements': []}
    model = Interpreter();done = [];saves = []

    async def save():
        saves.append(len(done))

    profile = asyncio.run(evaluate_skills(model, snapshot, [], done, save))
    assert model.skill_calls == 2 and saves == [1, 2] and len(profile['skills']) == 20
    assert profile['status'] == 'evaluated'


def test_a_profile_without_skills_is_empty_without_a_model_call():
    model = Interpreter()
    profile = asyncio.run(evaluate_skills(model, {'evidence': {}, 'goal': {}, 'requirements': []}, [], [], None))
    assert profile == {'status': 'empty', 'rubric_version': 'evidence-role-v4', 'skills': []} and model.skill_calls == 0


def test_ambiguous_project_has_a_provisional_baseline_even_if_model_leaves_it_unknown():
    evidence={'cv:p:claim:0':{'kind':'skill','name':'Python','source_kind':'project',
        'attribution':'unknown','text':'A Python team project.'}}
    output=SkillBatch(skills=[judgement('s1',competence_score=None,evidence_refs=[])])
    [skill]=validate_skill_batch(output,profile_skills(evidence),set(),evidence)
    assert skill['competence_score']==3
    assert skill['evidence_refs']==['cv:p:claim:0']
    assert 'Provisional' in skill['explanation'] and 'not verified capability' in skill['explanation']


@pytest.mark.parametrize('reviewed,score', [(True, 5), (False, None)])
def test_skipped_topics_take_the_models_capped_score_only_after_the_review(reviewed, score):
    evidence = {'cv:s:claim:0': {'kind': 'skill', 'name': 'SQL', 'source_kind': 'skills', 'attribution': 'unknown',
                                 'text': 'SQL', 'reviewed': reviewed}}
    output = SkillBatch(skills=[judgement('s1', competence_score=6, evidence_refs=['cv:s:claim:0'])])
    if score is None:
        with pytest.raises(OutputProblem) as error:
            validate_skill_batch(output, profile_skills(evidence), set(), evidence)
        assert error.value.detail == 'Finish your CV review so elo can rate your competence.'
        return
    [skill] = validate_skill_batch(output, profile_skills(evidence), set(), evidence)
    assert skill['competence_score'] == score and skill['evidence_refs'] == ['cv:s:claim:0']
    assert 'rough estimate' in skill['explanation']


def test_reviewed_cv_level_is_reused_even_when_goal_model_omits_it():
    import copy
    evidence=copy.deepcopy(EVIDENCE)
    record=evidence['cv:item1:claim:0']
    record.update(cv_level=3,source_kind='project')
    skills=profile_skills(evidence)
    output=SkillBatch(skills=[judgement('s1',competence_score=None,requirement_refs=['job:req1']),judgement('s2',relevance='none')])
    python,_=validate_skill_batch(output,skills,{'job:req1'},evidence)
    assert python['competence_score']==3 and python['required_score']==5
    assert 'cv:item1:claim:0' in python['evidence_refs']
    # An unreviewed or team-only source cannot lend an established level.
    record['reviewed']=False
    output.skills[0].competence_score=None
    python,_=validate_skill_batch(output,profile_skills(evidence),{'job:req1'},evidence)
    assert python['competence_score'] is None
