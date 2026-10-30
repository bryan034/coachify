"""Readiness is a backend decision grounded in this chat, not a model score."""
import pytest
from app.domain.discovery_readiness import grounded_understanding,missing_fields,ready_for_research,clarification_bundle,REQUIRED_FIELDS
from app.schemas.discovery import DiscoveryAnswer,DiscoveryUnderstanding,Decision,Scope


def test_assistant_text_and_unseen_quotes_cannot_supply_user_answers():
    proposed=DiscoveryUnderstanding(career_stage=DiscoveryAnswer(
        status='unsure',evidence='You can say unsure'))
    result=grounded_understanding(proposed,None,[{'role':'assistant','content':'You can say unsure'}],current_message='Finance')
    assert result.career_stage.status=='unanswered'
    assert len(missing_fields(result.model_dump()))==len(REQUIRED_FIELDS)


@pytest.mark.parametrize('status',['unsure','skipped'])
def test_uncertainty_requires_explicit_user_wording(status):
    proposed=DiscoveryUnderstanding(location=DiscoveryAnswer(status=status,evidence='Finance'))
    result=grounded_understanding(proposed,None,[],current_message='Finance')
    assert result.location.status=='unanswered'
    proposed.location.evidence='Skip the rest' if status=='skipped' else 'Not sure about the rest'
    result=grounded_understanding(proposed,None,[],current_message=proposed.location.evidence)
    assert result.location.status==status


def test_old_explicit_answers_survive_an_omitted_model_update_and_long_transcript():
    previous=DiscoveryUnderstanding(location=DiscoveryAnswer(status='known',value='Singapore',evidence='Singapore'))
    transcript=[{'role':'user','content':'Singapore'}]+[{'role':'user','content':'A later message'}]*40
    result=grounded_understanding(DiscoveryUnderstanding(),previous.model_dump(),transcript,current_message='More detail')
    assert result.location==previous.location


def test_all_unsure_answers_cannot_invent_a_research_field():
    value=DiscoveryUnderstanding(**{name:DiscoveryAnswer(status='unsure',evidence='Unsure about all of it')
                                   for name in DiscoveryUnderstanding.model_fields})
    assert missing_fields(value.model_dump())==[]
    decision=Decision(action='START_RESEARCH',scope=Scope(field='Finance',area='Finance'),
        reply='A guessed field',question=None,understanding=value)
    assert not ready_for_research(decision)


def test_repeating_a_field_as_the_role_does_not_resolve_targeted_scope():
    value=DiscoveryUnderstanding(
        field=DiscoveryAnswer(status='known',value='Finance',evidence='Finance'),
        role_family_or_work=DiscoveryAnswer(status='known',value='Finance',evidence='Finance'),
    )
    assert 'role_family_or_work' in missing_fields(value.model_dump())


def test_initial_bundle_has_six_ordered_topics_and_no_preface_or_extra_questions():
    questions=clarification_bundle({})
    assert len(questions)==6
    assert 'field' in questions[0] and 'specific role' in questions[0]
    assert questions[0].endswith('You can keep it broad.')
    assert 'interests you about' in questions[1]
    assert 'other interests' in questions[2] and 'unrelated' in questions[2]
    assert 'strongly want to avoid' in questions[3]
    assert 'career stage' in questions[4] and 'work preferences' in questions[5]
    assert all(question.endswith('You can say unsure.') for question in questions[1:])
    assert all(question.startswith(f'{i}. ') for i,question in enumerate(questions,1))
    assert 'clarify the remaining' not in '\n'.join(questions)
    assert 'location' not in '\n'.join(questions) and 'industry' not in '\n'.join(questions)


def test_removed_dictionaries_are_not_in_schema_and_legacy_broad_choice_is_preserved():
    schema=DiscoveryUnderstanding.model_json_schema()['properties']
    assert 'broad_exploration' not in schema and 'industry' not in schema
    assert 'other_interests' in schema
    value=DiscoveryUnderstanding.model_validate({
        'field':{'status':'known','value':'Finance','evidence':'Finance'},
        'role_family_or_work':{'status':'known','value':'Finance','evidence':'Finance'},
        'broad_exploration':{'status':'known','value':'yes','evidence':'keep it broad'},
        'industry':{'status':'known','value':'banking','evidence':'banking'}})
    assert value.role_family_or_work.value=='keep it broad'
    assert value.role_family_or_work.evidence=='keep it broad'
    assert 'broad_exploration' not in value.model_dump() and 'industry' not in value.model_dump()


def test_introduction_copy_and_legacy_opening_are_display_only():
    from app.domain.discovery_conversation import INTRODUCTION,LEGACY_INTRODUCTION,conversation_messages
    assert 'I will ask questions to understand your interests and personalise your goal for you' in INTRODUCTION
    assert 'one focused question' not in INTRODUCTION
    assert conversation_messages([{'role':'assistant','content':LEGACY_INTRODUCTION},
        {'role':'assistant','content':INTRODUCTION},{'role':'user','content':'Finance'}])==[{'role':'user','content':'Finance'}]
