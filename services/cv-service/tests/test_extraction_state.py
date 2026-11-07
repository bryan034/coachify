"""Saved graph state and automatic retries: runs resume, learn from the last failure, and stop at a limit."""
from copy import deepcopy
from dataclasses import replace
import json
import pytest
from app.domain.extraction_errors import ExtractionFailure
from app.core.config import Settings
from app.domain.extraction_retry import failure_for_model, should_auto_retry, waiting_message
from app.domain.model_usage import GLOBAL_DAILY, ModelAdmissionError, OWNER_BUSY, OWNER_DAILY
from app.domain.service import now
from app.repositories.extraction_state import MemoryExtractionStateStore
from app.workers.ingestion import IngestionWorker
from app.workflows.checkpoints import LatestStateSaver
from app.workflows.extraction import ExtractionHarness
from tests.conftest import docx, mutation, upload

SOURCE = 'I built the Python reporting API.'
VALID = {'items': [{'kind': 'project', 'title': 'Reporting API', 'description': SOURCE, 'explicit': True,
                    'skill_names': ['Python'], 'evidence': [{'block_id': 'b1', 'excerpt': SOURCE}]}]}
INVALID = {'items': [{'kind': 'project', 'title': 'Reporting API', 'description': SOURCE, 'explicit': True,
                      'evidence': [{'block_id': 'missing', 'excerpt': SOURCE}]}]}


class Crash(BaseException):
    """Stands in for a process dying: nothing in the service catches it."""


class Run:
    def __init__(self, store, outputs, thread='operation-1:v1'):
        self.parses, self.calls = 0, []
        self.outputs = outputs
        def parse(_):
            self.parses += 1
            return {'blocks': [{'id': 'b1', 'text': SOURCE, 'location': 'Paragraph 1'}]}
        def model(blocks, candidate, feedback):
            self.calls.append('repair' if feedback is not None else 'extract')
            output = self.outputs.pop(0)
            if isinstance(output, BaseException): raise output
            return deepcopy(output), {'provider': 'synthetic', 'model': 'fixture', 'prompt_version': '1', 'schema_version': '1'}
        self.harness = ExtractionHarness('cv-1', parse, model, lambda _: None, thread_id=thread,
            verify_evidence=lambda _, refs: frozenset(), checkpointer=LatestStateSaver(store, 'cv-1', 'owner-a'))

    def run(self):
        return self.harness.run(b'%PDF synthetic original')


def state_of(store, thread='operation-1:v1'):
    return Run(store, [], thread).harness.graph.get_state({'configurable': {'thread_id': thread}})


def test_a_crash_resumes_at_the_interrupted_step_without_repeating_earlier_work():
    store = MemoryExtractionStateStore()
    first = Run(store, [Crash()])
    with pytest.raises(Crash): first.run()
    saved = state_of(store)
    assert saved.next == ('extract',) and saved.values['parsed']['blocks'][0]['text'] == SOURCE
    second = Run(store, [VALID])
    assert second.run()['items'][0]['title'] == 'Reporting API'
    assert (second.parses, second.calls) == (0, ['extract'])


def test_a_crash_during_repair_keeps_the_rejected_output_and_feedback():
    store = MemoryExtractionStateStore()
    first = Run(store, [INVALID, Crash()])
    with pytest.raises(Crash): first.run()
    saved = state_of(store)
    assert saved.next == ('repair',) and saved.values['needs_repair'] is True and saved.values['feedback']
    second = Run(store, [VALID])
    result = second.run()
    assert (second.parses, second.calls) == (0, ['repair'])
    assert result['repair_attempts'] == 1 and second.harness.repair_attempted is True


def test_a_finished_run_stays_saved_and_is_returned_without_model_calls():
    store = MemoryExtractionStateStore()
    first = Run(store, [VALID]).run()
    again = Run(store, [])
    result = again.run()
    assert result['items'] == first['items'] and result['metadata'] == first['metadata']
    assert (again.parses, again.calls) == (0, [])


