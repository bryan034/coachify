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
from app.repositories.extraction_state import MemoryExtractionStateStore
from app.workflows.checkpoints import LatestStateSaver
from app.workflows.extraction import ExtractionHarness


def saver():
    return LatestStateSaver(MemoryExtractionStateStore(), 'synthetic-cv', 'owner-a')
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
    invalid['items'][0]['description'] = 'D' * 4001
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
    assert 'maxLength' not in item['properties']['evidence']['items']['properties']['excerpt']
    assert item['properties']['explicit']['type'] == 'boolean'
    assert item['properties']['kind']['enum'] == ['education', 'experience', 'project', 'skill']
    assert {'type': 'null'} in item['properties']['end_date']['anyOf']


def test_repair_recovers_overlong_quotes_and_conflicting_dates(harness, monkeypatch, caplog):
    invalid, valid = candidates()
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, valid])
    with caplog.at_level(logging.WARNING): app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and result['error'] is None
    assert result['extraction']['workflow_version'] == 'cv-extraction-6'
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
    assert any(issue['field'] == 'items[0].description' and issue['issue'] == 'string_too_long'
               for issue in repair['validation_feedback'])
    assert not any(issue['field'].endswith(('start_date', 'end_date')) for issue in repair['validation_feedback'])
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
    # Nothing in the final candidate verifies, so even the last attempt cannot keep a partial extraction.
    for item in invalid['items']: item['description'] = 'D' * 4001
    second = invalid if failure == 'schema' else deepcopy(valid)
    if failure == 'evidence':
        for item in second['items']: item['evidence'][0]['excerpt'] = 'Invented quotation'
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, second] + ([{'supported': []}] if failure == 'evidence' else []))
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'failed' and result['error']['repair_attempted']
    assert result['error']['failure_stage'] == 'extraction_validation'
    assert result['error']['failure_category'] == ('schema_validation' if failure == 'schema' else 'evidence_validation')
    assert len(calls) == count(app.state.repository) == (3 if failure == 'evidence' else 2)
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


def repeated_review_candidates():
    _, valid = candidates()
    fact = {'field': 'skill_use', 'skill_name': 'Python', 'status': 'supported',
            'value': 'Used Python', 'evidence': [{'source_id': 'b2', 'quote': 'used Python'}]}
    valid['items'][1]['review_evidence'] = [fact]
    invalid = deepcopy(valid)
    invalid['items'][1]['review_evidence'].append({**deepcopy(fact), 'skill_name': '  PYTHON  ', 'value': 'Applied Python'})
    return invalid, valid


def review_graph(responses):
    calls = []
    blocks = [{'id': f'b{i+1}', 'text': text, 'location': 'Synthetic'} for i, text in enumerate(SOURCES)]
    def model(_blocks, candidate, feedback):
        calls.append((deepcopy(candidate), deepcopy(feedback)))
        return deepcopy(responses[len(calls)-1]), {}
    def verify(_blocks, pending):
        return frozenset((ref['block_id'], ref['excerpt']) for ref in pending)
    graph = ExtractionHarness('synthetic-id', lambda _: {'blocks': blocks}, model, lambda _: None, checkpointer=saver(), thread_id='synthetic-quote-test', verify_evidence=verify)
    return graph, calls


def test_distinct_review_evidence_shares_normalized_field_without_repair():
    repeated, _ = repeated_review_candidates()
    graph, calls = review_graph([repeated])
    result = graph.run(b'synthetic')
    assert result['repair_attempts'] == 0 and len(calls) == 1
    facts = result['items'][1]['review_evidence']
    assert [fact['value'] for fact in facts] == ['Used Python', 'Applied Python']
    assert all(fact['evidence'] == [{'source_id': 'b2', 'quote': 'used Python'}] for fact in facts)


def test_identical_review_evidence_is_removed_without_repair():
    _, valid = repeated_review_candidates()
    valid['items'][1]['review_evidence'].append(deepcopy(valid['items'][1]['review_evidence'][0]))
    graph, calls = review_graph([valid])
    result = graph.run(b'synthetic')
    assert result['repair_attempts'] == 0 and len(calls) == 1
    assert len(result['items'][1]['review_evidence']) == 1
    assert result['items'][1]['review_evidence'][0]['value'] == 'Used Python'


def review_quote_candidates():
    _, valid = repeated_review_candidates()
    invalid = deepcopy(valid)
    invalid['items'][1]['review_evidence'][0]['evidence'][0]['quote'] = 'Applied Python'
    return invalid, valid


