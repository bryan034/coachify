import asyncio
from copy import deepcopy
import httpx
import pytest
from app.clients.career import CareerTargetProvider, service_url, MAX_CONTEXT_BYTES
from app.domain.errors import CvError
from tests.conftest import ready, mutation, upload
from tests.test_clarification import prepare_context


def context(**changes):
    return {'id': 'target-a', 'version': 1, 'type': 'specific_job', 'confirmed': True,
            'skill_ids': ['skill:python', 'skill:sql'], 'selection_version': 1,
            'role': 'Software engineer', 'field': 'Technology', 'conditions': [], **changes}


def run_provider(handler, method='selected_context', *args):
    async def invoke():
        async with httpx.AsyncClient(base_url='http://career', transport=httpx.MockTransport(handler),
                                     follow_redirects=False, trust_env=False, timeout=5) as client:
            return await getattr(CareerTargetProvider(client), method)('Bearer synthetic-owner', *args)
    return asyncio.run(invoke())


def test_career_adapter_owner_forwarding_and_versioned_paths():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=context())
    assert run_provider(handler) == context()
    assert run_provider(handler, 'context', 'target-a', 1) == context()
    assert requests[0].url.path == '/api/v1/career/targets/selected-context'
    assert requests[1].url.path == '/api/v1/career/targets/target-a/confirmed-context'
    assert requests[1].url.params['expected_version'] == '1'
    assert all(request.headers['authorization'] == 'Bearer synthetic-owner' for request in requests)


def test_only_selected_context_can_explicitly_report_none():
    assert run_provider(lambda request: httpx.Response(200, content=b'null', headers={'content-type': 'application/json'})) is None
    with pytest.raises(CvError) as error:
        run_provider(lambda request: httpx.Response(200, content=b'null', headers={'content-type': 'application/json'}),
                     'context', 'target-a', 1)
    assert error.value.status == 503


@pytest.mark.parametrize('code', [401, 403, 404, 409, 503])
def test_career_failures_are_not_misreported_as_deferred(code):
    with pytest.raises(CvError) as error:
        run_provider(lambda request: httpx.Response(code, json={'detail': 'Do not expose upstream internals'}))
    assert error.value.status == code
    assert 'upstream' not in error.value.detail


@pytest.mark.parametrize('changes', [
    {'confirmed': False}, {'confirmed': 1}, {'version': '1'}, {'selection_version': 0},
    {'type': 'exploration'}, {'role': ''}, {'skill_ids': ['skill:SQL']},
    {'skill_ids': ['skill:sql', 'skill:sql']}, {'skill_ids': ['skill:s' + str(i) for i in range(41)]},
    {'untrusted_extra': 'ignored fields are not allowed'},
])
def test_career_response_shape_is_strict(changes):
    with pytest.raises(CvError) as error:
        run_provider(lambda request: httpx.Response(200, json=context(**changes)))
    assert error.value.status == 503


@pytest.mark.parametrize('field', ['selection_version', 'role', 'field'])
def test_production_adapter_rejects_missing_context_metadata(field):
    payload = context()
    del payload[field]
    with pytest.raises(CvError) as error:
        run_provider(lambda request: httpx.Response(200, json=payload))
    assert error.value.status == 503


@pytest.mark.parametrize('response', [
    httpx.Response(302, headers={'location': 'https://outside.example'}),
    httpx.Response(200, content=b'x' * (MAX_CONTEXT_BYTES + 1), headers={'content-type': 'application/json'}),
    httpx.Response(200, content=b'{invalid', headers={'content-type': 'application/json'}),
    httpx.Response(200, json={'wrong': 'shape'}),
    httpx.Response(200, content=b'null', headers={'content-type': 'text/html'}),
])
def test_redirect_malformed_oversize_and_wrong_content_are_unavailable(response):
    with pytest.raises(CvError) as error:
        run_provider(lambda request: response)
    assert error.value.status == 503