def test_each_save_replaces_the_last_and_never_stores_the_file_or_an_error():
    store = MemoryExtractionStateStore()
    saved_steps = []
    original_save = store.save
    def save(document):
        saved_steps.append(document['checkpoint_id'])
        original_save(document)
    store.save = save
    with pytest.raises(ExtractionFailure):
        Run(store, [ExtractionFailure('Synthetic SECRET failure.', 'model_request', 'timeout')]).run()
    assert len(saved_steps) >= 2 and len(store.documents) == 1
    row = store.get('cv-1')
    assert row['user_id'] == 'owner-a' and row['checkpoint_id'] == saved_steps[-1]
    assert all(write['channel'] != '__error__' for write in row['writes'])
    assert b'%PDF synthetic original' not in row['checkpoint']['data'] and b'SECRET' not in row['checkpoint']['data']


def test_a_new_thread_or_discarded_state_starts_again_and_replaces_the_old_state():
    store = MemoryExtractionStateStore()
    Run(store, [VALID]).run()
    other = Run(store, [VALID], 'operation-2:v1')
    other.run()
    assert (other.parses, other.calls) == (1, ['extract'])
    assert store.get('cv-1')['thread_id'] == 'operation-2:v1'
    store.discard('cv-1')
    assert store.get('cv-1')['discarded'] is True
    fresh = Run(store, [VALID], 'operation-2:v1')
    fresh.run()
    assert (fresh.parses, fresh.calls) == (1, ['extract'])
    assert 'discarded' not in store.get('cv-1')


def test_a_worker_without_the_lease_does_not_write():
    store = MemoryExtractionStateStore()
    saver = LatestStateSaver(store, 'cv-1', 'owner-a', may_write=lambda: False)
    harness = ExtractionHarness('cv-1', lambda _: {'blocks': [{'id': 'b1', 'text': SOURCE, 'location': 'Paragraph 1'}]},
        lambda *_: (deepcopy(VALID), {'provider': 'synthetic', 'model': 'fixture', 'prompt_version': '1', 'schema_version': '1'}),
        lambda _: None, checkpointer=saver, thread_id='operation-1:v1')
    assert harness.run(b'x')['items']
    assert store.get('cv-1') is None


def counted_worker(app):
    """The worker's parser and extractor, with counts kept for assertions."""
    worker, counts = app.state.worker, {'parse': 0}
    parser = worker.parser
    def counting(*args):
        counts['parse'] += 1
        return parser(*args)
    worker.parser = counting
    return worker, counts


def status(client, identifier):
    return client.get('/api/v1/cv/' + identifier).json()


def retry(client, cv):
    response = client.post(f"/api/v1/cv/operations/{cv['operation_id']}/retry", json=mutation(cv['version']))
    assert response.status_code in (200, 202), response.text


def test_a_process_restart_mid_run_resumes_from_mongodb_state(harness):
    client, app, extractor, *_ = harness
    worker, counts = counted_worker(app)
    real_extract = extractor.extract
    def dies(*args, **kwargs): raise Crash()
    extractor.extract = dies
    cv = upload(client).json()
    with pytest.raises(Crash): worker.run_once()
    assert counts['parse'] == 1
    current = app.state.repository.get('owner-a', cv['id'])
    assert current['operation']['status'] == 'processing'
    expired = deepcopy(current)
    expired['operation']['lease_until'] = 0
    app.state.repository.replace(current, expired)
    extractor.extract = real_extract
    restarted = IngestionWorker(app.state.repository, worker.files, worker.settings, extractor, parser=worker.parser,
                                capacity=worker.capacity, model_usage=worker.model_usage)
    restarted.run_once()
    assert status(client, cv['id'])['status'] == 'ready'
    assert counts['parse'] == 1


def test_a_provider_failure_keeps_state_so_retry_does_not_parse_again(harness):
    client, app, extractor, *_ = harness
    worker, counts = counted_worker(app)
    real_extract = extractor.extract
    def times_out(*args, **kwargs): raise ExtractionFailure('Synthetic timeout.', 'model_request', 'timeout')
    extractor.extract = times_out
    cv = upload(client).json()
    worker.run_once()
    failed = status(client, cv['id'])
    assert failed['status'] == 'failed'
    extractor.extract = real_extract
    retry(client, failed)
    worker.run_once()
    assert status(client, cv['id'])['status'] == 'ready'
    assert counts['parse'] == 1