def test_review_quote_repair_uses_exact_anchor_and_preserves_fact(harness, monkeypatch):
    invalid, valid = review_quote_candidates()
    client, app, queued, calls = setup_provider(
        harness, monkeypatch, [invalid, valid, {'supported': [0]}])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and result['error'] is None
    assert result['extraction']['repair_attempts'] == 1
    assert len(calls) == count(app.state.repository) == 3
    feedback = json.loads(calls[1]['messages'][1]['content'])['validation_feedback']
    assert feedback[0]['field'] == 'items[1].review_evidence[0].evidence[0].quote'
    assert feedback[0]['issue'] == 'review_quote'
    assert 'exact' in feedback[0]['guidance'].lower()
    assert 'Applied Python' not in json.dumps(feedback)
    assert 'Project Finch' not in json.dumps(feedback)
    review_fact = result['items'][1]['review_evidence'][0]
    assert review_fact['value'] == 'Used Python'
    assert review_fact['evidence'] == [{'source_id': 'b2', 'quote': 'used Python'}]
    verification = json.loads(calls[2]['messages'][1]['content'])
    assert len(verification['summaries']) == 1
    assert 'skill_use' in verification['summaries'][0]['excerpt']


def test_repeated_nonexact_review_quote_fails_without_publishing(harness, monkeypatch):
    invalid, _ = review_quote_candidates()
    # Only the unverifiable item remains, so there is nothing to keep.
    invalid['items'] = [{**invalid['items'][1], 'supporting_items': []}]
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, invalid])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'failed' and result['error']['repair_attempted']
    assert result['error']['failure_stage'] == 'extraction_validation'
    assert result['error']['failure_category'] == 'evidence_validation'
    assert result['items'] == [] and result['extraction_version'] == 0
    assert len(calls) == count(app.state.repository) == 2


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
        lambda *args: (valid, {}), observe, checkpointer=saver(), thread_id='operation:1')
    assert isinstance(graph.graph.checkpointer, LatestStateSaver)
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


def test_other_information_is_saved_with_source_and_returned_by_api(harness, monkeypatch):
    _, valid = candidates()
    valid['other_information'] = [{'block_id': 'b1', 'excerpt': 'A' * 500}]
    client, app, queued, calls = setup_provider(harness, monkeypatch, [valid])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready'
    assert result['other_information'] == [{'id': 'b1', 'location': 'Paragraph 1', 'excerpt': 'A' * 500}]
    assert app.state.repository.get('owner-a', queued['id'])['other_information'] == result['other_information']
    assert len(calls) == 1
    assert 'other_information' in calls[0]['response_format']['json_schema']['schema']['required']


def test_other_information_rejects_invented_source_text(harness, monkeypatch):
    _, invalid = candidates()
    invalid['other_information'] = [{'block_id': 'b1', 'excerpt': 'Invented uncategorised fact'}]
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, {'supported': []}, invalid, {'supported': []}])
    app.state.worker.run_once()
    result = read_result(client, queued)
    # The verified items are kept; the invented text never is, and the user is told it was left out.
    assert result['status'] == 'ready' and result['other_information'] == []
    assert any('left out' in notice for notice in result['notices'])
    assert len(calls) == 4


def test_unclear_dates_need_no_repair(harness, monkeypatch):
    _, valid = candidates()
    valid['items'][0].update(start_date='Spring 2024', end_date='2025-99')
    client, app, queued, calls = setup_provider(harness, monkeypatch, [valid])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and result['extraction']['repair_attempts'] == 0
    assert result['items'][0]['start_date'] is None and result['items'][0]['end_date'] is None
    assert len(calls) == 1


def test_failed_reprocessing_preserves_other_information(harness, monkeypatch):
    _, valid = candidates()
    valid['other_information'] = [{'block_id': 'b1', 'excerpt': 'A' * 500}]
    rejection = httpx.Response(400, json={'error': {'message': 'Invalid request'}})
    client, app, queued, calls = setup_provider(harness, monkeypatch, [valid, rejection])
    app.state.worker.run_once()
    saved = read_result(client, queued)
    repeated = upload(client, docx(SOURCES), cv_id=saved['id'], expected_version=saved['version']).json()
    app.state.worker.run_once()
    failed = read_result(client, repeated)
    assert failed['status'] == 'failed'
    assert failed['other_information'] == saved['other_information']
    assert failed['extraction_version'] == saved['extraction_version']


