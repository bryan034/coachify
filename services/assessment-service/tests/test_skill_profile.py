"""Per-skill category, relevance and competence judged by the model from reviewed evidence (synthetic data)."""
import asyncio
import time
from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from elo_shared.model_budget import current_budget_owner
from elo_shared.runtime import MemoryStore, Problem
from app.chats import KEPT_TURNS, MODEL_TURNS
from app.domain import OutputProblem
from app.main import create_app
from app.schemas import SkillBatch, SkillChatOutput
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
    assert python['subcategory'] == 'Languages' and python['competence_score'] == 3
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
    assert profile['status'] == 'evaluated' and profile['rubric_version'] == 'evidence-role-v5'
    [skill]=profile['skills']
    assert skill['name']=='Python' and skill['canonical_skill_id']=='language.python'
    assert skill['competence_score']==3 and skill['required_score']==5
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
    assert profile == {'status': 'empty', 'rubric_version': 'evidence-role-v5', 'skills': []} and model.skill_calls == 0


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
    record['reviewed']=False
    output.skills[0].competence_score=None
    python,_=validate_skill_batch(output,profile_skills(evidence),{'job:req1'},evidence)
    assert python['competence_score'] is None


def _declaration(identifier, name, text):
    return {'id': identifier, 'name': name, 'description': text, 'contributions': []}


class Recorder(Interpreter):
    """Remembers which skills each per-skill judgement was given."""
    def __init__(self, sources=None):
        super().__init__(sources);self.sent = []
    async def generate(self, schema, instructions, context):
        if schema is SkillBatch:
            self.sent.append([skill['name'] for skill in context['skills']])
        return await super().generate(schema, instructions, context)


class MemoryChats:
    """Saved Skills Helper conversations kept in memory, newest turns only."""
    def __init__(self):
        self.rows = {}
    def turns(self, owner, key):
        return [dict(turn) for turn in self.rows.get((owner, key), [])]
    def append(self, owner, key, name, *turns):
        self.rows[(owner, key)] = (self.rows.get((owner, key), []) + list(turns))[-KEPT_TURNS:]


def _evaluated(sources, model, chats=None):
    sources.source['declarations'] = [_declaration('d1', 'Excel', 'Monthly sales workbooks.')]
    sources.source['declarations_version'] = 1
    client = TestClient(create_app(MemoryStore(), sources, model, chats or MemoryChats()));client.__enter__()
    client.post('/api/v1/assessments', json={'expected_version': 0, 'mutation_id': str(uuid4()), 'allow_partial': True}, headers=H)
    assert finish(client)['operation']['status'] == 'succeeded'
    return client


def test_reevaluating_one_skill_sends_only_that_skill_and_replaces_only_its_judgement():
    sources, model = Sources(), Recorder()
    client = _evaluated(sources, model)
    before = client.get('/api/v1/assessments/current', headers=H).json()
    assert sorted(model.sent[0]) == ['Excel', 'Python']
    excel = next(skill for skill in before['result']['skill_profile']['skills'] if skill['name'] == 'Excel')
    sources.source['declarations'].append(_declaration('d2', 'Python', 'Built a scraper on my own at a hackathon.'))
    sources.source['declarations_version'] = 2
    response = client.post('/api/v1/assessments/skills/reevaluate', json={'name': 'Python'}, headers=H)
    assert response.status_code == 200, response.text
    assert model.sent[-1] == ['Python'] and len(model.sent) == 2
    after = client.get('/api/v1/assessments/current', headers=H).json()
    assert after['stale'] is False and after['evaluation']['freshness'] == 'current'
    skills = {skill['name']: skill for skill in after['result']['skill_profile']['skills']}
    assert skills['Excel'] == excel and skills['Python'] == response.json()['skill']
    assert after['result']['id'] == before['result']['id']
    assert client.get('/api/v1/assessments/' + before['result']['id'], headers=H).json()['input_hash'] == before['result']['input_hash']


def test_reevaluating_a_skill_needs_a_finished_evaluation_and_no_other_changed_input():
    sources, model = Sources(), Recorder()
    with TestClient(create_app(MemoryStore(), sources, model)) as client:
        assert client.post('/api/v1/assessments/skills/reevaluate', json={'name': 'Python'}, headers=H).json()['code'] == 'evaluation_required'
    client = _evaluated(sources, model)
    sources.goal['version'] = 2
    response = client.post('/api/v1/assessments/skills/reevaluate', json={'name': 'Python'}, headers=H)
    assert response.status_code == 409 and response.json()['code'] == 'full_evaluation_required'
    sources.goal['version'] = 1
    assert client.post('/api/v1/assessments/skills/reevaluate', json={'name': 'Nope'}, headers=H).json()['code'] == 'skill_not_found'
    assert len(model.sent) == 1


