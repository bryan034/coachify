"""Question allowances survive source reconciliation and migration."""
from copy import deepcopy

import pytest

from app.clarification import service as clarification
from app.conversation.interview_memory import durable_review_questions


def question(identifier, item, status, **extra):
    return {'id': identifier, 'item_id': item, 'kind': 'project', 'status': status,
            'question': 'What did you personally build?', **extra}


def accepted(source, questions, old, new):
    return {'operation': 'reconcile', 'action': 'accept_candidate',
            'clarifications': deepcopy(questions),
            'candidate': {'source_cv_id': source, 'clarifications': deepcopy(questions)},
            'choices': [{'item_id': old, 'target_item_id': new}]}


def reconciled_document():
    answered = question('q1', 'A', 'answered', answer='I built the API.')
    skipped = question('q2', 'A', 'skipped', answer=None)
    transferred = question('q1b', 'B', 'answered', answer='I built the API.',
                           reconciled_from={'cv_id': 'cv', 'item_id': 'A', 'question_id': 'q1'})
    return {'_id': 'cv', 'history': [accepted('cv', [answered, skipped], 'A', 'B')],
            'original_items': [{'id': 'B', 'kind': 'project'}], 'clarifications': [transferred]}


@pytest.mark.parametrize('scope, group', [('section', 'section:project'), ('item', 'item:B')])
def test_reconciled_answer_and_skip_consume_two_slots_once(scope, group, monkeypatch):
    document = reconciled_document()
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    receipts = durable_review_questions(document)
    assert [(q['id'], q['item_id'], q['status']) for q in receipts] == [
        ('q1b', 'B', 'answered'), ('q2', 'B', 'skipped')]
    _, counts = clarification.group_counts(document, {'scope': scope, 'version': 1})
    assert counts == {group: 2}


def test_second_reconciliation_maps_archived_skips_and_deduplicates_chain(monkeypatch):
    document = reconciled_document()
    previous = deepcopy(document['clarifications'])
    document['history'].append(accepted('cv', previous, 'B', 'C'))
    document['original_items'] = [{'id': 'C', 'kind': 'project'}]
    document['clarifications'] = [question('q1c', 'C', 'answered', answer='I built the API.',
        reconciled_from={'cv_id': 'cv', 'item_id': 'B', 'question_id': 'q1b'})]
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    receipts = durable_review_questions(document)
    assert {(q['id'], q['item_id']) for q in receipts} == {('q1c', 'C'), ('q2', 'C')}
    assert clarification.group_counts(document, {'scope': 'item', 'version': 1})[1] == {'item:C': 2}


def test_keep_previous_and_synthetic_statements_do_not_issue_new_questions():
    document = reconciled_document()
    document['history'].append({**accepted('cv', document['clarifications'], 'B', 'C'), 'action': 'keep_previous'})
    document['clarifications'].append(question('statement', 'B', 'answered', _synthetic_statement=True))
    assert len(durable_review_questions(document)) == 2


def test_cross_cv_comparison_counts_only_explicitly_mapped_sources():
    mapped = question('q1', 'A', 'answered', answer='I built the API.')
    skipped = question('q2', 'A', 'skipped', answer=None)
    archived = question('q3', 'unmapped', 'skipped', answer=None)
    entry = accepted('old-cv', [mapped, skipped, archived], 'A', 'B')
    entry['clarifications'] = []
    entry['choices'].append({'item_id': 'unmapped', 'target_item_id': None})
    transferred = question('q1b', 'B', 'answered', answer='I built the API.',
                           reconciled_from={'cv_id': 'old-cv', 'item_id': 'A', 'question_id': 'q1'})
    document = {'_id': 'new-cv', 'history': [entry], 'clarifications': [transferred]}
    assert {(q['id'], q['item_id']) for q in durable_review_questions(document)} == {('q1b', 'B'), ('q2', 'B')}


def test_archive_preserves_section_count_without_assigning_an_unrelated_paid_item(monkeypatch):
    document = reconciled_document()
    document['history'][0]['choices'][0]['target_item_id'] = None
    document['clarifications'] = []
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    assert clarification.group_counts(document, {'scope': 'section', 'version': 1})[1] == {'section:project': 2}
    assert clarification.group_counts(document, {'scope': 'item', 'version': 1})[1] == {'item:A': 2}


def test_target_specific_envelope_hides_current_question_beyond_historical_limit(monkeypatch):
    from types import SimpleNamespace
    document = reconciled_document()
    document.update(operation={'status': 'ready'}, extraction_version=1, version=1)
    document['original_items'][0].update(removed=False, uncertainties=['claim'])
    document['clarifications'].append(question('q3', 'B', 'unanswered', uncertainty='claim', answer=None))
    context = SimpleNamespace(id='target', version=1, selection_version=1, type='specific_job',
                              model_dump=lambda **_: {'id': 'target'})
    monkeypatch.setattr(clarification, 'ConfirmedContext', SimpleNamespace(model_validate=lambda _: context))
    monkeypatch.setattr(clarification, 'effective_items', lambda document: document['original_items'])
    monkeypatch.setattr(clarification, 'relevant', lambda *_: True)
    view = clarification.envelope(document, {'id': 'target'}, {'scope': 'item', 'version': 1})
    assert [q['id'] for q in view['questions']] == ['q1b']


@pytest.mark.parametrize('scope', ['section', 'item'])
def test_interview_rebuild_counts_archived_receipts_for_replacement(scope, monkeypatch):
    from app.conversation import interview_memory as memory
    document = reconciled_document()
    document.update(extraction_version=1, effective_version=1, overlays={},
                    review_policy_snapshot={'scope': scope, 'version': 1})
    document['original_items'][0]['removed'] = False
    monkeypatch.setattr(memory, 'effective_items', lambda document: document['original_items'])
    monkeypatch.setattr(memory, 'source_fingerprint', lambda item: item['id'])
    monkeypatch.setattr(memory, 'baseline_estimates', lambda _: [])
    monkeypatch.setattr(memory, 'topic_ids', lambda items: [item['id'] for item in items])
    rebuilt = memory.reconcile_memory({'interview_memory': {}}, document)
    assert memory.topic_question_count(rebuilt, 'B') == 2
    assert len(rebuilt['intent_history']) == 2