def test_output_rejected_after_repair_retries_from_the_saved_document_with_the_reason(harness):
    client, app, extractor, *_ = harness
    worker, counts = counted_worker(app)
    real_extract, seen = extractor.extract, []
    invalid = lambda *args, **kwargs: ({'items': [{'kind': 'unknown-kind'}]}, {'provider': 'synthetic', 'model': 'fixture', 'prompt_version': '1', 'schema_version': '1'})
    extractor.extract = invalid
    extractor.repair = invalid
    cv = upload(client).json()
    worker.run_once()
    failed = status(client, cv['id'])
    assert failed['status'] == 'failed'
    def remembers(blocks, **kwargs):
        seen.append(kwargs.get('previous_failure'))
        return real_extract(blocks, **{key: value for key, value in kwargs.items() if key != 'previous_failure'})
    extractor.extract = remembers
    retry(client, failed)
    worker.run_once()
    assert status(client, cv['id'])['status'] == 'ready'
    assert counts['parse'] == 1
    assert seen[0]['category'] == 'schema_validation' and seen[0]['issues']
    assert 'unknown-kind' not in str(seen[0])
    assert 'last_failure' not in app.state.repository.get('owner-a', cv['id'])['operation']


def test_an_unexpected_failure_discards_state_so_retry_starts_from_the_document(harness):
    client, app, extractor, *_ = harness
    worker, counts = counted_worker(app)
    extractor.failure = 'Synthetic unexpected failure'
    cv = upload(client).json()
    worker.run_once()
    failed = status(client, cv['id'])
    assert failed['error']['failure_category'] == 'unexpected_error'
    assert app.state.repository.extraction_states.get(cv['id'])['discarded'] is True
    extractor.failure = None
    retry(client, failed)
    worker.run_once()
    assert status(client, cv['id'])['status'] == 'ready'
    assert counts['parse'] == 2


def auto_retrying(app, retries=2):
    worker = app.state.worker
    worker.settings = replace(worker.settings, extraction_auto_retries=retries)
    return worker


def make_due(app, identifier):
    current = app.state.repository.get('owner-a', identifier)
    assert current['operation']['retry_at'] > now()
    due = deepcopy(current)
    due['operation']['retry_at'] = 0
    app.state.repository.replace(current, due)


def test_the_second_retry_waits_forty_seconds(harness):
    client, app, extractor, *_ = harness
    worker = auto_retrying(app)
    worker.settings = replace(worker.settings, extraction_retry_delays=Settings().extraction_retry_delays)
    def times_out(*args, **kwargs): raise ExtractionFailure('Synthetic timeout.', 'model_request', 'timeout')
    extractor.extract = times_out
    cv = upload(client).json()
    worker.run_once()
    first = app.state.repository.get('owner-a', cv['id'])['operation']['retry_at'] - now()
    assert 15 < first <= 20
    make_due(app, cv['id'])
    worker.run_once()
    second = app.state.repository.get('owner-a', cv['id'])['operation']['retry_at'] - now()
    assert 35 < second <= 40
    assert 'retry 2 of 2' in status(client, cv['id'])['processing_progress']['message']


@pytest.mark.parametrize('category,reason', [
    ('schema_validation', "didn't pass our checks"), ('incomplete_output', 'cut off'),
    ('connection_error', 'connection to the model dropped'), ('provider_http_error', 'busy or unavailable'),
    ('model_admission', 'busy with other requests'), ('invented', 'something went wrong'),
])
def test_the_waiting_message_names_the_error_in_plain_words(category, reason):
    message = waiting_message({'retry_reason': category, 'auto_retries': 1, 'auto_retry_limit': 2})
    assert message.startswith('Hit an error: ') and reason in message and 'retry 1 of 2' in message


