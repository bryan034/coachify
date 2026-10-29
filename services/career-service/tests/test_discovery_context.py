"""Discovery-only context retention and career-suggestion contract checks."""
import pytest
from pydantic import ValidationError
from app.schemas.discovery import ConversationMemory, Decision


def decision(**updates):
    return {'action':'SUGGEST_ROLES','scope':None,'question':None,
        'reply':'Here are some career directions to consider.',**updates}


@pytest.mark.parametrize('field,limit',[
    ('interests',6),('preferences',6),('rejected_directions',6),('open_questions',3),
    ('excluded_skills',60),('requested_skills',30),
])
def test_context_lists_keep_newest_unique_entries_without_renewing_duplicates(field,limit):
    values=[f'Item {i}' for i in range(limit+2)]+['  ITEM   0  ']
    if field in ('excluded_skills','requested_skills'):
        model=Decision.model_validate(decision(**{field:values}))
    else:model=ConversationMemory.model_validate({field:values})
    assert getattr(model,field)==[f'Item {i}' for i in range(2,limit+2)]


def test_duplicates_do_not_consume_slots_and_preserve_first_spelling():
    memory=ConversationMemory(interests=['  Building APIs ','building   apis','Data analysis'])
    assert memory.interests==['Building APIs','Data analysis']


@pytest.mark.parametrize('invalid',[None,42,True,'x'*161,'   '])
def test_invalid_entries_are_rejected_even_when_they_would_be_evicted(invalid):
    with pytest.raises(ValidationError):
        ConversationMemory(interests=[invalid,*[f'Interest {i}' for i in range(7)]])


def test_an_entire_string_cannot_replace_a_list():
    with pytest.raises(ValidationError):ConversationMemory(interests='software engineering')


def test_assignment_uses_the_same_retention_policy():
    memory=ConversationMemory()
    memory.open_questions=[f'Question {i}' for i in range(5)]
    assert memory.open_questions==['Question 2','Question 3','Question 4']


def test_five_complete_career_suggestions_are_accepted_but_six_are_rejected():
    suggestions=[{'area':f'Area {i}','explanation':'Why this direction may appeal.',
        'typical_work':'Representative work in this field.','difference':'How it differs from the other areas.'}
        for i in range(6)]
    assert len(Decision.model_validate(decision(recommendations=suggestions[:5])).recommendations)==5
    with pytest.raises(ValidationError):Decision.model_validate(decision(recommendations=suggestions))


def test_invalid_recommendations_and_extra_fields_remain_rejected():
    with pytest.raises(ValidationError):Decision.model_validate(decision(recommendations=[{'area':'Software'}]))
    with pytest.raises(ValidationError):ConversationMemory(unsupported_personal_fact='invented')


def test_citation_limits_and_entry_character_limits_are_not_relaxed():
    with pytest.raises(ValidationError):Decision.model_validate(decision(source_ids=[f's{i}' for i in range(11)]))
    with pytest.raises(ValidationError):Decision.model_validate(decision(requested_skills=['x'*161]))


def test_returned_memory_can_clear_resolved_questions_and_superseded_preferences():
    memory=ConversationMemory(open_questions=['Which kind of work appeals?'],preferences=['Work outdoors'])
    updated=ConversationMemory.model_validate({'open_questions':[],'preferences':['Work indoors']})
    assert updated.open_questions==[] and updated.preferences==['Work indoors']
    assert memory.open_questions==['Which kind of work appeals?']
