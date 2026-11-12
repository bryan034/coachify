"""Synthetic semantic verdicts exercise harness policy, not live model accuracy."""
from copy import deepcopy
from uuid import uuid4
import httpx
import pytest
from elo_shared.skills_profile import SkillsProfile
from app.conversation.intake import next_target, skip_target
from tests.conftest import ready
from tests.test_conversation_security import PREFIX, send, settled


class Profiles:
    def __init__(self, original):
        self.original, self.records, self.receipts = original, {}, {}
        self.lose_response = False

    async def __call__(self, request):
        if request.url.path != '/api/v1/profile/skills-profile': return await self.original(request)
        import json
        owner = request.headers['authorization']
        current = self.records.setdefault(owner, SkillsProfile().model_dump(mode='json'))
        if request.method == 'GET': return httpx.Response(200, json=current)
        body = json.loads(request.content)
        key = (owner, body['mutation_id'])
        if key not in self.receipts:
            if current['version'] != body['expected_version']: return httpx.Response(409, json={})
            self.records[owner] = {**current, 'version': current['version'] + 1,
                **{k: body[k] for k in ('status', 'areas', 'entries')}}
            self.receipts[key] = body
        else: assert self.receipts[key] == body
        if self.lose_response:
            self.lose_response = False
            raise httpx.ReadTimeout('synthetic interruption')
        return httpx.Response(200, json=self.records[owner])


class Provider:
    configured = True
    approve = True
    evaluation = None
    calls = None
    def __init__(self): self.calls = []
    def route(self, context):
        self.calls.append(deepcopy(context))
        if context['task'].startswith('cv_interview_'):
            from tests.interview_fixture import InterviewProvider
            if not hasattr(self, 'interview'): self.interview = InterviewProvider()
            return self.interview.route(context)
        if context['task'] == 'skills_intake':
            output = self.evaluation(context) if callable(self.evaluation) else self.evaluation
            return deepcopy(output or {'reply': 'You can describe what you did.', 'entries': [], 'areas': []}), {}
        return {'reply': 'What can you share about ' + str(context['target'].get('field') or context['target'].get('area')) + '?', 'actions': []}, {}
    def verify_evidence(self, blocks, refs, **kwargs):
        return frozenset((r['block_id'], r['excerpt']) for r in refs) if self.approve else frozenset()


def open_profile(harness, cv_id=None):
    client, app, _, _, original = harness
    transport = Profiles(original)
    app.state.profile_client = httpx.AsyncClient(transport=httpx.MockTransport(transport), base_url='http://profile')
    provider = app.state.conversations.provider = Provider()
    response = client.post(PREFIX, json={'cv_id': cv_id, 'mutation_id': str(uuid4()), 'purpose': 'skills_profile'})
    assert response.status_code == 200, response.text
    return response.json(), provider, transport


def evaluated(context):
    quote = context['message']
    evidence = [{'message_id': context['message_id'], 'quote': quote}]
    return {'reply': 'I have captured the task you described.', 'areas': [], 'entries': [{
        'id': None, 'kind': 'project', 'title': 'Weekly reports', 'title_evidence': quote,
        'fields': {'description': {'status': 'answered', 'value': 'Weekly data processing', 'evidence': evidence},
                   'contribution': {'status': 'answered', 'value': 'Combined sales reports', 'evidence': evidence}},
        'skills': [{'name': 'Data processing', 'description': 'Combined spreadsheet reports with pandas.',
                    'evidence': evidence, 'dimensions': {'frequency': {'status': 'answered', 'value': 'Weekly', 'evidence': evidence}}}]}]}


