"""Persisted provider-attempt budgets and OS-held concurrency, without providers."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import fcntl
import hashlib
import multiprocessing
import os
from threading import Barrier, Event
from uuid import uuid4
import pytest
from pymongo.errors import AutoReconnect
from app.core.config import Settings
from app.domain.model_usage import ModelAdmissionError, ModelUsage
from tests.conftest import mutation, ready, upload
from tests.test_conversation import Router, source_chat
from tests.test_conversation_security import open_chat, send, settled, PREFIX
from tests.test_interpretation import project_question, PERSONAL


def usage(repository, directory, **settings):
    return ModelUsage(repository.model_usage, directory, replace(Settings(), **settings))


def count(repository, owner=None):
    document = repository.model_usage.read()
    if document is None: return 0
    return document['owners'].get(hashlib.sha256(owner.encode()).hexdigest(), 0) if owner else document['total']


def test_daily_owner_and_global_budgets_survive_new_instances(repository, tmp_path):
    limits = {'model_calls_per_owner_per_day': 2, 'model_calls_global_per_day': 3}
    first = usage(repository, tmp_path, **limits)
    assert first.run('owner-a', lambda: 'first') == 'first'
    restarted = usage(repository, tmp_path, **limits)
    assert restarted.run('owner-a', lambda: 'second') == 'second'
    with pytest.raises(ModelAdmissionError, match='Your daily'): first.run('owner-a', lambda: pytest.fail('Quota bypass'))
    assert restarted.run('owner-b', lambda: 'third') == 'third'
    with pytest.raises(ModelAdmissionError, match='daily CV model-call capacity'):
        first.run('owner-c', lambda: pytest.fail('Global quota bypass'))
    assert count(repository) == 3 and count(repository, 'owner-a') == 2
    assert 'owner-a' not in str(repository.model_usage.read())


def test_concurrent_budget_cas_has_no_extra_provider_calls(repository, tmp_path):
    limits = {'model_calls_per_owner_per_day': 1, 'model_calls_global_per_day': 2,
              'model_concurrent_global': 8}
    instances = [usage(repository, tmp_path, **limits) for _ in range(8)]
    gate = Barrier(8)
    def attempt(index):
        gate.wait(timeout=5)
        try: return instances[index].run('owner-' + str(index), lambda: True)
        except ModelAdmissionError: return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(8))) == 2
    assert count(repository) == 2


def test_failed_attempts_count_and_disabled_configuration_is_free(repository, tmp_path):
    guard = usage(repository, tmp_path)
    def fail(): raise ValueError('Synthetic provider failure')
    with pytest.raises(ValueError, match='Synthetic'): guard.run('owner-a', fail)
    assert count(repository) == 1
    with pytest.raises(ValueError, match='Synthetic'): guard.run('owner-a', fail, configured=False)
    assert count(repository) == 1


def test_ambiguous_committed_counter_write_fails_closed_without_refund(repository, tmp_path, monkeypatch):
    guard = usage(repository, tmp_path)
    store_replace = repository.model_usage.replace
    calls = []
    def lost_ack(previous, document):
        assert store_replace(previous, document)
        raise AutoReconnect('Synthetic committed acknowledgement loss')
    monkeypatch.setattr(repository.model_usage, 'replace', lost_ack)
    with pytest.raises(ModelAdmissionError, match='could not be reserved'):
        guard.run('owner-a', lambda: calls.append('provider'))
    assert calls == [] and count(repository, 'owner-a') == 1
    monkeypatch.setattr(repository.model_usage, 'replace', store_replace)
    guard.run('owner-a', lambda: calls.append('provider'))
    assert calls == ['provider'] and count(repository, 'owner-a') == 2


def test_day_rollover_keeps_revision_monotonic_and_clock_rollback_does_not_reset(repository, tmp_path):
    guard = usage(repository, tmp_path, model_calls_per_owner_per_day=1)
    guard.day = lambda: '2026-10-29'
    guard.run('owner-a', lambda: None)
    initial = repository.model_usage.read()['revision']
    guard.day = lambda: '2026-10-28'
    with pytest.raises(ModelAdmissionError, match='Your daily'): guard.run('owner-a', lambda: None)
    assert repository.model_usage.read()['day'] == '2026-10-29'
    guard.day = lambda: '2026-10-30'
    guard.run('owner-a', lambda: None)
    state = repository.model_usage.read()
    assert state['total'] == 1 and state['day'] == '2026-10-30' and state['revision'] > initial


def test_owner_map_cap_cannot_be_evaded_by_new_owner_ids(repository, tmp_path, monkeypatch):
    monkeypatch.setattr('app.domain.model_usage.MAX_OWNER_ENTRIES', 2)
    guard = usage(repository, tmp_path)
    guard.run('owner-a', lambda: None)
    guard.run('owner-b', lambda: None)
    with pytest.raises(ModelAdmissionError): guard.run('owner-c', lambda: None)
    guard.run('owner-a', lambda: None)
    assert len(repository.model_usage.read()['owners']) == 2 and count(repository) == 3


def test_counter_contention_is_bounded_and_releases_slot(repository, tmp_path, monkeypatch):
    guard = usage(repository, tmp_path)
    original = repository.model_usage.replace
    attempts = []
    def conflict(*args):
        attempts.append(1)
        return False
    monkeypatch.setattr(repository.model_usage, 'replace', conflict)
    with pytest.raises(ModelAdmissionError): guard.run('owner-a', lambda: pytest.fail('No counter committed'))
    assert len(attempts) == 30 and count(repository) == 0
    monkeypatch.setattr(repository.model_usage, 'replace', original)
    assert guard.run('owner-a', lambda: 'recovered') == 'recovered'


def test_one_owner_cannot_take_all_slots_and_busy_denials_are_free(repository, tmp_path):
    first, second = usage(repository, tmp_path), usage(repository, tmp_path)
    entered, release = Event(), Event()
    def blocked():
        entered.set()
        assert release.wait(5)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(first.run, 'owner-a', blocked)
        try:
            assert entered.wait(5)
            with pytest.raises(ModelAdmissionError, match='account is still running'):
                second.run('owner-a', lambda: pytest.fail('Owner concurrency bypass'))
            assert second.run('owner-b', lambda: 'independent') == 'independent'
            assert count(repository, 'owner-a') == 1 and count(repository, 'owner-b') == 1
        finally: release.set()
        pending.result(timeout=5)


def test_global_slot_ceiling_and_private_fixed_metadata(repository, tmp_path):
    guard = usage(repository, tmp_path)
    entered, release = [Event() for _ in range(3)], Event()
    def blocked(index):
        entered[index].set()
        assert release.wait(5)
    with ThreadPoolExecutor(max_workers=3) as executor:
        pending = [executor.submit(guard.run, 'owner-' + str(i), blocked, i) for i in range(3)]
        try:
            assert all(event.wait(5) for event in entered)
            with pytest.raises(ModelAdmissionError, match='processing is busy'):
                guard.run('owner-other', lambda: pytest.fail('Global concurrency bypass'))
            assert count(repository) == 3 and count(repository, 'owner-other') == 0
        finally: release.set()
        for future in pending: future.result(timeout=5)
    assert guard.run('owner-other', lambda: 'released') == 'released'
    assert {path.name for path in guard.directory.iterdir()} == {'gate', '0', '1', '2'}
    assert guard.directory.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in guard.directory.iterdir())


def test_inconsistent_counter_fails_closed_without_disclosing_state(repository, tmp_path):
    corrupted = {'_id': 'daily', 'revision': 1, 'day': '2026-10-29', 'total': 99, 'owners': {}}
    assert repository.model_usage.replace(None, corrupted)
    with pytest.raises(ModelAdmissionError, match='could not be reserved'):
        usage(repository, tmp_path).run('owner-a', lambda: pytest.fail('Corrupt counter bypass'))
    assert repository.model_usage.read() == corrupted


def test_busy_slot_with_malformed_owner_tag_fails_closed(repository, tmp_path):
    guard = usage(repository, tmp_path)
    descriptor = os.open(guard.directory / '0', os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    os.write(descriptor, b'unknown')
    try:
        with pytest.raises(ModelAdmissionError, match='could not be reserved'):
            guard.run('owner-a', lambda: pytest.fail('Cannot prove owner fairness'))
        assert count(repository) == 0
    finally: os.close(descriptor)
    # An unlocked stale tag is safe to replace while owning the slot and gate.
    assert guard.run('owner-a', lambda: 'recovered') == 'recovered'
    assert (guard.directory / '0').read_bytes() == hashlib.sha256(b'owner-a').hexdigest().encode()
    assert len(list(guard.directory.iterdir())) == 4


def test_async_cancellation_does_not_release_a_running_provider_thread(repository, tmp_path):
    guard = usage(repository, tmp_path)
    entered, release, finished = Event(), Event(), Event()
    def blocked():
        entered.set()
        try: assert release.wait(5)
        finally: finished.set()
    async def scenario():
        task = asyncio.create_task(asyncio.to_thread(guard.run, 'owner-a', blocked))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            with pytest.raises(ModelAdmissionError, match='account is still running'):
                await asyncio.to_thread(guard.run, 'owner-a', lambda: None)
            assert await asyncio.to_thread(guard.run, 'owner-b', lambda: 'other') == 'other'
        finally: release.set()
        assert await asyncio.to_thread(finished.wait, 5)
    asyncio.run(scenario())
    assert count(repository, 'owner-a') == 1


def child_provider(directory, entered):
    from time import sleep
    from app.repositories.model_usage import MemoryModelUsageStore
    guard = ModelUsage(MemoryModelUsageStore(), directory, Settings())
    def hold():
        entered.set()
        sleep(20)
    guard.run('owner-a', hold)


def test_process_death_releases_slot_without_an_expiring_lease(repository, tmp_path):
    context = multiprocessing.get_context('spawn')
    entered = context.Event()
    process = context.Process(target=child_provider, args=(str(tmp_path), entered))
    process.start()
    guard = usage(repository, tmp_path)
    try:
        assert entered.wait(10)
        with pytest.raises(ModelAdmissionError, match='account is still running'): guard.run('owner-a', lambda: None)
        process.terminate()
        process.join(10)
        assert not process.is_alive()
        assert guard.run('owner-a', lambda: 'after crash') == 'after crash'
    finally:
        if process.is_alive(): process.terminate()
        process.join(10)


def test_all_three_provider_paths_share_the_owner_budget(harness):
    client, app, *_ = harness
    cv, question, answer_path = project_question(harness)
    guard = app.state.service.model_usage
    guard.settings = replace(app.state.settings, model_calls_per_owner_per_day=1)
    assert count(app.state.repository, 'owner-a') == 1  # extraction
    router = app.state.conversations.provider = Router()
    chat = open_chat(client, cv['id'])
    chat = send(client, chat, 'Why are you asking this question?')
    assert router.calls == []
    assert any('daily CV model-call limit' in str(action.get('error'))
               for message in chat['messages'] for action in message['actions'])
    assert any(message['text'] == 'Why are you asking this question?' for message in chat['messages'])
    answered = client.put(answer_path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
    saved_question = next(q for q in answered['clarifications'] if q['id'] == question['id'])
    assert saved_question['answer'] == PERSONAL and saved_question['interpretation_status'] == 'failed'
    assert 'daily CV model-call limit' in saved_question['interpretation_error']
    assert app.state.interpreter.calls == 0
    retry = mutation(answered['version'])
    response = client.post(answer_path + '/interpretation/retry', json=retry)
    assert response.status_code == 200
    replay = client.post(answer_path + '/interpretation/retry', json=retry)
    assert replay.status_code == 200 and count(app.state.repository, 'owner-a') == 1
    another = upload(client).json()
    app.state.worker.run_once()
    app.state.worker.run_once()
    failed = client.get('/api/v1/cv/' + another['id']).json()
    assert failed['status'] == 'failed' and 'daily CV model-call limit' in failed['error']['message']
    assert app.state.files.exists(another['id']) and count(app.state.repository, 'owner-a') == 1


def test_disabled_chat_interpreter_does_not_consume_an_extra_attempt(harness):
    client, app, *_ = harness
    _, question, chat = source_chat(harness)
    app.state.conversations.provider = Router([{'kind': 'clarify', 'item_id': question['item_id'],
        'question_id': question['id'], 'excerpt': PERSONAL}])
    app.state.interpreter.configured = False
    app.state.interpreter.failure = 'Interpretation is not configured.'
    before = count(app.state.repository)
    chat = send(client, chat, PERSONAL)
    assert count(app.state.repository) == before + 1  # routing only
    assert app.state.interpreter.calls == 1
    assert any(action['status'] == 'failed' for message in chat['messages'] for action in message['actions'])


def test_chat_receipt_replay_and_local_commands_do_not_consume_calls(harness):
    client, app, *_ = harness
    chat = open_chat(client)
    app.state.conversations.provider = Router()
    request = {'text': 'Explain the process', 'mutation_id': str(uuid4()), 'expected_revision': chat['revision']}
    assert client.post(PREFIX + '/' + chat['id'] + '/messages', json=request).status_code == 200
    settled(client, chat['id'])
    assert count(app.state.repository) == 1
    assert client.post(PREFIX + '/' + chat['id'] + '/messages', json=request).status_code == 200
    assert client.get(PREFIX + '/' + chat['id']).status_code == 200
    current = client.get(PREFIX + '/' + chat['id']).json()
    send(client, current, 'Review', command='review')
    assert count(app.state.repository) == 1


def test_parser_failures_do_not_consume_model_calls(harness):
    client, app, *_ = harness
    saved = upload(client, b'PK\x03\x04broken synthetic archive').json()
    app.state.worker.run_once()
    assert client.get('/api/v1/cv/' + saved['id']).json()['status'] == 'failed'
    assert count(app.state.repository) == 0


def test_routing_blocks_same_owner_extraction_and_answers_but_other_owner_runs(harness):
    client, app, *_ = harness
    cv, question, answer_path = project_question(harness)
    chat = open_chat(client, cv['id'])
    router = app.state.conversations.provider = Router()
    entered, release = Event(), Event()
    def hold():
        entered.set()
        assert release.wait(5)
    router.callback = hold
    response = client.post(PREFIX + '/' + chat['id'] + '/messages', json={
        'text': 'Explain this source', 'mutation_id': str(uuid4()), 'expected_revision': chat['revision']})
    assert response.status_code == 200
    try:
        assert entered.wait(5)
        answered = client.put(answer_path, json=mutation(cv['version'], action='answer', answer=PERSONAL)).json()
        saved = next(q for q in answered['clarifications'] if q['id'] == question['id'])
        assert saved['answer'] == PERSONAL and 'account is still running' in saved['interpretation_error']
        assert app.state.interpreter.calls == 0
        own_upload = upload(client).json()
        app.state.worker.run_once()
        app.state.worker.run_once()
        failed = client.get('/api/v1/cv/' + own_upload['id']).json()
        assert failed['status'] == 'failed' and 'account is still running' in failed['error']['message']
        client.headers['Authorization'] = 'Bearer owner-b'
        other = upload(client).json()
        app.state.worker.run_once()
        app.state.worker.run_once()
        assert client.get('/api/v1/cv/' + other['id']).json()['status'] == 'ready'
        assert count(app.state.repository, 'owner-a') == 2
        assert count(app.state.repository, 'owner-b') == 1
    finally:
        release.set()
        client.headers['Authorization'] = 'Bearer owner-a'
    settled(client, chat['id'])


@pytest.mark.parametrize('name,value', [
    ('CV_MODEL_CONCURRENT_GLOBAL', '33'), ('CV_MODEL_CONCURRENT_GLOBAL', '1'),
    ('CV_MODEL_CONCURRENT_PER_OWNER', '3'), ('CV_MODEL_CALLS_PER_OWNER_PER_DAY', '0'),
    ('CV_MODEL_CALLS_GLOBAL_PER_DAY', '1'),
])
def test_model_configuration_rejects_unbounded_or_unfair_limits(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError): Settings.environment()
