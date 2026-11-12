"""A skill's own level, judged by the model from the CV or the user's review answers.

It is independent of any career goal; only sufficiently evidenced levels survive validation.
"""
from copy import deepcopy
import pytest
from app.domain.capabilities import effective_items, skills_for, validate_extraction, validate_interpretation
from app.schemas.cv import CvSkill, Extraction

BLOCKS = [{'id': 'b1', 'location': 'Page 1', 'text': 'Data Engineer, Acme (2019-2024): led the design of a Python ETL framework used by 40 analysts.'}]
QUOTE = {'source_id': 'b1', 'quote': 'led the design of a Python ETL framework used by 40 analysts'}


def extraction(levels):
    return {'items': [{'kind': 'experience', 'title': 'Data Engineer, Acme', 'description': 'Led design of a Python ETL framework.',
        'explicit': True, 'skill_names': ['Python'], 'skill_levels': levels,
        'evidence': [{'block_id': 'b1', 'excerpt': BLOCKS[0]['text']}]}]}


def judged(**changes):
    return {'skill_name': 'Python', 'level': 7, 'rationale': 'Led design of a framework used by 40 analysts.',
            'evidence': [QUOTE], **changes}


def test_default_extraction_has_no_skill_levels():
    assert Extraction.model_validate(extraction([])).items[0].skill_levels == []
    assert Extraction.model_validate({'items': [{k: v for k, v in extraction([])['items'][0].items() if k != 'skill_levels'}]}).items[0].skill_levels == []


def test_supported_cv_level_reaches_claim_and_skill():
    items = validate_extraction(extraction([judged()]), BLOCKS, 'cv-1')
    assert items[0]['skill_levels'][0]['evidence'] == [{'id': 'b1', 'location': 'Page 1', 'excerpt': QUOTE['quote']}]
    document = {'original_items': items, 'overlays': {}, 'clarifications': []}
    claim = effective_items(document)[0]['skill_claims'][0]
    # The CV never says the work was done independently, so the level is capped at guided use.
    assert claim['skill_level']['level'] == 3 and claim['skill_level']['source'] == 'cv'
    skill = CvSkill.model_validate(skills_for(effective_items(document))[0])
    assert skill.skill_level.level == 3 and skill.skill_level.status == 'rated' and skill.sources[0].skill_level.rationale


@pytest.mark.parametrize('bad', [
    judged(skill_name='SQL'),                                   # not a skill on this item
    judged(evidence=[{'source_id': 'b1', 'quote': 'invented'}]),  # not in the CV
    judged(evidence=[{'source_id': 'zz', 'quote': 'x'}]),       # unknown block
])
def test_unsupported_level_is_dropped_without_losing_the_item(bad):
    items = validate_extraction(extraction([bad]), BLOCKS, 'cv-1')
    assert items[0]['skill_levels'] == []
    assert 'skill_level' not in effective_items({'original_items': items, 'overlays': {}, 'clarifications': []})[0]['skill_claims'][0]


def test_duplicate_level_for_one_skill_keeps_the_first():
    items = validate_extraction(extraction([judged(), judged(level=9)]), BLOCKS, 'cv-1')
    assert [l['level'] for l in items[0]['skill_levels']] == [7]


def test_level_requires_rationale_and_evidence():
    with pytest.raises(ValueError): Extraction.model_validate(extraction([judged(evidence=[])]))
    with pytest.raises(ValueError): Extraction.model_validate(extraction([judged(level=11)]))


def source():
    return {'id': 'item-1', 'kind': 'project', 'title': 'Project', 'description': 'Team Python work',
        'skill_ids': ['skill:python'], 'skill_names': ['Python'], 'evidence': [], 'uncertainties': ['personal_contribution'],
        'proficiency': None, 'experience_months': None, 'start_date': None, 'end_date': None, 'ongoing': False,
        'skill_claims': [{'skill_id': 'skill:python', 'name': 'Python', 'attribution': 'unknown'}]}


ANSWER = 'I designed and ran the Python pipeline on my own and debugged production failures for two years.'