def test_career_timeout_and_mismatched_target_are_explicit():
    def timeout(request): raise httpx.ReadTimeout('synthetic timeout')
    with pytest.raises(CvError) as error: run_provider(timeout)
    assert error.value.status == 503
    with pytest.raises(CvError) as error:
        run_provider(lambda request: httpx.Response(200, json=context(id='another-target')), 'context', 'target-a', 1)
    assert error.value.status == 409


def test_canonical_names_expanded_by_unicode_normalization_are_accepted():
    from app.domain.capabilities import skill_id
    expanded = skill_id('\ufdfa' * 200)
    assert len(expanded) > 206
    payload = context(skill_ids=[expanded])
    assert run_provider(lambda request: httpx.Response(200, json=payload)) == payload


@pytest.mark.parametrize('url', ['file:///tmp/target', 'http://user:secret@career',
                                 'http://career/api', 'http://career?owner=other', 'http://career/#x'])
def test_career_origin_rejects_credentials_paths_and_non_http(url):
    with pytest.raises(RuntimeError): service_url(url)


def test_empty_prepared_context_is_persisted_and_distinct_from_deferred(harness):
    client, app, _, targets, _ = harness
    cv = ready(harness)
    path = f"/api/v1/cv/{cv['id']}/clarifications"
    missing = client.get(path).json()
    assert missing['deferred'] and not missing['prepared'] and missing['context'] is None
    targets.context_value = context(skill_ids=['skill:unrelated'])
    initial = client.get(path).json()
    assert not initial['deferred'] and not initial['prepared'] and initial['questions'] == []
    request = mutation(cv['version'], career_target_id='target-a', career_target_version=1,
                       career_target_selection_version=1)
    result = client.post(path + '/prepare', json=request)
    assert result.status_code == 200, result.text
    prepared = result.json()
    assert prepared['prepared'] and not prepared['deferred'] and prepared['questions'] == []
    assert prepared['cv_version'] > cv['version']
    assert client.get(path).json() == prepared
    assert client.post(path + '/prepare', json=request).json() == prepared
    stored = app.state.repository.get('owner-a', cv['id'])
    assert stored['prepared_context']['selection_version'] == 1
    assert stored['effective_version'] == cv['effective_version']


def test_reads_filter_pending_for_current_context_but_keep_saved_history(harness):
    client, app, _, targets, _ = harness
    cv, questions = prepare_context(harness, ready(harness))
    path = f"/api/v1/cv/{cv['id']}/clarifications"
    project = next(q for q in questions if q['kind'] == 'project')
    saved = client.put(path + '/' + project['id'], json=mutation(cv['version'], action='skip')).json()
    before = deepcopy(app.state.repository.get('owner-a', cv['id']))
    targets.context_value = context(id='target-b', type='career_exploration', skill_ids=['skill:unrelated'], selection_version=2)
    current = client.get(path).json()
    assert current['context']['id'] == 'target-b' and not current['prepared']
    assert [q['id'] for q in current['questions']] == [project['id']]
    assert current['questions'][0]['status'] == 'skipped'
    assert app.state.repository.get('owner-a', cv['id']) == before
    targets.context_value = None
    deferred = client.get(path).json()
    assert deferred['deferred'] and [q['id'] for q in deferred['questions']] == [project['id']]
    revisited, reused = prepare_context(harness, saved, 'target-a')
    assert len(reused) == len(questions)
    assert next(q for q in reused if q['id'] == project['id'])['status'] == 'skipped'


def test_old_documents_require_explicit_prepare_without_losing_answers(harness):
    client, app, *_ = harness
    cv, questions = prepare_context(harness, ready(harness))
    path = f"/api/v1/cv/{cv['id']}/clarifications"
    saved = client.put(path + '/' + questions[0]['id'],
        json=mutation(cv['version'], action='answer', answer='I built the Python portion with guidance.')).json()
    previous = app.state.repository.get('owner-a', cv['id'])
    legacy = deepcopy(previous)
    del legacy['prepared_context']
    legacy['revision'] += 1
    app.state.repository.replace(previous, legacy)
    result = client.get(path).json()
    assert not result['deferred'] and not result['prepared']
    assert next(q for q in result['questions'] if q['id'] == questions[0]['id'])['answer'] == saved['clarifications'][0]['answer']