def test_a_temporary_failure_retries_automatically_after_a_delay_and_resumes(harness):
    client, app, extractor, *_ = harness
    worker = auto_retrying(app)
    worker, counts = counted_worker(app)
    real_extract, attempts = extractor.extract, []
    def flaky(blocks, **kwargs):
        attempts.append(kwargs.get('previous_failure'))
        if len(attempts) == 1: raise ExtractionFailure('Synthetic timeout.', 'model_request', 'timeout')
        return real_extract(blocks)
    extractor.extract = flaky
    cv = upload(client).json()
    worker.run_once()
    waiting = status(client, cv['id'])
    assert waiting['status'] == 'queued' and waiting['error'] is None
    assert waiting['processing_progress']['message'] == 'Hit an error: the model took too long to respond. Retrying shortly (retry 1 of 2).'
    worker.run_once()  # Not due yet: nothing is called.
    assert len(attempts) == 1
    make_due(app, cv['id'])
    def retrying_then_flaky(blocks, **kwargs):
        during.append(status(client, cv['id'])['processing_progress']['message'])
        return flaky(blocks, **kwargs)
    during = []
    extractor.extract = retrying_then_flaky
    worker.run_once()
    assert during == ['Retry 1 of 2: Identifying your experience and skills.']
    assert status(client, cv['id'])['processing_progress']['message'] == 'Your CV is ready for review.'
    assert status(client, cv['id'])['status'] == 'ready'
    assert counts['parse'] == 1
    assert attempts[0] is None and attempts[1]['category'] == 'timeout' and attempts[1]['issues'] == []
    operation = app.state.repository.get('owner-a', cv['id'])['operation']
    assert not {'retry_at', 'auto_retries', 'auto_retry_limit', 'retry_reason', 'last_failure'} & set(operation)


def test_automatic_retries_stop_at_the_limit_and_a_manual_retry_gets_a_fresh_allowance(harness):
    client, app, extractor, *_ = harness
    worker = auto_retrying(app, 2)
    calls = []
    def always(blocks, **kwargs):
        calls.append(1)
        raise ExtractionFailure('Synthetic timeout.', 'model_request', 'timeout')
    extractor.extract = always
    cv = upload(client).json()
    worker.run_once()
    for _ in range(2):
        assert status(client, cv['id'])['status'] == 'queued'
        make_due(app, cv['id'])
        worker.run_once()
    failed = status(client, cv['id'])
    assert failed['status'] == 'failed' and failed['error']['failure_category'] == 'timeout'
    assert len(calls) == 3
    retry(client, failed)
    worker.run_once()
    assert status(client, cv['id'])['status'] == 'queued' and len(calls) == 4


@pytest.mark.parametrize('failure', [
    ExtractionFailure('Synthetic rejection.', 'model_request', 'provider_http_error', 401, provider_reason='authentication_failed'),
    ExtractionFailure('Synthetic rejection.', 'model_request', 'provider_http_error', 400, provider_reason='schema_rejected'),
    ExtractionFailure('Not configured.', 'model_request', 'not_configured'),
    ModelAdmissionError(OWNER_DAILY),
])
def test_failures_a_retry_cannot_fix_do_not_retry_automatically(harness, failure):
    client, app, extractor, *_ = harness
    worker = auto_retrying(app)
    def rejected(*args, **kwargs): raise failure
    extractor.extract = rejected
    cv = upload(client).json()
    worker.run_once()
    assert status(client, cv['id'])['status'] == 'failed'


@pytest.mark.parametrize('code,expected', [(402, 'failed'), ('insufficient_quota', 'failed'),
                                           (429, 'queued'), (503, 'queued')])
def test_embedded_provider_quota_respects_worker_auto_retry_policy(harness, monkeypatch, code, expected):
    import httpx
    from tests.test_extraction_failures import provider, PRIVATE
    client, app, *_ = harness
    calls = []
    def reject(request):
        calls.append(request)
        return httpx.Response(200, json={'error': {'code': code, 'message': PRIVATE}})
    app.state.worker.extractor = provider(monkeypatch, reject)
    worker = auto_retrying(app)
    cv = upload(client).json()
    worker.run_once()
    result = status(client, cv['id'])
    assert result['status'] == expected and len(calls) == 1
    if expected == 'failed':
        assert result['error']['provider_status_code'] is None
        assert result['error']['provider_reason'] == 'rate_limit_or_quota'
        assert PRIVATE not in json.dumps(result)
    else:
        assert app.state.repository.get('owner-a', cv['id'])['operation']['auto_retries'] == 1