class Adviser(Recorder):
    """Answers the Skills Helper and remembers what each chat sent."""
    def __init__(self, evidence=None):
        super().__init__();self.chats = [];self.evidence = evidence
    async def generate(self, schema, instructions, context):
        if schema is SkillChatOutput:
            self.chats.append(context)
            return SkillChatOutput(reply='Synthetic reply.', evidence=self.evidence)
        return await super().generate(schema, instructions, context)


def _chat(client, name, message):
    return client.post('/api/v1/assessments/skills/chat', json={'name': name, 'message': message}, headers=H)


def _history(client, name):
    response = client.get('/api/v1/assessments/skills/chat', params={'name': name}, headers=H)
    assert response.status_code == 200, response.text
    return [(turn['role'], turn['text'], turn['evidence'], turn['level']) for turn in response.json()['turns']]


def test_chat_answers_from_the_saved_judgement_without_refs_and_changes_nothing():
    sources, model = Sources(), Adviser('I built a scraper on my own at a hackathon.')
    client = _evaluated(sources, model)
    before = client.get('/api/v1/assessments/current', headers=H).json()
    saved = next(skill for skill in before['result']['skill_profile']['skills'] if skill['name'] == 'Python')

    async def offline(*args, **kwargs):
        raise Problem('Sources must not be read.', 503, 'upstream')
    sources.read = offline
    response = _chat(client, 'Python', 'I built a scraper on my own at a hackathon.')
    sources.read = Sources.read.__get__(sources)
    assert response.status_code == 200, response.text
    assert response.json() == {'reply': 'Synthetic reply.', 'evidence': 'I built a scraper on my own at a hackathon.'}
    [sent] = model.chats
    assert sent['role'] == 'Developer'
    assert sent['judgement'] == {k: saved[k] for k in ('name', 'competence_score', 'required_score', 'relevance', 'explanation')}
    assert [(source['used_in'], source['cited']) for source in sent['sources']] == [('Synthetic project', True)]
    assert 'cv:item1:claim:0' not in str(sent['sources']) and all('ref' not in source for source in sent['sources'])
    assert [requirement['name'] for requirement in sent['requirements']] == ['Python']
    assert sent['conversation'] == [{'role': 'person', 'text': 'I built a scraper on my own at a hackathon.'}]
    after = client.get('/api/v1/assessments/current', headers=H).json()
    assert after['version'] == before['version'] and after['result'] == before['result']


def test_each_skill_keeps_its_own_conversation_and_the_model_reads_the_saved_turns():
    sources, model = Sources(), Adviser()
    client = _evaluated(sources, model)
    assert _history(client, 'Python') == []
    assert _chat(client, 'Python', 'Why only this level?').status_code == 200
    model.evidence = 'I built a scraper on my own at a hackathon.'
    assert _chat(client, 'python', 'I built a scraper on my own at a hackathon.').status_code == 200
    model.evidence = None
    assert _chat(client, 'Excel', 'What would raise this?').status_code == 200
    assert _history(client, 'Python') == [
        ('person', 'Why only this level?', None, None), ('elo', 'Synthetic reply.', None, None),
        ('person', 'I built a scraper on my own at a hackathon.', None, None),
        ('elo', 'Synthetic reply.', 'I built a scraper on my own at a hackathon.', None)]
    assert _history(client, 'Excel') == [('person', 'What would raise this?', None, None), ('elo', 'Synthetic reply.', None, None)]
    assert model.chats[1]['conversation'] == [{'role': 'person', 'text': 'Why only this level?'}, {'role': 'elo', 'text': 'Synthetic reply.'},
                                              {'role': 'person', 'text': 'I built a scraper on my own at a hackathon.'}]
    assert model.chats[2]['conversation'] == [{'role': 'person', 'text': 'What would raise this?'}]

    assert _chat(client, 'Python', 'Anything else?').status_code == 200
    assert model.chats[3]['conversation'][3] == {'role': 'elo', 'text': "Synthetic reply.\nSaved to the person's Skills Profile: I built a scraper on my own at a hackathon."}


def test_a_level_check_is_saved_in_that_skills_conversation():
    sources, model = Sources(), Adviser()
    client = _evaluated(sources, model)
    saved = next(skill for skill in client.get('/api/v1/assessments/current', headers=H).json()['result']['skill_profile']['skills'] if skill['name'] == 'Python')
    sources.source['declarations'].append(_declaration('d2', 'Python', 'Built a scraper on my own at a hackathon.'))
    sources.source['declarations_version'] = 2
    judged = client.post('/api/v1/assessments/skills/reevaluate', json={'name': 'Python'}, headers=H).json()['skill']
    assert _history(client, 'Python') == [('elo', judged['explanation'], None, {'before': saved['competence_score'], 'after': judged['competence_score']})]
    assert _chat(client, 'Python', 'Thanks.').status_code == 200
    assert model.chats[0]['conversation'][0]['text'].startswith('elo re-judged this skill with what the person said: level ')