@pytest.mark.parametrize('defect', ['items_count', 'citation_count', 'duration', 'other_count', 'extra', 'enum'])
def test_decoding_schema_keeps_all_backend_constraints(harness, monkeypatch, defect):
    _, invalid = candidates()
    if defect == 'items_count': invalid['items'] *= 81
    # Every item carries the defect, so nothing verifies and the whole extraction fails.
    elif defect == 'citation_count':
        for item in invalid['items']: item['evidence'] = [{'block_id': 'b1', 'excerpt': 'A'}] * 7
    elif defect == 'duration':
        for item in invalid['items']: item['experience_months'] = -1
    elif defect == 'other_count': invalid['other_information'] = [{'block_id': 'b1', 'excerpt': 'A'}] * 161
    elif defect == 'extra':
        for item in invalid['items']: item['invented_field'] = 'untrusted'
    elif defect == 'enum':
        for item in invalid['items']: item['kind'] = 'invented'
    client, app, queued, calls = setup_provider(harness, monkeypatch, [invalid, invalid])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'failed' and result['error']['failure_category'] == 'schema_validation'
    assert result['items'] == [] and result['extraction_version'] == 0
    assert len(calls) == 2
    for request in calls:
        assert 'maxItems' in request['response_format']['json_schema']['schema']['properties']['items']


@pytest.mark.parametrize('other', [False, True])
def test_long_evidence_passes_the_schema_and_empty_evidence_gets_private_guidance(other):
    _, candidate = candidates()
    private_quote = 'PRIVATE_SYNTHETIC_QUOTATION_' * 21
    def with_excerpt(text):
        value = deepcopy(candidate)
        ref = {'block_id': 'b1', 'excerpt': text}
        if other: value['other_information'] = [ref]
        else: value['items'][0]['evidence'] = [ref]
        return value
    Extraction.model_validate(with_excerpt(private_quote))
    with pytest.raises(ValidationError) as caught:
        Extraction.model_validate(with_excerpt(''))
    feedback = feedback_for(caught.value)
    assert len(feedback) == 1
    assert feedback[0]['field'] == ('other_information[0].excerpt' if other else 'items[0].evidence[0].excerpt')
    assert 'supported by the cited source block' in feedback[0]['guidance']
    assert private_quote not in json.dumps(feedback)


def test_source_verified_long_quotations_publish_without_model_repair(harness, monkeypatch):
    _, valid = candidates()
    valid['items'][0]['evidence'][0]['excerpt'] = SOURCES[0]
    valid['other_information'] = [{'block_id': 'b1', 'excerpt': 'A' * 510}]
    client, app, queued, calls = setup_provider(harness, monkeypatch, [valid])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and len(calls) == 1
    assert result['extraction']['repair_attempts'] == 0
    evidence = result['items'][0]['evidence']
    assert [ref['excerpt'] for ref in evidence] == [SOURCES[0]]
    assert [ref['excerpt'] for ref in result['other_information']] == ['A' * 510]


def test_graph_prepares_clarification_context_after_grounded_extraction():
    from app.workflows.extraction import ExtractionHarness
    source = 'I implemented the Python reporting API and owned its testing.'
    facts = [{'field': field, 'skill_name': None, 'status': 'supported', 'value': value,
              'attribution': 'personal', 'evidence': [{'source_id': 'b1', 'quote': source}]}
             for field, value in [('personal_contribution', 'Implemented the reporting API'),
                                  ('responsibilities', 'Owned API implementation and testing'),
                                  ('task_scope', 'Python reporting API')]]
    candidate = {'items': [{'kind': 'project', 'title': 'Reporting API', 'description': source,
        'explicit': True, 'skill_names': ['Python'], 'evidence': [{'block_id': 'b1', 'excerpt': source}],
        'review_evidence': facts, 'uncertainties': ['personal_contribution', 'responsibility', 'proficiency']}]}
    calls = []
    def model(*args):
        calls.append(args)
        return candidate, {'provider': 'synthetic', 'model': 'fixture', 'prompt_version': '1', 'schema_version': '1'}
    graph = ExtractionHarness('synthetic-cv', lambda _: {'blocks': [{'id': 'b1', 'text': source, 'location': 'Paragraph 1'}]},
                              model, lambda _: None, checkpointer=saver(), thread_id='operation:1',
                              verify_evidence=lambda _, refs: frozenset((r['block_id'], r['excerpt']) for r in refs))
    result = graph.run(b'synthetic')
    assert 'prepare_review' in graph.graph.nodes
    assert len(calls) == 1
    assert result['items'][0]['uncertainties'] == ['proficiency']
    assert result['items'][0]['review_evidence'] == facts
    assert result['metadata']['workflow_version'] == 'cv-extraction-6'
