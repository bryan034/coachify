"""Real LangGraph orchestration with synthetic provider/document boundaries."""
from copy import deepcopy
from dataclasses import replace
import json
import logging

import httpx
import pytest
from pydantic import ValidationError

from app.clients.extractor import Extractor
from app.clients.extraction_schema import extraction_schema
from app.domain.extraction_feedback import feedback_for
from app.domain.service import now
from app.schemas.cv import Extraction, ExtractedItem, SourceExcerpt
from app.workflows.extraction import ExtractionHarness
from tests.conftest import docx, upload
from tests.test_extraction_failures import provider
from tests.test_model_usage import count


SOURCES = ['Synthetic University (2024 to 2025). ' + 'A' * 510,
           'Project Finch (2023 to present): used Python.']


def candidates():
    invalid = {'items': [
        {'kind': 'education', 'title': 'Synthetic University', 'description': 'Study record',
         'explicit': True, 'start_date': '2024', 'end_date': '2025',
         'evidence': [{'block_id': 'b1', 'excerpt': SOURCES[0]}]},
        {'kind': 'project', 'title': 'Project Finch', 'description': 'Used Python',
         'explicit': True, 'skill_names': ['Python'], 'start_date': '2023', 'end_date': '2024', 'ongoing': True,
         'evidence': [{'block_id': 'b2', 'excerpt': SOURCES[1]}]},
    ]}
    valid = deepcopy(invalid)
    valid['items'][0]['evidence'][0]['excerpt'] = 'Synthetic University (2024 to 2025).'
    valid['items'][1]['end_date'] = None
    return invalid, valid


def completion(value):
    return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
        'message': {'content': json.dumps(value)}}]})


def setup_provider(harness, monkeypatch, responses, callback=None):
    client, app, *_ = harness
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        if callback: callback(len(calls))
        result = responses[len(calls) - 1]
        return result if isinstance(result, httpx.Response) else completion(result)
    app.state.worker.extractor = provider(monkeypatch, respond)
    queued = upload(client, docx(SOURCES)).json()
    return client, app, queued, calls


def read_result(client, queued):
    return client.get('/api/v1/cv/operations/' + queued['operation_id']).json()


def test_schema_contains_decoding_constraints_and_no_optional_object_fields():
    schema = extraction_schema()
    assert '$ref' not in json.dumps(schema) and '$defs' not in schema
    def check(value):
        if isinstance(value, dict):
            assert 'default' not in value
            if value.get('type') == 'object':
                assert value['additionalProperties'] is False
                assert set(value['required']) == set(value['properties'])
            for item in value.values(): check(item)
        elif isinstance(value, list):
            for item in value: check(item)
    check(schema)
    item = schema['properties']['items']['items']
    assert set(item['properties']) == set(ExtractedItem.model_fields)
    assert set(item['properties']['evidence']['items']['properties']) == set(SourceExcerpt.model_fields)
    assert 'title' in item['required'] and item['properties']['title']['type'] == 'string'
    assert schema['properties']['items']['minItems'] == 1
    assert schema['properties']['items']['maxItems'] == 160
    assert item['properties']['evidence']['maxItems'] == 6
    assert item['properties']['evidence']['items']['properties']['excerpt']['maxLength'] == 500
    assert item['properties']['explicit']['type'] == 'boolean'
    assert item['properties']['kind']['enum'] == ['education', 'experience', 'project', 'skill']
    assert {'type': 'null'} in item['properties']['end_date']['anyOf']


def test_repair_recovers_overlong_quotes_and_conflicting_dates(harness, monkeypatch, caplog):
    invalid, valid = candidates()
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, valid])
    with caplog.at_level(logging.WARNING): app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and result['error'] is None
    assert result['extraction']['workflow_version'] == 'cv-extraction-1'
    assert result['extraction']['repair_attempts'] == 1
    assert result['extraction']['response_mode'] == 'json_schema'
    assert result['extraction_version'] == 1 and len(result['items']) == 2
    assert result['items'][1]['ongoing'] and result['items'][1]['end_date'] is None
    assert [item['title'] for item in result['items']] == ['Synthetic University', 'Project Finch']
    assert len(calls) == count(app.state.repository) == 2
    assert calls[0]['response_format'] == calls[1]['response_format']
    assert calls[0]['response_format']['json_schema']['strict'] is True
    repair = json.loads(calls[1]['messages'][1]['content'])
    assert repair['rejected_candidate'] == invalid
    assert [block['text'] for block in repair['source_blocks']] == SOURCES
    assert any(issue['field'] == 'items[0].evidence[0].excerpt' for issue in repair['validation_feedback'])
    assert any('ongoing=true requires end_date=null' in issue['guidance'] for issue in repair['validation_feedback'])
    saved = app.state.repository.get('owner-a', queued['id'])
    assert all(key not in saved for key in ('original', 'parsed', 'candidate', 'feedback', 'validation_error'))
    assert not any('Synthetic University' in record.message for record in caplog.records)


def test_valid_first_pass_needs_no_repair(harness, monkeypatch):
    _, valid = candidates()
    client, app, queued, calls = setup_provider(harness, monkeypatch, [valid])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and result['extraction']['repair_attempts'] == 0
    assert len(calls) == count(app.state.repository) == 1


