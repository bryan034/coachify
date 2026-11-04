from copy import deepcopy
from app.domain.baseline import baseline_estimates
from app.conversation.interview_memory import topic_ids


def fact(field, value, *, skill=None, status='supported'):
    return {'field': field, 'skill_name': skill, 'value': value, 'status': status, 'attribution': 'personal',
            'evidence': [{'source_id': 'answer:synthetic', 'quote': 'Synthetic personal application evidence.'}]}


def project(assistance='unknown'):
    return {'id': 'project', 'kind': 'project', 'title': 'Synthetic project', 'description': 'Python pipeline',
            'uncertainties': [], 'skill_names': ['Python'], 'removed': False,
            'skill_claims': [{'name': 'Python', 'attribution': 'personal', 'assistance': assistance,
                              'evidence_type': 'user_clarified', 'evidence': [{'id': 'answer:synthetic', 'excerpt': 'I implemented the pipeline.'}]}],
            'review_evidence': [fact('personal_contribution', 'Implemented the pipeline'),
                                fact('skill_use', 'Implemented the data pipeline', skill='Python')],
            'evidence': [{'id': 'b1', 'excerpt': 'Python pipeline'}]}


def test_confidence_and_duration_alone_cannot_establish_independence():
    item = project()
    item['experience_months'] = 120
    item['review_evidence'].append(fact('replication_confidence', 'Very confident'))
    assert baseline_estimates([item])[0]['level'] == 'insufficient_evidence'
    item['skill_claims'][0]['assistance'] = 'assisted'
    assert baseline_estimates([item])[0]['level'] == 'guided_application'
    item['skill_claims'][0]['assistance'] = 'independent'
    assert baseline_estimates([item])[0]['level'] == 'independent_application'
    item['review_evidence'] += [fact('complexity', 'Handled complex data', skill='Python'), fact('problem_solving', 'Debugged pipeline failure', skill='Python')]
    assert baseline_estimates([item])[0]['level'] == 'complex_application'
    item['review_evidence'].append(fact('assistance', 'Support is unclear', status='conflicting', skill='Python'))
    assert baseline_estimates([item])[0]['level'] == 'insufficient_evidence'


def test_baseline_has_explicit_unknown_for_every_project_skill_and_no_topic_count_cap():
    item = project()
    item['skill_claims'].append({'name': 'SQL', 'attribution': 'unknown', 'assistance': 'unknown'})
    assert {e['skill_name'] for e in baseline_estimates([item])} == {'Python', 'SQL'}
    items = [{**deepcopy(item), 'id': str(index)} for index in range(12)]
    assert len(topic_ids(items)) == 12
    assert len(baseline_estimates(items)) == 24


def test_clear_supported_skill_baseline_does_not_require_repeating_the_cv():
    item = project('independent')
    assert topic_ids([item]) == []
    assert baseline_estimates([item])[0]['level'] == 'independent_application'


def test_general_project_complexity_does_not_inflate_each_skill_level():
    item = project('independent')
    item['review_evidence'] += [fact('complexity', 'The overall project was complex'),
                                fact('problem_solving', 'The team solved difficult problems')]
    assert baseline_estimates([item])[0]['level'] == 'independent_application'


def test_review_targets_establish_relevant_application_before_support_details():
    from app.domain.baseline import baseline_targets
    item = project()
    item['review_evidence'] = []
    item['skill_claims'] = [{'name': 'Python', 'attribution': 'unknown', 'assistance': 'unknown'}]
    assert {(t['field'], t['skill_name']) for t in baseline_targets(item)} == {
        ('personal_contribution', None), ('skill_use', 'Python')}
    item['review_evidence'] = [fact('personal_contribution', 'Implemented the pipeline'),
                               fact('skill_use', 'Built the data pipeline', skill='Python')]
    assert [(t['field'], t['skill_name']) for t in baseline_targets(item)] == [('assistance', 'Python')]


def test_peripheral_missing_or_partial_fields_do_not_become_review_questions():
    from app.domain.review_context import clarification_context
    item = project('independent')
    item['review_evidence'] += [fact(field, 'Some peripheral detail is incomplete', status='partial')
        for field in ('recency', 'frequency', 'replication_confidence', 'limitations', 'role', 'outcome')]
    assert clarification_context(item)['clarification_targets'] == []
    assert topic_ids([item]) == []
    assert baseline_estimates([item])[0]['level'] == 'independent_application'
