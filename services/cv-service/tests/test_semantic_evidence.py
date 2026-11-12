"""Synthetic semantic verdicts exercise grounding, admission and publication."""
from dataclasses import replace
import json
import pytest
from pydantic import ValidationError
from app.domain.capabilities import evidence_requiring_semantic_check, validate_extraction
from app.domain.extraction_errors import EvidenceValidationError
from app.domain.extraction_feedback import feedback_for
from app.schemas.cv import Extraction
from app.schemas.interview_evidence import fact_statement
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


def review_evidence_candidate():
    text = 'Project Finch: used Python to clean tables.'
    fact = {'field': 'skill_use', 'skill_name': 'Python', 'status': 'supported',
            'value': 'Used Python', 'evidence': [{'source_id': 'b1', 'quote': 'used Python'}]}
    blocks = [{'id': 'b1', 'text': text, 'location': 'Synthetic'},
              {'id': 'b2', 'text': 'Unrelated synthetic education.', 'location': 'Synthetic'}]
    value = {'items': [{'kind': 'project', 'title': 'Project Finch', 'description': text,
        'explicit': True, 'skill_names': ['Python'],
        'evidence': [{'block_id': 'b1', 'excerpt': text}], 'review_evidence': [fact]}]}
    return value, blocks


@pytest.mark.parametrize('source_id,quote,rule,field', [
    ('missing', 'used Python', 'review_source', 'source_id'),
    ('b2', 'used Python', 'review_quote', 'quote'),
    ('b1', 'Applied Python', 'review_quote', 'quote'),
])
def test_review_anchor_errors_are_specific_and_do_not_leak_cv_text(source_id, quote, rule, field):
    value, blocks = review_evidence_candidate()
    value['items'][0]['review_evidence'][0]['evidence'][0] = {'source_id': source_id, 'quote': quote}
    with pytest.raises(EvidenceValidationError) as caught:
        evidence_requiring_semantic_check(value, blocks)
    feedback = feedback_for(caught.value)
    assert feedback[0]['issue'] == rule
    assert feedback[0]['field'] == f'items[0].review_evidence[0].evidence[0].{field}'
    assert quote not in json.dumps(feedback)
    assert 'Project Finch' not in json.dumps(feedback)
    assert 'Unrelated synthetic education' not in json.dumps(feedback)


def test_semantic_approval_cannot_make_nonexact_review_anchor_valid():
    value, blocks = review_evidence_candidate()
    fact = value['items'][0]['review_evidence'][0]
    fact['evidence'][0]['quote'] = 'Applied Python'
    support = frozenset({('b1', 'Applied Python'), ('b1', fact_statement(fact))})
    with pytest.raises(EvidenceValidationError) as caught:
        validate_extraction(value, blocks, 'synthetic-cv', support)
    assert caught.value.rule == 'review_quote'


@pytest.mark.parametrize('quote', ['USED  PYTHON', 'used\nPython', 'ｕｓｅｄ Ｐｙｔｈｏｎ'])
def test_review_quotes_keep_case_spacing_and_unicode_tolerance(quote):
    value, blocks = review_evidence_candidate()
    value['items'][0]['review_evidence'][0]['evidence'][0]['quote'] = quote
    pending = evidence_requiring_semantic_check(value, blocks)
    fact = value['items'][0]['review_evidence'][0]
    assert pending == [{'block_id': 'b1', 'excerpt': fact_statement(fact)}]
    support = frozenset((ref['block_id'], ref['excerpt']) for ref in pending)
    items = validate_extraction(value, blocks, 'synthetic-cv', support)
    assert items[0]['review_evidence'][0]['evidence'][0]['quote'] == quote


@pytest.mark.parametrize('source,quote', [
    # A PDF line break after a hyphen, rejoined by the model.
    ('Built a proof-of-\nconcept pipeline.', 'built a proof-of-concept pipeline'),
    ('Wrote evi-\ndence summaries.', 'wrote evidence summaries'),
    ('Wrote evi-\ndence summaries.', 'wrote evi-dence summaries'),
    # A quote keeping the wrap still matches a source without it.
    ('Built a proof-of-concept pipeline.', 'proof-of- concept'),
])
def test_review_quotes_tolerate_line_wrapped_hyphens(source, quote):
    value, blocks = review_evidence_candidate()
    blocks[0]['text'] = source
    value['items'][0]['evidence'][0]['excerpt'] = source
    value['items'][0]['review_evidence'][0].update(skill_name=None, evidence=[{'source_id': 'b1', 'quote': quote}])
    value['items'][0]['skill_names'] = []
    pending = evidence_requiring_semantic_check(value, blocks)
    support = frozenset((ref['block_id'], ref['excerpt']) for ref in pending)
    items = validate_extraction(value, blocks, 'synthetic-cv', support)
    assert items[0]['review_evidence'][0]['evidence'][0]['quote'] == quote


@pytest.mark.parametrize('source,quote', [
    # Spaced separators are not line-wrapped words.
    ('Python - SQL', 'Python-SQL'),
    ('Python - SQL', 'PythonSQL'),
    # Words and punctuation must still match.
    ('Built a proof-of-\nconcept pipeline.', 'built a proof of concept pipeline'),
    ('Built a proof-of-\nconcept pipeline.', 'built a proof-of-product pipeline'),
])
def test_review_quotes_still_reject_changed_words_or_separators(source, quote):
    value, blocks = review_evidence_candidate()
    blocks[0]['text'] = source
    value['items'][0]['review_evidence'][0]['evidence'][0]['quote'] = quote
    with pytest.raises(EvidenceValidationError) as caught:
        evidence_requiring_semantic_check(value, blocks)
    assert caught.value.rule == 'review_quote'


@pytest.mark.parametrize('field,text', [('quote', ''), ('source_id', '')])
def test_review_anchor_schema_feedback_matches_its_quotation_rule(field, text):
    value, _ = review_evidence_candidate()
    value['items'][0]['review_evidence'][0]['evidence'][0][field] = text
    with pytest.raises(ValidationError) as caught:
        Extraction.model_validate(value)
    feedback = feedback_for(caught.value)
    issue = next(issue for issue in feedback if issue['field'].endswith('.' + field))
    assert issue['field'] == f'items[0].review_evidence[0].evidence[0].{field}'
    assert 'paraphrasing is allowed' not in issue['guidance'].lower()
    assert ('exact' if field == 'quote' else 'source_id') in issue['guidance'].lower()
    assert 'Project Finch' not in json.dumps(feedback)


@pytest.mark.parametrize('review_evidence', [None, 'invalid', {}, [None], [
    {'field': 'skill_use', 'status': 'supported', 'value': 'Used Python', 'evidence': None}
]])
def test_malformed_review_evidence_reaches_schema_validation(review_evidence):
    value, blocks = review_evidence_candidate()
    value['items'][0]['review_evidence'] = review_evidence
    assert evidence_requiring_semantic_check(value, blocks) == []
    with pytest.raises(ValidationError):
        Extraction.model_validate(value)


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


def test_approved_long_summary_is_kept_whole(harness, monkeypatch):
    _, value = candidates()
    summary = ('Synthetic University study record. ' * 17) + 'The period was 2024 to 2025.'
    value['items'][0]['evidence'] = [{'block_id': 'b1', 'excerpt': summary}]
    client, app, queued, calls = setup_provider(harness, monkeypatch, [value, {'supported': [0]}])
    app.state.worker.run_once()
    result = read_result(client, queued)
    assert result['status'] == 'ready' and len(calls) == 2
    refs = result['items'][0]['evidence']
    assert [ref['excerpt'] for ref in refs] == [summary]


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
