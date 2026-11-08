"""Distinct responsibilities/contributions survive extraction and review reads."""
from copy import deepcopy

import pytest

from app.conversation.interview_memory import target_availability
from app.domain.baseline import estimate_skill
from app.domain.capabilities import validate_extraction, evidence_requiring_semantic_check, interpretation_semantic_checks
from app.domain.extraction_errors import EvidenceValidationError
from app.domain.extraction_feedback import feedback_for
from app.domain.review_context import evidence_for, clarification_context
from app.schemas.interview_evidence import fact_statement
from tests.conftest import docx, upload


TEXT = 'I built a Python loader. I maintained the records. We co-developed a pipeline.'


def fact(field, value, quote, *, attribution='personal', status='supported', skill=None):
    return {'field': field, 'skill_name': skill, 'value': value, 'attribution': attribution,
            'status': status, 'evidence': [{'source_id': 'b1', 'quote': quote}]}


def payload():
    facts = [fact('responsibilities', 'Built a Python loader.', 'I built a Python loader.'),
             fact('responsibilities', 'Maintained the records.', 'I maintained the records.'),
             fact('personal_contribution', 'Built a Python loader.', 'I built a Python loader.'),
             fact('personal_contribution', 'Co-developed a pipeline.', 'We co-developed a pipeline.', attribution='shared')]
    return {'items': [{'kind': 'project', 'title': 'Synthetic pipeline', 'description': TEXT,
        'explicit': True, 'skill_names': ['Python'], 'evidence': [{'block_id': 'b1', 'excerpt': TEXT}],
        'review_evidence': [*facts, deepcopy(facts[0])]}]}


def validate(value):
    blocks = [{'id': 'b1', 'location': 'Paragraph 1', 'text': TEXT}]
    # Explicit synthetic semantic verdicts; exact quote anchors still undergo
    # the production checks even when the interpreted descriptions are approved.
    approved = frozenset((r['block_id'], r['excerpt']) for r in evidence_requiring_semantic_check(value, blocks))
    return validate_extraction(value, blocks, 'synthetic-cv', approved)[0]


def test_distinct_facts_survive_and_only_exact_repetition_is_removed():
    item = validate(payload())
    assert len(item['review_evidence']) == 4
    assert [f['value'] for f in item['review_evidence'] if f['field'] == 'responsibilities'] == [
        'Built a Python loader.', 'Maintained the records.']
    assert [f['attribution'] for f in item['review_evidence'] if f['field'] == 'personal_contribution'] == ['personal', 'shared']
    assert evidence_for(item) == item['review_evidence']


def test_grouping_does_not_admit_a_fabricated_quote():
    value = payload()
    value['items'][0]['review_evidence'][1]['evidence'][0]['quote'] = 'I independently mastered Python.'
    with pytest.raises(EvidenceValidationError) as caught:
        validate(value)
    assert feedback_for(caught.value)[0]['issue'] == 'review_quote'
    assert feedback_for(caught.value)[0]['field'] == 'items[0].review_evidence[1].evidence[0].quote'


def test_skill_repair_feedback_identifies_the_item_and_rule():
    value = payload()
    value['items'][0]['review_evidence'][0]['skill_name'] = 'SQL'
    with pytest.raises(EvidenceValidationError) as caught:
        validate(value)
    assert feedback_for(caught.value)[0]['field'] == 'items[0].review_evidence[0]'
    assert feedback_for(caught.value)[0]['issue'] == 'review_skill'


def test_repair_feedback_keeps_original_indexes_before_deduplication():
    value = payload()
    facts = value['items'][0]['review_evidence']
    facts.insert(1, deepcopy(facts[0]))
    facts[2]['skill_name'] = 'SQL'
    with pytest.raises(EvidenceValidationError) as caught:
        validate(value)
    assert feedback_for(caught.value)[0]['field'] == 'items[0].review_evidence[2]'
    assert feedback_for(caught.value)[0]['issue'] == 'review_skill'


def test_unknown_ownership_is_not_presented_as_a_cv_claim_to_verify():
    value = fact('task_scope', 'The pipeline classifies text.', 'We co-developed a pipeline.', attribution='unknown')
    statement = fact_statement(value)
    assert 'The pipeline classifies text.' in statement
    assert 'Attribution' not in statement and 'personal/shared' not in statement
    assert value['attribution'] == 'unknown'
    value['attribution'] = 'shared'
    assert 'Attribution is shared' in fact_statement(value)


@pytest.mark.parametrize('reverse', [False, True])
def test_a_supported_fact_cannot_hide_an_unresolved_fact(reverse):
    item = validate(payload())
    item['review_evidence'].append(fact('personal_contribution', 'Pipeline ownership remains partial.',
                                      'We co-developed a pipeline.', status='partial'))
    if reverse: item['review_evidence'].reverse()
    context = clarification_context(item, include_baseline=False)
    assert any(t['field'] == 'personal_contribution' for t in context['clarification_targets'])
    assert target_availability(item, {'attempts': {}}, 'personal_contribution') == 'open'


@pytest.mark.parametrize('reverse', [False, True])
def test_different_assistance_facts_do_not_inflate_the_baseline(reverse):
    item = validate(payload())
    item['skill_claims'] = [{'name': 'Python', 'attribution': 'personal', 'assistance': 'unknown'}]
    item['review_evidence'] += [fact('skill_use', 'Built the loader.', 'I built a Python loader.', skill='Python'),
        fact('assistance', 'independent', 'I built a Python loader.', skill='Python'),
        fact('assistance', 'assisted', 'We co-developed a pipeline.', skill='Python')]
    if reverse: item['review_evidence'].reverse()
    assert estimate_skill(item, item['skill_claims'][0])['level'] == 'insufficient_evidence'


def test_legacy_consistency_checks_include_every_prior_fact_in_the_group():
    item = validate(payload())
    value = {'item_id': item['id'], 'answer_revision': 1, 'claims': [],
        'resolution': 'partial', 'resolved_uncertainties': [], 'remaining_uncertainties': ['claim'],
        'review_evidence': [fact('responsibilities', 'Maintained both components.', 'I maintained both components.')]}
    value['review_evidence'][0]['evidence'][0]['source_id'] = 'answer'
    blocks, _, _ = interpretation_semantic_checks(value,
        {'answer': 'I maintained both components.', 'question': 'What did you maintain?'}, item)
    assert 'Built a Python loader.' in blocks[-1]['text'] and 'Maintained the records.' in blocks[-1]['text']


def test_upload_publishes_ready_and_restores_all_distinct_facts(harness):
    client, app, extractor, *_ = harness
    extractor.payload = payload()
    extractor.verify_evidence = lambda blocks, refs, **kw: frozenset((r['block_id'], r['excerpt']) for r in refs)
    response = upload(client, docx([TEXT]))
    assert response.status_code == 202
    app.state.worker.run_once()
    saved = client.get('/api/v1/cv/' + response.json()['id']).json()
    assert saved['status'] == 'ready' and saved['error'] is None
    assert len(saved['items'][0]['review_evidence']) == 4
    assert client.get('/api/v1/cv/' + saved['id']).json()['items'] == saved['items']
