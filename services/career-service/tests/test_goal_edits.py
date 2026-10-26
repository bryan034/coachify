"""Chat edits are narrow, schema-checked changes; unrelated values remain intact."""
import pytest
from pydantic import ValidationError
from app.ai.adapter import AIAdapter,AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.goal_edit_contracts import GoalChange,GoalEditDecision
from app.domain.goal_edits import apply_changes,edit_context
from app.schemas.jd import JDExtraction
import json


def goal():
    return JDExtraction(role='Analyst',field='Data',company='Example',location='Singapore',skills=[
        {'item_id':'sql','skill_id':'language.sql','name':'SQL','category':'Technical','priority':'required','origin':'employer','evidence':'SQL required.',
         'group_id':'languages','group_operator':'any'},
        {'item_id':'python','skill_id':'language.python','name':'Python','category':'Technical','priority':'preferred','origin':'employer','evidence':'Python preferred.',
         'group_id':'languages','group_operator':'any'}],responsibilities=['Analyse data','Build reports'],
        non_skill_requirements=[{'requirement_id':'degree','category':'qualification','description':'A degree','priority':'required','evidence':'A degree is required.'}])


def change(collection,action,reference=None,field=None,value=None):
    return GoalChange(collection=collection,action=action,reference=reference,field=field,value=value)


def test_metadata_edit_preserves_every_untouched_item_and_identity():
    before=goal();after=apply_changes(before,[change('goal','set',field='location',value='London')],'Change location to London')
    assert after.location=='London' and before.location=='Singapore'
    assert after.skills==before.skills and after.non_skill_requirements==before.non_skill_requirements
    assert after.responsibilities==before.responsibilities and after.role==before.role


def test_priority_is_a_user_correction_without_rewriting_employer_evidence_or_groups():
    before=goal();after=apply_changes(before,[change('skills','set','s0','priority','preferred')],'Make SQL preferred')
    item=after.skills[0]
    assert item.item_id=='sql' and item.priority=='preferred' and item.priority_origin=='user_declaration'
    assert item.origin=='employer' and item.evidence=='SQL required.' and item.group_id=='languages' and item.group_operator=='any'
    assert after.skills[1]==before.skills[1]


def test_new_skills_and_modified_requirements_are_user_declarations():
    before=goal();after=apply_changes(before,[change('skills','add','new1','name','AWS'),change('skills','add','new1','category','Technical'),
        change('conditions','set','c0','description','A diploma')],'Add AWS and change the qualification to a diploma')
    assert after.skills[-1].name=='AWS' and after.skills[-1].origin=='user_declaration' and after.skills[-1].priority=='unspecified'
    assert after.non_skill_requirements[0].origin=='user_declaration' and after.non_skill_requirements[0].requirement_id=='degree'
    assert after.skills[:2]==before.skills


def test_list_references_stay_stable_across_removes_updates_and_additions():
    after=apply_changes(goal(),[change('responsibilities','remove','r0'),change('responsibilities','set','r1','text','Build dashboards'),
        change('responsibilities','add','new1','text','Present findings'),change('skills','remove','s0'),
        change('skills','set','s1','required_proficiency','advanced')],'Remove SQL and update these responsibilities')
    assert after.responsibilities==['Build dashboards','Present findings']
    assert len(after.skills)==1 and after.skills[0].item_id=='python' and after.skills[0].required_proficiency=='advanced'


def test_clear_then_add_replaces_only_the_requested_list():
    before=goal();after=apply_changes(before,[change('skills','clear'),change('skills','add','new1','name','Communication'),
        change('skills','add','new1','category','Transferable')],'Replace all skills with Communication')
    assert [s.name for s in after.skills]==['Communication'] and after.non_skill_requirements==before.non_skill_requirements


@pytest.mark.parametrize('changes',[
    [change('skills','set','s999','name','Invented')],
    [change('goal','set',field='role',value=None)],
    [change('skills','set','s0','priority','nonsense')],
    [change('skills','add','new1','name','AWS')],
    [change('goal','set',field='name',value='Other')],
    [change('skills','set','s0','required_experience_months',-1)],
])
def test_invalid_change_cannot_produce_a_saveable_goal(changes):
    with pytest.raises(AIError,match='invalid_output'):apply_changes(goal(),changes,'Synthetic correction')


def test_decision_requires_real_changes_and_does_not_allow_unrelated_mutations():
    with pytest.raises(ValidationError):GoalEditDecision(status='ready',reply='Saved',intent='No changes')
    with pytest.raises(ValidationError):GoalEditDecision(status='off_topic',reply='No',intent='Unrelated',changes=[change('goal','set',field='company',value='Other')])
    with pytest.raises(ValidationError):GoalChange(collection='goal',action='set',field='password',value='disallowed')


def test_edit_context_omits_evidence_and_record_ids_and_does_not_lose_change_values():
    context=edit_context(goal(),{'intent':'Change location','question':'Where?','changes':[]})
    text=json.dumps(context)
    assert 'SQL required.' not in text and 'requirement_id' not in text and 'item_id' not in text
    request=AIInput(stage='goal_edit',context=text,conversation=[{'role':'user','content':'London'}])
    payload=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),None)._payload(request)
    assert payload['max_completion_tokens']==2048
    assert json.loads(payload['messages'][1]['content'])['context']['pending_edit']['question']=='Where?'
