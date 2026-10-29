"""Discovery-only, evidence-backed readiness checks; no model or network calls."""
import re
from app.schemas.discovery import DiscoveryAnswer,DiscoveryUnderstanding,Decision

# Seven stored answers, presented as the user's six requested question topics.
REQUIRED_FIELDS=('field','role_family_or_work','interest','other_interests','avoided_activities','career_stage','work_preferences')
QUESTIONS = {
    'field': 'Which field and, if possible, specific role would you like to explore? You can keep it broad.',
    'role_family_or_work': 'Is there a specific role or kind of work you want to explore within this field? You can keep it broad.',
    'interest': 'What interests you about this field? You can say unsure.',
    'other_interests': 'What other interests do you have, related or unrelated to this field? You can say unsure.',
    'avoided_activities': 'What activities do you strongly want to avoid? You can say unsure.',
    'career_stage': 'What career stage are you looking for: internship, starting out, or experienced? You can say unsure.',
    'work_preferences': 'What work preferences or constraints matter to you? You can say unsure.',
}


def keeps_broad(value):
    return value.role_family_or_work.status=='known' and value.role_family_or_work.value=='keep it broad'


def clarification_bundle(understanding):
    missing=missing_fields(understanding)
    lines=[]
    if 'field' in missing:lines.append(QUESTIONS['field'])
    elif 'role_family_or_work' in missing:lines.append(QUESTIONS['role_family_or_work'])
    for name in ('interest','other_interests','avoided_activities','career_stage','work_preferences'):
        if name in missing:lines.append(QUESTIONS[name])
    if not lines:lines=[QUESTIONS['field']]
    return [f'{i}. {question}' for i,question in enumerate(lines,1)]


def grounded_understanding(proposed, previous, messages, *, changed_field=False, current_message=''):
    """Missing is never converted to unsure. Only user-backed updates are kept.

    Meaning/inference is assessed by Gemini; Python verifies the supplied evidence
    actually belongs to this chat. Old explicit answers survive bounded history.
    """
    result=DiscoveryUnderstanding.model_validate(previous or {})
    if changed_field:
        for name in ('field','role_family_or_work','interest','skill_ambiguity'):
            setattr(result,name,DiscoveryAnswer())
    user_messages=[m['content'] for m in messages if m['role']=='user']+[current_message]
    for name in DiscoveryUnderstanding.model_fields:
        answer=getattr(proposed,name)
        if answer.status=='unanswered':continue
        if not answer.evidence or not any(answer.evidence in text for text in user_messages):continue
        if answer.status in ('unsure','skipped') and not re.search(
            r"\b(?:unsure|uncertain|undecided|unknown|unspecified|not sure|not decided|not certain|don['’]?t know|do not know|idk|skip|"
            r"leave.{0,12}open|no preference|no particular|any(?:thing|where)?|open to|don['’]?t mind|do not mind)\b",
            answer.evidence,re.I):continue
        if changed_field and name in ('field','role_family_or_work','interest','skill_ambiguity') and answer.evidence not in current_message:continue
        if answer.status=='known' and not answer.value:continue
        if name=='skill_ambiguity' and answer.status=='known' and answer.value not in ('material','resolved'):continue
        setattr(result,name,answer)
    return result


def missing_fields(understanding):
    value=DiscoveryUnderstanding.model_validate(understanding or {})
    missing=[name for name in REQUIRED_FIELDS if (answer:=getattr(value,name)).status=='unanswered'
             or not answer.evidence or answer.status=='known' and not answer.value]
    if (value.role_family_or_work.status=='known' and value.field.status=='known'
        and value.role_family_or_work.value and value.field.value
        and value.role_family_or_work.value.casefold()==value.field.value.casefold()
        and not keeps_broad(value)):
        if 'role_family_or_work' not in missing:missing.insert(0,'role_family_or_work')
    if (value.skill_ambiguity.status=='known' and value.skill_ambiguity.value=='material'
        and not keeps_broad(value)):
        if 'role_family_or_work' not in missing:missing.insert(0,'role_family_or_work')
    return missing


def ready_for_research(decision):
    value=Decision.model_validate(decision)
    return bool(value.scope and value.understanding.field.status=='known' and not missing_fields(value.understanding.model_dump())
        and value.scope.field.casefold() not in ('unsure','unknown','unspecified','skip'))


def research_context(understanding):
    value=DiscoveryUnderstanding.model_validate(understanding or {})
    return {name:answer.value for name in ('role_family_or_work','interest','avoided_activities','work_preferences')
            if (answer:=getattr(value,name)).status=='known'}