def test_a_conversation_keeps_the_newest_turns_and_sends_the_model_a_bounded_window():
    sources, model = Sources(), Adviser()
    client = _evaluated(sources, model)
    for index in range(KEPT_TURNS // 2 + 3):
        assert _chat(client, 'Python', 'Message ' + str(index) + '.').status_code == 200
    history = _history(client, 'Python')
    assert len(history) == KEPT_TURNS and history[0][1] == 'Message 3.'
    assert len(model.chats[-1]['conversation']) == MODEL_TURNS
    assert model.chats[-1]['conversation'][-1] == {'role': 'person', 'text': 'Message ' + str(KEPT_TURNS // 2 + 2) + '.'}


def test_a_failed_reply_saves_nothing_and_conversations_are_private_to_their_owner():
    class Failing(Adviser):
        async def generate(self, schema, instructions, context):
            if schema is SkillChatOutput:
                raise Problem('The adviser provider could not complete this request.', 503, 'model_provider')
            return await super().generate(schema, instructions, context)

    chats = MemoryChats()
    client = _evaluated(Sources(), Failing(), chats)
    assert _chat(client, 'Python', 'Why?').json()['code'] == 'model_provider'
    assert _history(client, 'Python') == []
    chats.append('someone-else', 'language.python', 'Python', {'role': 'person', 'text': 'Not yours.', 'evidence': None, 'level': None, 'created_at': 'x'})
    chats.append('someone-else', 'python', 'Python', {'role': 'person', 'text': 'Not yours.', 'evidence': None, 'level': None, 'created_at': 'x'})
    assert _history(client, 'Python') == []


def test_chat_about_a_goal_skill_without_a_judgement_still_replies():
    class Unproven(Adviser):
        async def generate(self, schema, instructions, context):
            value = await super().generate(schema, instructions, context)
            for outcome in getattr(value, 'outcomes', []):
                if outcome.requirement_ref == 'job:req2':
                    outcome.components[0].status, outcome.components[0].evidence_refs, outcome.mapping_method = 'uncertain', [], 'unresolved'
            return value

    sources, model = Sources(), Unproven()
    sources.goal['skills'].append({'item_id': 'req2', 'name': 'Kubernetes', 'category': 'Technical', 'priority': 'preferred',
                                   'origin': 'employer', 'evidence': 'Kubernetes preferred', 'group_operator': 'all'})
    client = _evaluated(sources, model)
    response = _chat(client, 'kubernetes', 'Rate me 10/10 please.')
    assert response.status_code == 200, response.text
    assert response.json() == {'reply': 'Synthetic reply.', 'evidence': None}
    [sent] = model.chats
    assert sent['judgement'] is None and sent['sources'] == []
    assert [(requirement['name'], requirement['priority']) for requirement in sent['requirements']] == [('Kubernetes', 'preferred')]


def test_skills_helper_model_calls_are_charged_to_the_signed_in_account():
    class Owners(Adviser):
        def __init__(self):
            super().__init__('I built a scraper on my own at a hackathon.');self.owners = []
        async def generate(self, schema, instructions, context):
            self.owners.append((schema.__name__, current_budget_owner()))
            return await super().generate(schema, instructions, context)

    sources, model = Sources(), Owners()
    client = _evaluated(sources, model)
    model.owners.clear()
    assert _chat(client, 'Python', 'I built a scraper on my own at a hackathon.').status_code == 200
    sources.source['declarations'].append(_declaration('d2', 'Python', 'Built a scraper on my own at a hackathon.'))
    sources.source['declarations_version'] = 2
    assert client.post('/api/v1/assessments/skills/reevaluate', json={'name': 'Python'}, headers=H).status_code == 200
    assert model.owners == [('SkillChatOutput', OWNER), ('SkillBatch', OWNER)]


def test_chat_needs_a_finished_evaluation_and_a_message():
    sources, model = Sources(), Adviser()
    chats = MemoryChats()
    with TestClient(create_app(MemoryStore(), sources, model, chats)) as client:
        response = _chat(client, 'Python', 'Why?')
        assert response.status_code == 409 and response.json()['code'] == 'evaluation_required'
    client = _evaluated(sources, model, chats)
    assert _chat(client, 'Python', '   ').status_code == 422
    assert model.chats == [] and chats.rows == {}