def test_manual_entry_semantic_paraphrase_save_resume_and_skip(harness):
    client, app, *_ = harness
    chat, provider, profiles = open_profile(harness)
    chat = send(client, chat, 'Start', command='review')
    assert chat['active_question']['title'] == 'work or internship experience'
    chat = send(client, chat, 'Skip this area', command='skip')
    assert chat['active_question']['title'] == 'project'
    provider.evaluation = evaluated
    chat = send(client, chat, 'I used pandas every Friday to combine sales spreadsheets for Weekly reports.')
    profile = profiles.records['Bearer owner-a']
    assert profile['status'] == 'draft'
    assert profile['entries'], chat['messages'][-1]
    assert profile['entries'][0]['skills'][0]['name'] == 'Data processing'
    assert profile['entries'][0]['fields']['description']['value'] == 'Weekly data processing'
    assert chat['active_question']['question'].endswith('contribution?')
    # No CV or career goal was created/required, and a partial profile is saveable.
    chat = send(client, chat, 'Save my reviewed profile', command='finish')
    assert profiles.records['Bearer owner-a']['status'] == 'saved'
    assert chat['active_question'] is None
    resumed = client.post(PREFIX, json={'mutation_id': str(uuid4()), 'purpose': 'skills_profile'}).json()
    assert resumed['id'] == chat['id']


def test_unsupported_or_forged_evidence_never_changes_profile(harness):
    client, app, *_ = harness
    chat, provider, profiles = open_profile(harness)
    provider.evaluation, provider.approve = evaluated, False
    chat = send(client, chat, 'My teammates built the project, I watched.')
    assert profiles.records['Bearer owner-a']['entries'] == []
    assert any(a['status'] == 'failed' for m in chat['messages'] for a in m['actions'])
    provider.approve = True
    def forged(context):
        output = evaluated(context)
        output['entries'][0]['fields']['description']['evidence'][0]['message_id'] = 'someone-elses-answer'
        return output
    provider.evaluation = forged
    chat = send(client, chat, 'I combined the spreadsheets.')
    assert profiles.records['Bearer owner-a']['entries'] == []


def test_lost_profile_response_retries_same_write_without_duplicate_entries(harness):
    client, app, *_ = harness
    chat, provider, profiles = open_profile(harness)
    provider.evaluation = evaluated
    profiles.lose_response = True
    chat = send(client, chat, 'I used pandas for Weekly reports.')
    assert len(profiles.records['Bearer owner-a']['entries']) == 1, chat['messages'][-1]
    failed = chat['messages'][-1]['actions'][0]
    response = client.post(PREFIX+'/'+chat['id']+'/actions/'+failed['id'], json={
        'mutation_id': str(uuid4()), 'expected_revision': chat['revision'], 'decision': 'retry'})
    assert response.status_code == 200, response.text
    chat = settled(client, chat['id'])
    assert len(profiles.records['Bearer owner-a']['entries']) == 1, chat['messages'][-1]
    assert len([c for c in provider.calls if c['task'] == 'skills_intake']) == 1
    assert chat['messages'][-1]['actions'][0]['status'] == 'saved'


def test_cv_review_is_explicit_target_independent_and_source_bound(harness):
    client, app, *_ = harness
    cv = ready(harness)
    chat, provider, _ = open_profile(harness, cv['id'])
    assert chat['active_question'] is None
    chat = send(client, chat, 'Review my CV', command='review')
    active = chat['active_question']
    assert active and active['item_id'] in {i['id'] for i in cv['items']}
    assert app.state.target_provider.context_value is None
    assert any(c['task'] == 'cv_interview_plan' for c in provider.calls)
    chat = send(client, chat, 'Skip', command='skip')
    assert not chat['active_question'] or chat['active_question']['id'] != active['id']
    chat = send(client, chat, 'Save partial review', command='finish')
    saved = client.get('/api/v1/cv/'+cv['id']).json()
    assert saved['profile_reviewed_effective_version'] is None
    assert saved['effective_version'] == cv['effective_version']
    assert chat['interview']['status'] == 'paused'
    assert not chat['active_question']


