"""Cross-service snapshot checks; no foreign database reads."""
from app.schemas.analysis import CareerGoal, CvSnapshot, InputVersions, InterviewResearch, SkillGapAnalysis, ResearchContext


class ContractConflict(ValueError):
    """Recoverable missing, foreign or stale input; never publish this result."""


def validate_inputs(owner: str, expected: InputVersions, cv: CvSnapshot | None,
                    goal: CareerGoal | None, research: list[InterviewResearch], profile_version: int):
    if cv is None or goal is None:
        raise ContractConflict('A referenced CV or career goal is unavailable.')
    if cv.user_id != owner or goal.user_id != owner:
        raise ContractConflict('Input ownership mismatch.')
    if goal.readiness != 'ready':
        raise ContractConflict('The selected career goal still needs skill requirements.')
    if cv.extraction_status != 'succeeded':
        raise ContractConflict('Select a successfully extracted CV.')
    actual = InputVersions(cv_id=cv.id, cv_version=cv.version, extraction_version=cv.extraction_version,
        profile_version=profile_version, career_goal_id=goal.id, career_goal_version=goal.version,
        generation_version=goal.generation_version,
        research=[{'id': r.id, 'version': r.version} for r in research])
    if actual != expected or cv.profile_version != profile_version:
        raise ContractConflict('Inputs changed. Refresh and request a new analysis.')
    goal_context = ResearchContext(company=goal.company, field=goal.field, role=goal.role,
                                   location=goal.location, seniority_level=goal.seniority_level).reuse_key()
    if any(r.context_key != goal_context for r in research):
        raise ContractConflict('Research context does not match the selected goal.')
    if any(r.research_status not in ('succeeded', 'no_findings') for r in research):
        raise ContractConflict('Research is unavailable; explicitly request a partial analysis instead.')
    if any(r.skill_mapping_version != goal.skill_mapping_version for r in research) or cv.skill_mapping_version != goal.skill_mapping_version:
        raise ContractConflict('Skill mapping versions disagree.')


def validate_analysis(result: SkillGapAnalysis, cv: CvSnapshot, goal: CareerGoal,
                      research: list[InterviewResearch], profile_version: int):
    validate_inputs(result.user_id, result.inputs, cv, goal, research, profile_version)
    if result.skill_mapping_version != goal.skill_mapping_version:
        raise ContractConflict('Analysis skill mapping version disagrees.')
    if not {g.skill_id for g in result.job_skill_gaps} <= {s.skill_id for s in goal.skills}:
        raise ContractConflict('Job gaps must reference career goal skills.')
    if not {g.skill_id for g in result.interview_prep_gaps} <= {s.skill_id for r in research for s in r.skills}:
        raise ContractConflict('Interview gaps must reference researched skills.')
    cv_skills = {s.skill_id: s for s in cv.skills}
    for gap in [*result.job_skill_gaps, *result.interview_prep_gaps]:
        original = cv_skills.get(gap.skill_id)
        if gap.cv_proficiency != (original.proficiency if original else None):
            raise ContractConflict('A model cannot invent CV proficiency.')
