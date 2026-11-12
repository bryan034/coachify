"""The review summary is derived on read from the saved CV, with synthetic documents only."""
from copy import deepcopy
from app.domain.capabilities import effective_items
from app.domain.review_summary import review_summary
from tests.conftest import ready


def test_fresh_cv_reports_an_empty_review(harness):
    client, *_ = harness
    cv = ready(harness)
    summary = client.get('/api/v1/cv/' + cv['id']).json()['review_summary']
    assert summary == {'answered_questions': 0, 'experiences': 0, 'skills_added': 0, 'skills_corrected': 0,
                       'skills_removed': 0, 'added_skill_ids': [], 'skill_notes': {}}


def test_review_answers_are_counted_and_notes_use_personal_claims(harness):
    client, app, *_ = harness
    cv = ready(harness)
    detail = client.get('/api/v1/cv/' + cv['id']).json()
    item = next(i for i in detail['items'] if i['kind'] != 'skill')
    document = {'original_items': deepcopy(detail['original_items']), 'overlays': {}, 'history': [], 'clarifications': [
        {'id': 'q1', 'item_id': item['id'], 'status': 'answered',
         'interpretation': {'applied_sequence': 1, 'claims': [
             {'skill_id': 'synthetic-new', 'name': 'Synthetic New', 'attribution': 'personal', 'assistance': 'independent',
              'proficiency': None, 'experience_months': None, 'evidence_excerpt': 'I wrote it myself.',
              'changed_fields': ['attribution', 'assistance']},
             {'skill_id': 'synthetic-team', 'name': 'Synthetic Team', 'attribution': 'team', 'assistance': 'unknown',
              'proficiency': None, 'experience_months': None, 'evidence_excerpt': 'The team did it.',
              'changed_fields': ['attribution']}],
          'resolved_uncertainties': [], 'remaining_uncertainties': []}},
        {'id': 'q2', 'item_id': item['id'], 'status': 'skipped'},
        {'id': 'q3', 'item_id': item['id'], 'status': 'answered', 'reconciliation_required': True}]}
    summary = review_summary(document, effective_items(document))
    assert summary['answered_questions'] == 1 and summary['experiences'] == 1
    assert summary['skill_notes'] == {'synthetic-new': 'I wrote it myself.'}
    assert summary['added_skill_ids'] == ['synthetic-new'] and summary['skills_added'] == 1
    assert summary['skills_removed'] == 0