@pytest.mark.parametrize('failure', ['schema', 'evidence'])
def test_failed_repair_is_bounded_and_cannot_publish(harness, monkeypatch, failure):
    invalid, valid = candidates()
    second = invalid if failure == 'schema' else deepcopy(valid)
    if failure == 'evidence': second['items'][0]['evidence'][0]['excerpt'] = 'Invented quotation'
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, second])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'failed' and result['error']['repair_attempted']
    assert result['error']['failure_stage'] == 'extraction_validation'
    assert result['error']['failure_category'] == ('schema_validation' if failure == 'schema' else 'evidence_validation')
    assert len(calls) == count(app.state.repository) == 2
    assert result['items'] == [] and result['extraction_version'] == 0


def test_evidence_failure_also_receives_source_specific_repair(harness, monkeypatch):
    _, valid = candidates()
    invalid = deepcopy(valid)
    invalid['items'][1]['skill_names'] = ['Python', 'Invented skill']
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, valid])
    app.state.worker.run_once()
    assert read_result(client, queued)['status'] == 'ready'
    feedback = json.loads(calls[1]['messages'][1]['content'])['validation_feedback']
    assert feedback[0]['field'] == 'items[1]' and feedback[0]['issue'] == 'literal_skill'


def test_provider_failure_during_repair_keeps_status_and_stage(harness, monkeypatch):
    invalid, _ = candidates()
    client, app, queued, calls = setup_provider(harness, monkeypatch,
        [invalid, httpx.Response(503, text='PRIVATE_PROVIDER_PROSE')])
    app.state.worker.run_once()
    error = read_result(client, queued)['error']
    assert error['failure_stage'] == 'model_repair'
    assert error['failure_category'] == 'provider_http_error' and error['provider_status_code'] == 503
    assert error['repair_attempted'] and len(calls) == count(app.state.repository) == 2
    assert 'PRIVATE' not in json.dumps(error)


def test_repair_cannot_bypass_daily_budget(harness, monkeypatch):
    invalid, _ = candidates()
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid])
    app.state.worker.model_usage.settings = replace(app.state.settings, model_calls_per_owner_per_day=1)
    app.state.worker.run_once()
    error = read_result(client, queued)['error']
    assert error['failure_stage'] == 'model_repair' and error['failure_category'] == 'model_admission'
    assert error['repair_attempted'] and len(calls) == count(app.state.repository) == 1


@pytest.mark.parametrize('change', ['short_lease', 'lost_lease', 'expired_lease'])
def test_repair_requires_time_and_live_lease(harness, monkeypatch, change):
    invalid, _ = candidates()
    def change_lease(attempt):
        if attempt != 1: return
        old = app.state.repository.get('owner-a', queued['id'])
        current = deepcopy(old)
        if change == 'lost_lease': current['operation']['lease_token'] = 'new-worker-token'
        else: current['operation']['lease_until'] = now() + (9 if change == 'short_lease' else -1)
        current['revision'] += 1
        app.state.repository.replace(old, current)
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid], change_lease)
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert len(calls) == count(app.state.repository) == 1
    assert result['items'] == [] and result['extraction_version'] == 0
    if change == 'short_lease':
        assert result['status'] == 'failed' and result['error']['failure_category'] == 'timeout'
        assert result['error']['failure_stage'] == 'model_repair'
    else:
        assert result['status'] == 'processing' and result['error'] is None


def test_repaired_result_cannot_publish_after_lease_loss(harness, monkeypatch):
    invalid, valid = candidates()
    def lose_lease(attempt):
        if attempt != 2: return
        old = app.state.repository.get('owner-a', queued['id'])
        current = deepcopy(old)
        current['operation']['lease_token'] = 'new-worker-token'
        current['revision'] += 1
        app.state.repository.replace(old, current)
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, valid], lose_lease)
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert len(calls) == 2 and result['status'] == 'processing'
    assert result['items'] == [] and result['extraction_version'] == 0


def test_feedback_excludes_unknown_field_names_and_values():
    invalid, _ = candidates()
    invalid['items'][0]['PRIVATE_FIELD'] = 'PRIVATE_VALUE'
    with pytest.raises(ValidationError) as caught: Extraction.model_validate(invalid)
    feedback = feedback_for(caught.value)
    assert 'PRIVATE' not in json.dumps(feedback)
    assert len(feedback) <= 16 and any(issue['field'].endswith('.other') for issue in feedback)


def test_graph_disables_tracing_even_under_enabled_parent(monkeypatch):
    from langsmith import tracing_context, get_tracing_context
    _, valid = candidates()
    stages, tracing = [], []
    def observe(stage):
        stages.append(stage)
        tracing.append(get_tracing_context()['enabled'])
    graph = ExtractionHarness('synthetic-id',
        lambda original: {'blocks': [{'id': f'b{i+1}', 'text': text, 'location': 'Synthetic'} for i, text in enumerate(SOURCES)]},
        lambda *args: (valid, {}), observe)
    assert graph.graph.checkpointer is None
    with tracing_context(enabled=True): result = graph.run(b'synthetic')
    assert stages == ['document_parse', 'model_request', 'extraction_validation']
    assert all(value is False for value in tracing) and result['repair_attempts'] == 0


def test_explicit_json_mode_is_not_silently_selected(monkeypatch):
    monkeypatch.setenv('CV_LLM_RESPONSE_MODE', 'json_object')
    calls = []
    def respond(request):
        calls.append(json.loads(request.content))
        return completion({'items': []})
    extractor = provider(monkeypatch, respond)
    _, metadata = extractor.extract([])
    assert calls[0]['response_format'] == {'type': 'json_object'}
    assert metadata['response_mode'] == 'json_object'
    monkeypatch.setenv('CV_LLM_RESPONSE_MODE', 'invalid-mode')
    with pytest.raises(RuntimeError, match='CV_LLM_RESPONSE_MODE'): Extractor()