@pytest.mark.parametrize('failure,auto', [
    ({'failure_category': 'schema_validation'}, True), ({'failure_category': 'incomplete_output'}, True),
    ({'failure_category': 'provider_http_error', 'provider_reason': 'rate_limit_or_quota'}, True),
    ({'failure_category': 'provider_http_error', 'provider_reason': 'provider_unavailable'}, True),
    ({'failure_category': 'model_admission', 'message': OWNER_BUSY}, True),
    ({'failure_category': 'model_admission', 'message': GLOBAL_DAILY}, False),
    ({'failure_category': 'invalid_document'}, False), ({'failure_category': 'unexpected_error'}, False),
    ({'failure_category': 'source_changed'}, False), ({'failure_category': 'history_capacity'}, False),
])
def test_which_failures_retry_automatically(failure, auto):
    assert should_auto_retry(failure) is auto


def test_only_fixed_text_and_allowlisted_issues_reach_the_model():
    told = failure_for_model({'failure_category': 'provider_http_error', 'message': 'PRIVATE provider prose'})
    assert 'PRIVATE' not in str(told) and told['issues'] == []
    assert failure_for_model({'failure_category': 'model_admission'}) is None
    assert failure_for_model({'failure_category': 'invalid_document'}) is None


def test_the_model_sees_the_previous_failure_in_the_real_request(harness, monkeypatch):
    from tests.test_extraction_harness import candidates, read_result, setup_provider
    invalid, valid = candidates()
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, invalid, valid])
    worker = auto_retrying(app)
    worker.run_once()
    assert read_result(client, queued)['status'] == 'queued' and len(calls) == 2
    assert 'previous_attempt_failure' not in json.loads(calls[0]['messages'][1]['content'])
    make_due(app, queued['id'])
    worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and len(calls) == 3
    request = json.loads(calls[2]['messages'][1]['content'])
    told = request['previous_attempt_failure']
    assert told['category'] == 'schema_validation' and told['issues']
    assert 'rejected_candidate' not in request and 'An earlier attempt' in calls[2]['messages'][0]['content']
    assert 'D' * 100 not in json.dumps(told)


def test_state_persists_after_success_and_a_reupload_replaces_it(harness):
    client, app, *_ = harness
    worker = app.state.worker
    cv = upload(client).json()
    worker.run_once()
    states = app.state.repository.extraction_states
    first = states.get(cv['id'])
    assert first and first['user_id'] == 'owner-a' and first['thread_id'].startswith(cv['operation_id'])
    latest = status(client, cv['id'])
    assert upload(client, docx(), cv_id=cv['id'], expected_version=latest['version']).status_code == 202
    worker.run_once()
    assert states.get(cv['id'])['thread_id'] != first['thread_id']


def test_deleting_a_cv_erases_its_saved_state(harness):
    client, app, *_ = harness
    cv = upload(client).json()
    app.state.worker.run_once()
    states = app.state.repository.extraction_states
    assert states.get(cv['id'])
    latest = status(client, cv['id'])
    assert client.request('DELETE', '/api/v1/cv/' + cv['id'], json=mutation(latest['version'])).status_code == 200
    assert states.get(cv['id']) is None


def test_a_cv_deleted_mid_run_leaves_no_state_behind(harness):
    client, app, extractor, *_ = harness
    states = app.state.repository.extraction_states
    real_extract = extractor.extract
    cv = upload(client).json()
    def delete_then_answer(*args, **kwargs):
        latest = status(client, cv['id'])
        assert client.request('DELETE', '/api/v1/cv/' + cv['id'], json=mutation(latest['version'])).status_code == 200
        return real_extract(*args, **kwargs)
    extractor.extract = delete_then_answer
    app.state.worker.run_once()
    assert states.get(cv['id']) is None