def test_selection_revision_fences_switch_away_and_back(harness):
    client, app, _, targets, _ = harness
    cv = ready(harness)
    targets.context_value = context(selection_version=3)
    response = client.post(f"/api/v1/cv/{cv['id']}/clarifications/prepare", json=mutation(cv['version'],
        career_target_id='target-a', career_target_version=1, career_target_selection_version=1))
    assert response.status_code == 409
    assert app.state.repository.get('owner-a', cv['id'])['version'] == cv['version']


def test_target_switch_during_preparation_reports_conflict_without_fact_rollback(harness):
    client, app, _, targets, _ = harness
    cv = ready(harness)
    targets.context_value = context()
    async def changed_selection(authorization): return context(id='target-b', selection_version=2, skill_ids=['skill:unrelated'])
    targets.selected_context = changed_selection
    response = client.post(f"/api/v1/cv/{cv['id']}/clarifications/prepare", json=mutation(cv['version'],
        career_target_id='target-a', career_target_version=1, career_target_selection_version=1))
    assert response.status_code == 409
    stored = app.state.repository.get('owner-a', cv['id'])
    assert stored['effective_version'] == cv['effective_version']
    current = client.get(f"/api/v1/cv/{cv['id']}/clarifications").json()
    assert not current['prepared'] and not current['deferred'] and current['questions'] == []


def test_corrected_sources_hide_pending_questions_and_reextraction_needs_prepare(harness):
    client, app, *_ = harness
    cv, questions = prepare_context(harness, ready(harness))
    project = next(q for q in questions if q['kind'] == 'project')
    edited = client.patch(f"/api/v1/cv/{cv['id']}/items/{project['item_id']}",
                          json=mutation(cv['version'], action='remove')).json()
    path = f"/api/v1/cv/{cv['id']}/clarifications"
    assert project['id'] not in {q['id'] for q in client.get(path).json()['questions']}
    assert upload(client, cv_id=cv['id'], expected_version=edited['version']).status_code == 202
    processing = client.get(path).json()
    assert not processing['prepared'] and processing['questions'] == []
    app.state.worker.run_once()
    refreshed = client.get(path).json()
    assert not refreshed['prepared'] and refreshed['context']['id'] == 'target-a'


def test_context_failure_does_not_return_empty_success_and_other_owner_never_fetches(harness):
    client, _, _, targets, _ = harness
    cv = ready(harness)
    calls = []
    async def unavailable(authorization):
        calls.append(authorization)
        raise CvError('Career context is unavailable. Keep your inputs and retry.', 503)
    targets.selected_context = unavailable
    path = f"/api/v1/cv/{cv['id']}/clarifications"
    assert client.get(path).status_code == 503
    assert calls == ['Bearer owner-a']
    client.headers['Authorization'] = 'Bearer owner-b'
    assert client.get(path).status_code == 404
    assert calls == ['Bearer owner-a']


def test_read_waiting_for_career_uses_the_latest_cv_version(harness):
    from app.schemas.cv import AnswerMutation
    from app.clarification.service import answer
    client, app, _, targets, _ = harness
    cv, questions = prepare_context(harness, ready(harness))
    project = next(question for question in questions if question['kind'] == 'project')
    async def concurrent_answer(authorization):
        answer(app.state.service, 'owner-a', cv['id'], project['id'], AnswerMutation(**mutation(
            cv['version'], action='answer', answer='I built the Python endpoint with supervision.')))
        return context()
    targets.selected_context = concurrent_answer
    result = client.get(f"/api/v1/cv/{cv['id']}/clarifications")
    assert result.status_code == 200, result.text
    saved = client.get('/api/v1/cv/' + cv['id']).json()
    assert result.json()['cv_version'] == saved['version'] > cv['version']
    question = next(question for question in result.json()['questions'] if question['id'] == project['id'])
    assert question['status'] == 'answered' and question['answer'] == 'I built the Python endpoint with supervision.'
