"""Synthetic contracts and real MongoDB compare-and-set concurrency coverage."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from app.main import create_app
from app.domain import targets
from app.repositories.targets import MemoryTargetRepository, TargetRepository
from app.schemas.targets import SelectTarget, TargetCreate, canonical_skill_id

BASE = '/api/v1/career/targets'
OWNER_A, OWNER_B = 'a8d77eb4-cf9f-4ddc-9372-f2bc6dd080a2', '04722fb4-c2ae-445f-b615-cd7d305a9828'
AUTH = {'Authorization': 'Bearer ' + OWNER_A}
SOURCE = 'Synthetic analyst role. Use Python to analyse records and SQL to query tables.\n' + 'Transient material not retained. ' * 100


def profile():
    def handle(request):
        owner = request.headers['Authorization'].removeprefix('Bearer ')
        if owner == 'revoked': return httpx.Response(401, json={})
        if owner == 'unfinished': return httpx.Response(200, json={'id': OWNER_A, 'email_verified': True, 'onboarding_complete': False})
        if request.url.path.endswith('/auth/session'): return httpx.Response(200, json={'id': owner, 'email_verified': True})
        return httpx.Response(200, json={'onboarding_complete': True})
    return httpx.AsyncClient(base_url='http://profile.test', transport=httpx.MockTransport(handle))


@pytest.fixture(params=['memory', 'mongo'])
def repository(request):
    if request.param == 'memory': yield MemoryTargetRepository(); return
    uri = os.getenv('MONGODB_TEST_URI')
    if not uri: pytest.skip('Set MONGODB_TEST_URI to test real target persistence and concurrency.')
    mongo = MongoClient(uri, serverSelectionTimeoutMS=3000)
    name = 'coachify_career_test_' + uuid4().hex
    try: yield TargetRepository(mongo[name])
    finally:
        mongo.drop_database(name)
        mongo.close()


@pytest.fixture
def harness(repository):
    with TestClient(create_app(profile(), target_repository=repository)) as client:
        client.headers.update(AUTH)
        yield client, repository


def draft(**changes):
    return {'mutation_id': str(uuid4()), 'target_type': 'specific_job', 'role': 'Data analyst', 'field': 'Data',
        'skills': [{'name': 'Python', 'evidence': 'Use Python to analyse records'}], 'reviewed_source_text': SOURCE, **changes}


def confirmed(client, **changes):
    response = client.post(BASE, json=draft(**changes)); assert response.status_code == 201, response.text
    target = response.json()
    response = client.post(BASE + '/' + target['id'] + '/confirm', json={'mutation_id': str(uuid4()), 'expected_version': target['version']})
    assert response.status_code == 200, response.text
    return response.json()


def select_body(target, version=0, **changes):
    return {'mutation_id': str(uuid4()), 'expected_version': version, 'career_target_id': target['id'], 'career_target_version': target['version'], **changes}


def test_draft_review_confirmation_and_selection_are_separate(harness):
    client, repository = harness
    assert client.get(BASE + '/selected-context').json() is None
    target = client.post(BASE, json=draft()).json()
    assert target['status'] == 'draft' and target['version'] == 1
    assert target['requirements_source'] == 'user_reviewed_jd' and target['generation_version'] == 'manual-v1'
    assert target['skills'][0]['skill_id'] == 'skill:python'
    assert target['skills'][0]['origin'] == 'user_reviewed_jd'
    assert client.put(BASE + '/selection', json=select_body(target)).status_code == 409
    body = {'mutation_id': str(uuid4()), 'expected_version': 1}
    response = client.post(BASE + '/' + target['id'] + '/confirm', json=body)
    assert response.status_code == 200 and response.json()['version'] == 2
    assert client.post(BASE + '/' + target['id'] + '/confirm', json=body).json() == response.json()
    assert client.get(BASE + '/selected-context').json() is None
    target = response.json()
    assert client.put(BASE + '/selection', json=select_body(target)).json() == {'career_target_id': target['id'], 'career_target_version': 2, 'version': 1}
    context = client.get(BASE + '/selected-context').json()
    assert context == {'id': target['id'], 'version': 2, 'type': 'specific_job', 'confirmed': True,
        'skill_ids': ['skill:python'], 'conditions': [], 'selection_version': 1, 'role': 'Data analyst', 'field': 'Data'}
    assert client.get(BASE + '/' + target['id'] + '/confirmed-context?expected_version=2').json() == context
    assert client.get(BASE + '/' + target['id'] + '/confirmed-context?expected_version=1').status_code == 409
    assert client.get(BASE + '/' + target['id']).json() == target
    assert client.get(BASE).json()['targets'] == [target]
    assert response.headers['Cache-Control'] == 'no-store'


def test_full_source_never_reaches_documents_or_retry_receipts(harness):
    client, repository = harness
    body = draft()
    target = client.post(BASE, json=body).json()
    stored = json.dumps(repository.get(OWNER_A, target['id']))
    assert 'reviewed_source_text' not in stored and SOURCE not in stored and 'Transient material not retained' not in stored
    retry = client.post(BASE, json={**body, 'reviewed_source_text': SOURCE + 'Different unrelated source context.'})
    assert retry.status_code == 201 and retry.json()['id'] == target['id']
    assert len(repository.list(OWNER_A)) == 1
    mismatch = client.post(BASE, json={**body, 'role': 'Changed role'})
    assert mismatch.status_code == 409
    assert 'Transient material' not in mismatch.text


def test_owner_isolation_and_authentication(harness):
    client, repository = harness
    target = confirmed(client)
    client.headers['Authorization'] = 'Bearer ' + OWNER_B
    assert client.get(BASE).json()['targets'] == []
    assert client.get(BASE + '/' + target['id']).status_code == 404
    assert client.post(BASE + '/' + target['id'] + '/confirm', json={'expected_version': 2, 'mutation_id': str(uuid4())}).status_code == 404
    assert client.get(BASE + '/' + target['id'] + '/confirmed-context?expected_version=2').status_code == 404
    assert client.put(BASE + '/selection', json=select_body(target)).status_code == 404
    for token, code in [('revoked', 401), ('unfinished', 403)]:
        client.headers['Authorization'] = 'Bearer ' + token
        assert client.get(BASE).status_code == code
    client.headers.pop('Authorization')
    assert client.post(BASE, json=draft()).status_code == 401


@pytest.mark.parametrize('changes', [
    {'user_id': OWNER_B}, {'requirements_source': 'ai'}, {'status': 'confirmed'}, {'mutation_id': 'not-uuid'},
    {'role': ' '}, {'field': 'x' * 201}, {'company': 12}, {'skills': [{'name': 'Python', 'evidence': 'Not in the source'}]},
    {'skills': [{'name': 'Python'}]}, {'skills': [{'name': 'Python', 'evidence': 'Use Python', 'required_experience_months': True}]},
    {'skills': [{'name': 'Python', 'evidence': 'Use Python', 'required_experience_months': -1}]},
    {'skills': [{'name': 'Python', 'evidence': 'Use Python', 'skill_id': 'skill:forged'}]},
    {'skills': [{'name': 'Python', 'evidence': 'Use Python'}] * 41},
    {'skills': [{'name': 'Python', 'evidence': 'Use Python'}, {'name': 'Ｐｙｔｈｏｎ', 'evidence': 'Use Python'}]},
    {'job_url': 'javascript:alert(1)'}, {'job_url': 'https://user:secret@example.test'},
    {'reviewed_source_text': 'x' * 20001}, {'interests': ['x'] * 21}, {'role': 'bad\x00text'},
])
def test_strict_invalid_inputs_leave_no_saved_targets(harness, changes):
    client, repository = harness
    response = client.post(BASE, json=draft(**changes))
    assert response.status_code == 422, response.text
    assert repository.list(OWNER_A) == []
    assert 'reviewed_source_text' not in response.text


def test_exploration_is_user_guidance_and_empty_draft_is_not_ready(harness):
    client, repository = harness
    target = confirmed(client, target_type='career_exploration', reviewed_source_text=None,
        skills=[{'name': ' Python ', 'context': 'I want to work on data tooling.'}])
    assert target['requirements_source'] == 'user_guidance'
    assert target['skills'][0]['origin'] == 'user_guidance'
    assert target['skills'][0]['skill_id'] == 'skill:python'
    empty = client.post(BASE, json=draft(skills=[], reviewed_source_text=None)).json()
    response = client.post(BASE + '/' + empty['id'] + '/confirm', json={'expected_version': 1, 'mutation_id': str(uuid4())})
    assert response.status_code == 422
    assert client.get(BASE + '/' + empty['id']).json()['status'] == 'draft'


def condition(**changes):
    return {'kind': 'qualification', 'label': 'Computer Science degree',
        'description': 'A Computer Science degree is required.', 'item_kinds': ['education'],
        'match_terms': ['Computer Science'], 'evidence': 'A Computer Science degree is required.', **changes}


@pytest.mark.parametrize('kind', ['qualification', 'date'])
def test_condition_only_job_is_confirmed_context_with_exact_evidence(harness, kind):
    client, repository = harness
    entry = condition(kind=kind)
    source = SOURCE + '\n' + entry['evidence'] + '\nPrivate source remainder not stored.'
    body = draft(skills=[], conditions=[entry], reviewed_source_text=source)
    created = client.post(BASE, json=body)
    assert created.status_code == 201, created.text
    target = created.json()
    saved = target['conditions'][0]
    assert saved['origin'] == 'user_reviewed_jd' and saved['kind'] == kind
    assert saved['match_terms'] == ['Computer Science']
    assert client.post(BASE, json=body).json()['conditions'] == [saved]
    assert 'Private source remainder' not in json.dumps(repository.get(OWNER_A, target['id']))
    assert client.put(BASE + '/selection', json=select_body(target)).status_code == 409
    target = client.post(BASE + '/' + target['id'] + '/confirm', json={'expected_version': 1, 'mutation_id': str(uuid4())}).json()
    assert target['version'] == 2
    assert client.put(BASE + '/selection', json=select_body(target)).status_code == 200
    before = repository.get(OWNER_A, target['id'])
    context = client.get(BASE + '/selected-context').json()
    assert context['skill_ids'] == [] and context['conditions'] == [saved]
    assert context['selection_version'] == 1
    assert repository.get(OWNER_A, target['id']) == before
    assert client.get(BASE + '/' + target['id'] + '/confirmed-context?expected_version=1').status_code == 409
    client.headers['Authorization'] = 'Bearer ' + OWNER_B
    assert client.get(BASE + '/selected-context').json() is None
    assert client.get(BASE + '/' + target['id']).status_code == 404


def test_exploration_conditions_are_personal_guidance_without_jd(harness):
    client, _ = harness
    entry = condition(kind='date', label='Degree timing', description='I want to clarify my Computer Science study dates.', evidence=None)
    target = confirmed(client, target_type='career_exploration', skills=[], conditions=[entry], reviewed_source_text=None)
    assert target['conditions'][0]['origin'] == 'user_guidance'
    assert target['conditions'][0]['evidence'] is None
    assert client.put(BASE + '/selection', json=select_body(target)).status_code == 200
    assert client.get(BASE + '/selected-context').json()['conditions'] == target['conditions']


@pytest.mark.parametrize('entry', [
    condition(evidence='Not in this source'), condition(evidence=None), condition(item_kinds=[]),
    condition(item_kinds=['education', 'education']), condition(item_kinds=['profile']),
    condition(match_terms=[]), condition(match_terms=[' ']), condition(match_terms=['a']),
    condition(match_terms=['Computer Science', 'Ｃｏｍｐｕｔｅｒ Science']),
    condition(match_terms=['unrelated']), condition(match_terms=['degree'] * 6),
    condition(match_terms=['x' * 121]), condition(description='x' * 501),
    condition(origin='verified'), condition(id='forged'),
    condition(label='Secret skill', description='Secret skill', match_terms=['Secret skill']),
])
def test_invalid_or_unsupported_conditions_do_not_save(harness, entry):
    client, repository = harness
    response = client.post(BASE, json=draft(skills=[], conditions=[entry], reviewed_source_text=condition()['evidence']))
    assert response.status_code == 422, response.text
    assert repository.list(OWNER_A) == []


def test_duplicate_and_oversized_conditions_are_rejected(harness):
    client, repository = harness
    for entries in ([condition(), condition(label='Ｃｏｍｐｕｔｅｒ Science degree')], [condition(label=f'Degree {n}') for n in range(21)]):
        response = client.post(BASE, json=draft(skills=[], conditions=entries, reviewed_source_text=condition()['evidence']))
        assert response.status_code == 422
    assert repository.list(OWNER_A) == []


def test_legacy_targets_without_conditions_remain_readable_and_replayable():
    repository = MemoryTargetRepository()
    request = TargetCreate.model_validate(draft())
    target = targets.create(repository, OWNER_A, request)
    repository.documents[target['id']].pop('conditions')
    old_fingerprint = targets.fingerprint(request.model_dump(exclude={'mutation_id', 'reviewed_source_text', 'conditions'}))
    repository.documents[target['id']]['create_fingerprint'] = old_fingerprint
    assert targets.create(repository, OWNER_A, request)['conditions'] == []
    assert targets.present(repository.get(OWNER_A, target['id']))['conditions'] == []


def test_noop_selection_and_old_replays_cannot_roll_back(harness):
    client, repository = harness
    first, second = confirmed(client), confirmed(client, role='Research analyst')
    original = select_body(first)
    assert client.put(BASE + '/selection', json=original).json()['version'] == 1
    noop = select_body(first, 1)
    assert client.put(BASE + '/selection', json=noop).json()['version'] == 1
    assert client.put(BASE + '/selection', json=select_body(second, 1)).json()['version'] == 2
    replay = client.put(BASE + '/selection', json=original)
    assert replay.json() == {'career_target_id': second['id'], 'career_target_version': 2, 'version': 2}
    assert client.put(BASE + '/selection', json=noop).json()['career_target_id'] == second['id']
    assert client.put(BASE + '/selection', json={**original, 'career_target_id': second['id']}).status_code == 409
    assert client.put(BASE + '/selection', json=select_body(first, 1)).status_code == 409
    assert client.get(BASE + '/' + first['id'] + '/confirmed-context?expected_version=2').status_code == 409
    assert client.get(BASE + '/' + first['id']).json() == first


def test_same_key_concurrent_create_and_select_are_idempotent(repository):
    body = TargetCreate.model_validate(draft())
    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(pool.map(lambda _: targets.create(repository, OWNER_A, body), range(8)))
    assert len({row['id'] for row in created}) == 1 and len(repository.list(OWNER_A)) == 1
    from app.schemas.targets import ConfirmTarget
    confirmation = ConfirmTarget(expected_version=1, mutation_id=str(uuid4()))
    with ThreadPoolExecutor(max_workers=8) as pool:
        confirmed_targets = list(pool.map(lambda _: targets.confirm(repository, OWNER_A, created[0]['id'], confirmation), range(8)))
    assert all(row['version'] == 2 for row in confirmed_targets)
    selection = SelectTarget.model_validate(select_body(confirmed_targets[0]))
    with ThreadPoolExecutor(max_workers=8) as pool:
        selected = list(pool.map(lambda _: targets.select(repository, OWNER_A, selection), range(8)))
    assert all(row['version'] == 1 for row in selected)


def test_concurrent_different_selections_accept_only_one_expected_version(harness):
    from fastapi import HTTPException
    client, repository = harness
    first, second = confirmed(client), confirmed(client, role='Other role')
    def save(target):
        try: return targets.select(repository, OWNER_A, SelectTarget.model_validate(select_body(target)))
        except HTTPException as exc: return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(save, [first, second]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert 409 in results
    assert repository.selection(OWNER_A)['version'] == 1


def test_target_switch_during_context_read_is_rejected(harness, monkeypatch):
    client, repository = harness
    target = confirmed(client)
    client.put(BASE + '/selection', json=select_body(target))
    original = repository.selection
    calls = 0
    def changing(owner):
        nonlocal calls
        calls += 1
        value = original(owner)
        if calls > 1: value['version'] += 1
        return value
    monkeypatch.setattr(repository, 'selection', changing)
    assert client.get(BASE + '/selected-context').status_code == 409


def test_target_payload_limit_and_unicode_are_separate_from_preview_limits(harness):
    client, repository = harness
    source = '🧭' * 19000 + 'Use Python to analyse records'
    response = client.post(BASE, json=draft(reviewed_source_text=source, role='数据分析师'))
    assert response.status_code == 201
    assert response.json()['role'] == '数据分析师'
    assert client.post(BASE, content=b'x' * (256 * 1024 + 1)).status_code == 413
    assert client.post(BASE, content=(b'x' * 65536 for _ in range(5)), headers={'Content-Type': 'application/json'}).status_code == 413
    assert client.post(BASE, content=b'{}', headers={'Content-Length': '-1'}).status_code == 413
    assert client.post('/api/v1/career/imports/url', content=b'x' * 17000).status_code == 413
    assert client.post(BASE, json={**draft(), 'skills': [{'name': 'ﷺ' * 200, 'evidence': 'Use Python'}]}).status_code == 201


def legacy_without_storage(*args):
    # Retired API failure/recovery coverage uses an explicit test-only router.
    # Production create_app() exposes only canonical-goal confirmation.
    from anyio import CapacityLimiter
    from app.api.v1.targets import router
    app=create_app(*args)
    app.state.target_repository=None
    app.state.target_database=None
    app.state.target_limiter=CapacityLimiter(8)
    app.include_router(router)
    return app


def test_storage_outage_and_missing_configuration_do_not_break_previews(monkeypatch):
    monkeypatch.delenv('MONGODB_URI', raising=False)
    processor = lambda *_: {'kind': 'url', 'text': 'Synthetic preview', 'source_name': 'example.test', 'notices': []}
    with TestClient(legacy_without_storage(profile(), processor)) as client:
        assert client.get(BASE, headers=AUTH).status_code == 503
        assert client.post('/api/v1/career/imports/url', headers=AUTH, json={'url': 'https://example.test'}).status_code == 200
    repository = MemoryTargetRepository()
    def unavailable(*_): raise ServerSelectionTimeoutError('mongodb://private:secret@host')
    monkeypatch.setattr(repository, 'list', unavailable)
    with TestClient(create_app(profile(), target_repository=repository)) as client:
        response = client.get(BASE, headers=AUTH)
        assert response.status_code == 503 and 'secret' not in response.text


def test_normalization_matches_shared_cv_identity():
    assert canonical_skill_id('  Ｐｙｔｈｏｎ\tDevelopment ') == 'skill:python development'
    assert canonical_skill_id('Straße') == 'skill:strasse'
    assert canonical_skill_id('CAFÉ') == 'skill:café'


def test_failed_database_initialization_recovers_on_later_request(monkeypatch):
    monkeypatch.delenv('MONGODB_URI', raising=False)
    repository = MemoryTargetRepository()
    attempts = []
    def initialize(database):
        attempts.append(database)
        if len(attempts) == 1: raise ServerSelectionTimeoutError('synthetic startup outage')
        return repository
    monkeypatch.setattr('app.api.v1.targets.TargetRepository', initialize)
    app = legacy_without_storage(profile())
    with TestClient(app) as client:
        app.state.target_database = 'synthetic owned database'
        assert client.get(BASE, headers=AUTH).status_code == 503
        assert client.get(BASE, headers=AUTH).json() == {'targets': [], 'selection': {'career_target_id': None, 'career_target_version': None, 'version': 0}, 'next_cursor': None, 'selected_target': None}
        assert len(attempts) == 2


def test_target_history_pages_preserve_all_rows_and_old_selection(harness, monkeypatch):
    from datetime import datetime, timezone
    from app.schemas.targets import ConfirmTarget
    client, repository = harness
    class SameCreationTime(datetime):
        @classmethod
        def now(cls, tz=None): return datetime(2026, 1, 1, tzinfo=timezone.utc)
    with monkeypatch.context() as patch:
        patch.setattr(targets, 'datetime', SameCreationTime)
        # Substantial structured history exercises the list boundary rather than
        # depending on a handful of tiny records fitting in memory by accident.
        saved = [targets.create(repository, OWNER_A, TargetCreate.model_validate(draft(
            target_type='career_exploration', reviewed_source_text=None, role='Analyst ' + str(index),
            skills=[{'name': 'Skill ' + str(skill), 'context': 'Synthetic context. ' * 25,
                     'evidence': 'Synthetic user guidance. ' * 20} for skill in range(40)]))) for index in range(43)]
    ordered = sorted(saved, key=lambda row: (row['created_at'], row['id']), reverse=True)
    oldest = targets.confirm(repository, OWNER_A, ordered[-1]['id'], ConfirmTarget(expected_version=1, mutation_id=str(uuid4())))
    targets.select(repository, OWNER_A, SelectTarget.model_validate(select_body(oldest)))
    first = client.get(BASE).json()
    assert len(first['targets']) == 20 and first['next_cursor']
    assert first['selected_target'] == oldest
    assert oldest['id'] not in {row['id'] for row in first['targets']}
    assert [row['id'] for row in first['targets']] == [row['id'] for row in ordered[:20]]
    # A newer insertion after the first page does not shift an offset or cause
    # existing rows to repeat/disappear while the user traverses older history.
    concurrent = targets.create(repository, OWNER_A, TargetCreate.model_validate(draft(role='New concurrent target')))
    seen = list(first['targets'])
    cursor = first['next_cursor']
    while cursor:
        response = client.get(BASE, params={'cursor': cursor})
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page['targets']) <= 20 and page['selected_target'] == oldest
        seen.extend(page['targets'])
        cursor = page['next_cursor']
    assert [row['id'] for row in seen] == [row['id'] for row in ordered]
    assert len({row['id'] for row in seen}) == 43
    assert concurrent['id'] not in {row['id'] for row in seen}
    assert client.get(BASE).json()['targets'][0]['id'] == concurrent['id']
    # The API bound is implemented at the repository boundary, including the
    # extra look-ahead record used to decide whether a next page exists.
    assert len(repository.list(OWNER_A)) == 21
    assert client.get(BASE + '/' + oldest['id']).json() == oldest


def test_cursor_rejects_tampering_and_other_owners_without_exposing_data(harness):
    import base64
    client, repository = harness
    own = targets.create(repository, OWNER_A, TargetCreate.model_validate(draft()))
    foreign = targets.create(repository, OWNER_B, TargetCreate.model_validate(draft(role='Private other-owner role')))
    def encoded(value): return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    malformed = [
        'not a cursor', '=', 'x' * 513,
        encoded({'created_at': own['created_at'], 'id': own['id'], 'owner': OWNER_B}),
        encoded({'created_at': 42, 'id': own['id']}),
        encoded({'created_at': 'invalid date', 'id': own['id']}),
        encoded({'created_at': '2026-01-01T00:00:00', 'id': own['id']}),
        encoded({'created_at': own['created_at'], 'id': 'not-a-uuid'}),
        encoded({'created_at': own['created_at'], 'id': str(uuid4())}),
        encoded({'created_at': '2026-01-01T00:00:00+00:00', 'id': own['id']}),
        targets.encode_cursor(foreign), encoded(['unexpected list']),
    ]
    for cursor in malformed:
        response = client.get(BASE, params={'cursor': cursor})
        assert response.status_code == 422, response.text
        assert 'Private other-owner role' not in response.text and OWNER_B not in response.text
    response = client.get(BASE, params={'cursor': targets.encode_cursor(own)})
    assert response.status_code == 200 and response.json()['targets'] == []
    client.headers['Authorization'] = 'Bearer ' + OWNER_B
    assert client.get(BASE, params={'cursor': targets.encode_cursor(own)}).status_code == 422
    assert [target['id'] for target in client.get(BASE).json()['targets']] == [foreign['id']]


def test_mongo_list_sets_owner_seek_sort_and_limit_before_iteration():
    events = []
    class Cursor:
        def sort(self, value): events.append(('sort', value)); return self
        def limit(self, value): events.append(('limit', value)); return self
        def __iter__(self):
            assert events[-1] == ('limit', 21)
            events.append(('iterate', None))
            return iter([])
    class Collection:
        def find(self, query): events.append(('find', query)); return Cursor()
    repository = TargetRepository.__new__(TargetRepository)
    repository.collection = Collection()
    anchor = {'created_at': '2026-01-01T00:00:00+00:00', 'id': str(uuid4())}
    assert repository.list(OWNER_A, anchor) == []
    assert events == [('find', {'user_id': OWNER_A, '$or': [
        {'created_at': {'$lt': anchor['created_at']}},
        {'created_at': anchor['created_at'], '_id': {'$lt': anchor['id']}}]}),
        ('sort', [('created_at', -1), ('_id', -1)]), ('limit', 21), ('iterate', None)]
