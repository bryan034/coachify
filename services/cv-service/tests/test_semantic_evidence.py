"""Synthetic semantic verdicts exercise grounding, admission and publication."""
from dataclasses import replace
import json
import pytest
from tests.test_extraction_harness import candidates, setup_provider, read_result


def test_paraphrase_and_other_information_accept_supported_meaning(harness, monkeypatch):
    _, value = candidates()
    summary = 'Studied at Synthetic University between 2024 and 2025.'
    value['items'][0]['evidence'] = [{'block_id': 'b1', 'excerpt': summary}]
    value['other_information'] = [{'block_id': 'b1', 'excerpt': 'The study period was 2024–2025.'}]
    client, app, queued, calls = setup_provider(harness, monkeypatch, [value, {'supported': [0, 1]}])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and result['extraction']['repair_attempts'] == 0
    assert result['items'][0]['evidence'][0]['excerpt'] == summary
    assert result['other_information'][0]['excerpt'] == value['other_information'][0]['excerpt']
    assert len(calls) == 2
    request = json.loads(calls[1]['messages'][1]['content'])
    assert [block['id'] for block in request['source_blocks']] == ['b1']
    assert [ref['index'] for ref in request['summaries']] == [0, 1]
    saved = app.state.repository.get('owner-a', queued['id'])
    assert 'source_blocks' not in saved and 'semantic_support' not in saved


def test_formatting_differences_need_no_semantic_model_call(harness, monkeypatch):
    _, value = candidates()
    value['items'][1]['evidence'][0]['excerpt'] = 'PROJECT  FINCH\n(2023 to present): used Python.'
    client, app, queued, calls = setup_provider(harness, monkeypatch, [value])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and len(calls) == 1


@pytest.mark.parametrize('summary', ['The project never used Python.', 'The project lasted 99 years.',
                                     'I independently built everything without help.'])
def test_unsupported_semantic_verdict_requires_repair_not_publication(harness, monkeypatch, summary):
    _, valid = candidates()
    from copy import deepcopy
    invalid = deepcopy(valid)
    invalid['items'][1]['evidence'][0]['excerpt'] = summary
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, {'supported': []}, valid])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and result['extraction']['repair_attempts'] == 1
    assert result['items'][1]['evidence'][0]['excerpt'] != summary
    assert len(calls) == 3


@pytest.mark.parametrize('verdict', [{'supported': [True]}, {'supported': [-1]}, {'supported': [7]},
                                    {'supported': [0, 0]}, {'supported': [0], 'extra': True}, {}])
def test_malformed_verdict_never_approves_evidence(harness, monkeypatch, verdict):
    _, value = candidates()
    value['items'][0]['evidence'][0]['excerpt'] = 'Studied at Synthetic University.'
    client, app, queued, calls = setup_provider(harness, monkeypatch, [value, verdict])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'failed' and result['items'] == []
    assert result['error']['failure_category'] == 'invalid_response'
    assert not result['error']['repair_attempted'] and len(calls) == 2


def test_semantic_verification_uses_shared_daily_budget(harness, monkeypatch):
    _, value = candidates()
    value['items'][0]['evidence'][0]['excerpt'] = 'Studied at Synthetic University.'
    client, app, queued, calls = setup_provider(harness, monkeypatch, [value])
    app.state.worker.model_usage.settings = replace(app.state.settings, model_calls_per_owner_per_day=1)
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'failed' and result['items'] == []
    assert result['error']['failure_category'] == 'model_admission' and len(calls) == 1
    assert not result['error']['repair_attempted']


def test_approved_long_summary_is_split_without_losing_approval_scope(harness, monkeypatch):
    _, value = candidates()
    summary = ('Synthetic University study record. ' * 17) + 'The period was 2024 to 2025.'
    value['items'][0]['evidence'] = [{'block_id': 'b1', 'excerpt': summary}]
    client, app, queued, calls = setup_provider(harness, monkeypatch, [value, {'supported': [0]}])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and len(calls) == 2
    refs = result['items'][0]['evidence']
    assert len(refs) > 1 and all(len(ref['excerpt']) <= 500 for ref in refs)
    assert ''.join(ref['excerpt'] for ref in refs) == summary


@pytest.mark.parametrize('lose_at', [1, 2])
def test_semantic_verification_cannot_call_or_publish_after_lease_loss(harness, monkeypatch, lose_at):
    from copy import deepcopy
    _, value = candidates()
    value['items'][0]['evidence'][0]['excerpt'] = 'Studied at Synthetic University.'
    def lose_lease(attempt):
        if attempt != lose_at: return
        old = app.state.repository.get('owner-a', queued['id'])
        current = deepcopy(old)
        current['operation']['lease_token'] = 'new-worker-token'
        current['revision'] += 1
        app.state.repository.replace(old, current)
    client, app, queued, calls = setup_provider(harness, monkeypatch, [value, {'supported': [0]}], lose_lease)
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert len(calls) == lose_at and result['status'] == 'processing'
    assert result['items'] == [] and result['extraction_version'] == 0