def test_backend_orders_fields_and_preserves_explicit_unknown():
    profile = SkillsProfile(areas={'work':'not_applicable'}).model_dump(mode='json')
    target = next_target(profile)
    assert target['area'] == 'project'
    skip_target(profile, target)
    assert next_target(profile)['area'] == 'education'


def test_changed_manual_profile_cannot_skip_a_different_question(harness):
    client, app, *_ = harness
    chat, provider, profiles = open_profile(harness)
    chat = send(client, chat, 'Start', command='review')
    profiles.records['Bearer owner-a'].update(version=1, areas={'work':'not_applicable'})
    response = client.post(PREFIX+'/'+chat['id']+'/messages',json={
        'mutation_id':str(uuid4()),'expected_revision':chat['revision'],'command':'skip','text':'Skip'})
    assert response.status_code == 409
    current = client.get(PREFIX+'/'+chat['id']).json()
    assert current['active_question'] is None
    assert profiles.records['Bearer owner-a']['areas'] == {'work':'not_applicable'}
    current = send(client, current, 'Continue', command='continue')
    assert current['active_question']['title'] == 'project'


def test_summary_review_stamp_checks_owner_version_and_replays_without_evidence_change(harness):
    from tests.conftest import mutation
    client, app, *_ = harness
    cv = ready(harness)
    path = '/api/v1/cv/'+cv['id']+'/profile-review'
    assert client.post(path,headers={'Authorization':'Bearer owner-b'},json=mutation(cv['version'])).status_code == 404
    assert client.post(path,json=mutation(cv['version']+1)).status_code == 409
    body = mutation(cv['version'])
    response = client.post(path,json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['profile_reviewed_effective_version'] == cv['effective_version']
    assert saved['effective_version'] == cv['effective_version']
    assert client.post(path,json=body).json() == saved


def test_legacy_pending_actions_keep_their_execution_mode_until_finished(harness):
    from tests.test_conversation import Router
    from tests.test_conversation_security import open_chat
    client, app, *_ = harness
    chat = open_chat(client)
    app.state.conversations.provider = Router([{'kind':'add_capability','name':'Python','excerpt':'I use Python.'}])
    chat = send(client, chat, 'I use Python.')
    before = deepcopy(chat['messages'])
    request = {'mutation_id':str(uuid4()),'purpose':'skills_profile'}
    legacy = client.post(PREFIX,json=request).json()
    assert legacy['purpose'] is None
    assert legacy['messages'] == before
    proposed = next(a for m in legacy['messages'] for a in m['actions'] if a['kind']=='add_capability')
    response = client.post(PREFIX+'/'+chat['id']+'/actions/'+proposed['id'],json={
        'mutation_id':str(uuid4()),'expected_revision':legacy['revision'],'decision':'cancel'})
    assert response.status_code == 200, response.text
    app.state.profile_client = httpx.AsyncClient(transport=httpx.MockTransport(Profiles(harness[-1])),base_url='http://profile')
    upgraded = client.post(PREFIX,json=request).json()
    assert upgraded['purpose'] == 'skills_profile'
    stored = app.state.conversations.get('owner-a',chat['id'])
    assert stored['purpose'] == 'skills_profile'
    assert len(stored['messages']) == len(before)


@pytest.mark.parametrize('approved', [True, False])
def test_cv_interpretation_accepts_semantic_proficiency_and_independence_only_with_support(harness, approved):
    from tests.test_clarification import prepare_context
    from tests.conftest import FakeInterpreter, mutation
    client, app, *_ = harness
    cv, questions = prepare_context(harness, ready(harness))
    question = next(q for q in questions if q['uncertainty'] == 'proficiency')
    text = 'I can combine two tables using their matching keys. Nobody needs to step in while I do that.'
    class SemanticInterpreter(FakeInterpreter):
        def verify_evidence(self, blocks, refs, **kwargs):
            assert all(block['text'] == text for block in blocks)
            return frozenset((ref['block_id'], ref['excerpt']) for ref in refs) if approved else frozenset()
    interpreter = SemanticInterpreter()
    interpreter.payload = {'resolution':'resolved', 'claims':[{'skill_id':'skill:sql','name':'SQL',
        'attribution':'unknown','assistance':'independent','proficiency':'Basic joins',
        'changed_fields':['assistance','proficiency'],'evidence_excerpt':text}],
        'resolved_uncertainties':['proficiency'],'remaining_uncertainties':[]}
    app.state.interpreter = interpreter
    response = client.put('/api/v1/cv/'+cv['id']+'/clarifications/'+question['id'],
        json={**mutation(cv['version']), 'action':'answer','answer':text})
    assert response.status_code == 200, response.text
    saved = next(q for q in response.json()['clarifications'] if q['id'] == question['id'])
    assert saved['answer'] == text
    assert saved['interpretation_status'] == ('ready' if approved else 'failed')
    if approved:
        claim = saved['interpretation']['claims'][0]
        assert claim['proficiency'] == 'Basic joins' and claim['assistance'] == 'independent'


def test_old_refresh_cannot_clear_a_concurrently_published_review_question(harness, monkeypatch):
    import asyncio
    client, app, *_ = harness
    cv = ready(harness)
    chat, _, _ = open_profile(harness, cv['id'])
    service = app.state.conversations
    before_chat = service.get('owner-a', chat['id'])
    before_cv = service.cv.get('owner-a', cv['id'])
    chat = send(client, chat, 'Review my CV', command='review')
    active = chat['active_question']
    assert active
    original_get, original_cv_get = service.get, service.cv.get
    stale_chat, stale_cv = [before_chat], [before_cv]

    def read_chat(*args):
        return stale_chat.pop() if stale_chat else original_get(*args)

    def read_cv(*args):
        return stale_cv.pop() if stale_cv else original_cv_get(*args)

    monkeypatch.setattr(service, 'get', read_chat)
    monkeypatch.setattr(service.cv, 'get', read_cv)
    account = {'id': 'owner-a', 'authorization': 'Bearer owner-a'}
    refreshed = asyncio.run(service.refresh(app, account, chat['id']))
    assert refreshed['active_question'] == active
    assert refreshed['revision'] == chat['revision']
    # A fresh read still clears a question whose source really changed.
    document = original_cv_get('owner-a', cv['id'])
    from app.schemas.cv import AnswerMutation
    from app.clarification.service import answer
    answer(service.cv, 'owner-a', cv['id'], active['id'],
           AnswerMutation(expected_version=document['version'], mutation_id=uuid4(), action='skip'))
    refreshed = asyncio.run(service.refresh(app, account, chat['id']))
    assert refreshed['active_question'] is None


def test_old_profile_refresh_preserves_a_newer_intake_question(harness, monkeypatch):
    import asyncio
    import app.conversation.intake as intake
    client, app, *_ = harness
    chat, provider, profiles = open_profile(harness)
    service = app.state.conversations
    before_chat = service.get('owner-a', chat['id'])
    before_profile = SkillsProfile().model_dump(mode='json')
    provider.evaluation = evaluated
    chat = send(client, chat, 'I used pandas for Weekly reports.')
    assert chat['active_question']
    original_get = service.get
    stale = [before_chat]
    monkeypatch.setattr(service, 'get', lambda *args: stale.pop() if stale else original_get(*args))

    async def old_profile(*args): return before_profile

    monkeypatch.setattr(intake, 'read_profile', old_profile)
    refreshed = asyncio.run(service.refresh(app, {'id': 'owner-a'}, chat['id']))
    # The public view adds empty defaults for question numbering and hints that intake questions do not use.
    assert {**refreshed['active_question'], 'number': None, 'limit': None, 'hints': [], 'reason': None} == chat['active_question']
    assert refreshed['intake_profile_version'] == profiles.records['Bearer owner-a']['version']
    assert refreshed['revision'] == chat['revision']