def level_payload(**claim):
    return {'item_id': 'item-1', 'answer_revision': 1, 'resolution': 'resolved',
        'claims': [{'skill_id': 'skill:python', 'name': 'Python', 'attribution': 'personal', 'assistance': 'independent',
            'skill_level': 7, 'skill_level_rationale': 'Owned a production pipeline and its failures.',
            'evidence_excerpt': ANSWER, 'changed_fields': ['attribution', 'assistance', 'skill_level'], **claim}],
        'resolved_uncertainties': ['personal_contribution'], 'remaining_uncertainties': []}


def question():
    return {'id': 'q1', 'uncertainty': 'personal_contribution', 'question': 'What did you do?', 'answer': ANSWER, 'answer_revision': 1}


def support():
    return frozenset({('skill:python', 'assistance'), ('skill:python', 'attribution')})


def test_review_answer_can_set_a_level():
    result = validate_interpretation(level_payload(), source(), question(), support())
    assert result['claims'][0]['skill_level'] == 7


@pytest.mark.parametrize('change', [
    {'attribution': 'team'},                                    # not the user's own work
    {'skill_level_rationale': None},                            # unexplained
    {'evidence_excerpt': None},                                 # no answer evidence
    {'skill_level': None},                                      # declared but absent
    {'changed_fields': ['attribution', 'assistance']},          # supplied outside declared changes
    {'skill_level': 11},                                  # not a level
])
def test_unsupported_review_level_is_rejected(change):
    payload = level_payload(**change)
    with pytest.raises(ValueError): validate_interpretation(payload, source(), question(), support())


def test_review_level_overrides_cv_level_and_aggregates_highest():
    items = validate_extraction(extraction([judged(level=3)]), BLOCKS, 'cv-1')
    item = items[0]
    skill = item['skill_ids'][0]
    interpretation = {'item_id': item['id'], 'answer_revision': 1, 'resolution': 'resolved', 'summary': 's',
        'claims': [{'skill_id': skill, 'name': 'Python', 'attribution': 'personal', 'assistance': 'unknown', 'proficiency': None,
            'experience_months': None, 'skill_level': 8, 'skill_level_rationale': 'Maintains it for the whole org.',
            'evidence_excerpt': 'I maintain Python for the whole org.', 'changed_fields': ['attribution', 'skill_level']}],
        'review_evidence': [], 'resolved_uncertainties': [], 'remaining_uncertainties': [], 'dates': None, 'statement_excerpt': None,
        'applied_sequence': 1}
    document = {'original_items': [deepcopy(item)], 'overlays': {}, 'clarifications': [
        {'id': 'q1', 'item_id': item['id'], 'interpretation': interpretation, 'reconciliation_required': False}]}
    claim = effective_items(document)[0]['skill_claims'][0]
    # Personal but not stated as independent: still assumed guided.
    assert claim['skill_level']['level'] == 3 and claim['skill_level']['source'] == 'review'
    assert claim['skill_level']['evidence'][0]['excerpt'] == 'I maintain Python for the whole org.'
    interpretation['claims'][0].update(assistance='independent', changed_fields=['attribution', 'assistance', 'skill_level'])
    claim = effective_items(document)[0]['skill_claims'][0]
    assert claim['skill_level']['level'] == 8
    assert skills_for(effective_items(document))[0]['skill_level']['level'] == 8


def test_ceiling_is_pessimistic_without_stated_independence():
    from app.domain.capabilities import level_ceiling
    project = {'kind': 'project', 'review_evidence': []}
    assert level_ceiling(project, {'skill_id': 'skill:python', 'attribution': 'personal', 'assistance': 'unknown'}) == 3
    assert level_ceiling(project, {'skill_id': 'skill:python', 'attribution': 'unknown', 'assistance': 'independent'}) == 3
    assert level_ceiling(project, {'skill_id': 'skill:python', 'attribution': 'personal', 'assistance': 'independent'}) == 10
    listed = {'kind': 'skill', 'review_evidence': []}
    assert level_ceiling(listed, {'skill_id': 'skill:python'}) == 2
    assert level_ceiling(listed, {'skill_id': 'skill:english', 'proficiency': 'native'}) == 5
