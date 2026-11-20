"""Checks on model-extracted JD skills and requirements before they are used."""
from app.ai.errors import AIError


def validate_skills(skills, message='', existing=(), *, extraction=False):
    if len({(' '.join(s.name.casefold().split()),' '.join(s.category.casefold().split())) for s in skills}) != len(skills):
        raise AIError('invalid_output', True, reason='duplicate_skill', fields=('name',))
    for skill in skills:
        if skill.origin == 'employer' and skill.priority == 'suggested':
            raise AIError('invalid_output', True, reason='unexpected_origin', fields=('origin', 'priority'))
        if skill.origin == 'user_declaration' and (extraction or (
                skill not in existing and (not skill.evidence or skill.evidence not in message))):
            raise AIError('invalid_output', True, reason='source_quote', fields=('evidence',))
        if skill.origin == 'generated_guidance' and (skill.priority != 'suggested' or skill.evidence is not None):
            raise AIError('invalid_output', True, reason='unexpected_origin', fields=('origin',))


def validate_extraction(output, source_url):
    validate_skills(output.skills, extraction=True)
    # Provenance comes from the input transport, not an AI-generated URL.
    output.job_url = source_url
    for item in [*output.skills,*output.non_skill_requirements]:
        if item.origin=='employer' and item.priority in ('required','preferred','conflicting'):
            item.priority_evidence=item.priority_evidence or item.evidence
            if not item.priority_evidence:item.priority='unspecified'
