"""Role targets are planning standards on the shared 1-10 competence scale, never employer pass marks.

1 = not competent, 5 = works independently and understands the skill, 10 = the most complex work.
The level a role needs is rated by the research model from cited public findings. A level the
job description states outright is the floor, and without a rating the stated wording decides.
"""
import re
from elo_shared.competence_scale import INDEPENDENT_LEVEL
from app.schemas.analysis import CompetenceTarget
from app.repositories.goals import now

STATED=r'\b(familiar|familiarity|advanced|expert|expertise|mastery|proficien\w*|beginner|basic|working knowledge|in.depth)\b'


def level_for(text, proficiency=None):
    if re.search(r'\b(expert|expertise|mastery|authoritative)\b', text, re.I): return 9
    if proficiency == 'advanced' or re.search(r'\b(advanced|proficient|proficiency|complex|in.depth)\b', text, re.I): return 7
    if proficiency == 'beginner' or re.search(r'\b(beginner|basic|exposure)\b', text, re.I): return 3
    # Familiarity and unstated expectations both mean doing the work alone with understanding.
    return INDEPENDENT_LEVEL


def _key(name): return ' '.join(name.casefold().split())


def researched(skill, research):
    """The fresh research rating for this skill with the public sources behind it, if any."""
    report=getattr(research, 'intelligence', None)
    if not report or report.status not in {'completed','partial'} or report.expires_at<=now(): return None
    rating=next((r for r in getattr(report, 'skill_levels', None) or [] if _key(r.skill)==_key(skill.name)), None)
    if not rating: return None
    findings={f.finding_id:f for result in report.categories.values() for f in result.findings}
    sources={s.source_id:s.url for s in research.sources}
    urls=[sources[s] for i in rating.finding_ids if i in findings for s in findings[i].source_ids if s in sources]
    return rating, list(dict.fromkeys(urls))


def target_for(skill, research=None):
    text=' '.join(v or '' for v in (skill.evidence, skill.context))
    level=level_for(text, skill.required_proficiency)
    stated=bool(skill.required_proficiency or re.search(STATED, text, re.I))
    found=researched(skill, research)
    if found:
        rating,urls=found
        # The employer's own stated level is a floor; research supplies the practical depth.
        final=max(level, rating.level) if stated and skill.origin=='employer' else rating.level
        return CompetenceTarget(level=final, basis='research' if urls else 'inferred',
            explanation=f'Role target: {final}/10. {rating.rationale} '
                +('Rated from public research on this role. ' if urls else 'Rated from the role itself; research did not address this skill. ')
                +('The job description states a higher level, which is kept. ' if final>rating.level else '')
                +'This is a planning estimate, not an employer test score.',
            source_urls=list(dict.fromkeys([*urls,*skill.source_urls]))[:10])
    return CompetenceTarget(level=level, basis='job_description' if stated and skill.origin=='employer' else 'inferred',
        explanation=f'Role target: {level}/10. '+('Taken from the stated skill expectations.' if stated else
            'The description does not state a level, so working independently with understanding (5/10) is assumed until research rates it.')+
            ' This is a planning standard, not an employer test score.',
        source_urls=skill.source_urls[:10])


def calibrated_goal(goal, research=None):
    return goal.model_copy(update={'skills':[s.model_copy(update={'competence_target':target_for(s,research)}) for s in goal.skills]})
