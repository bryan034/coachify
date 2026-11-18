"""Role targets are planning standards on the shared 1-10 competence scale, never employer pass marks.

Levels rate understanding of the subject: 1-3 basic, 4-6 moderate, 7-8 good, 9-10 expert.
The research model decides the level from everything it knows about the role. It is given a weighted
reference score as guidance: a baseline for the role's seniority, adjusted by the skill's importance,
whether the role is named after it, the experience asked for, and how widely and how deeply public
research discusses it. Until the model has rated a skill, that reference is the target. A level the
employer states outright is a floor (or, for basic wording, a ceiling) on either. Every weight lives
in the tables below.
"""
import re
from elo_shared.competence_scale import MIN_LEVEL, MAX_LEVEL
from app.schemas.analysis import CompetenceTarget
from app.repositories.goals import now

# --- Ranking tables: edit these to re-rank targets -------------------------------------------
# Baseline by seniority, matched in order against the seniority level, then the role title.
SENIORITY_BASE = (
    (r'\b(principal|distinguished|fellow|director|vp|vice president|head of)\b', 9, 'principal or director role'),
    (r'\b(lead|staff|manager)\b', 8, 'lead role'),
    (r'\b(senior|sr)\b', 7, 'senior role'),
    (r'\b(mid|mid.level|intermediate)\b', 5, 'mid-level role'),
    (r'\b(junior|jr|graduate|entry|entry.level|associate|trainee|fresh)\b', 4, 'entry-level role'),
    (r'\b(intern|internship|attachment|placement)\b', 3, 'internship'),
)
# Used when neither the seniority level nor the title names a band.
EMPLOYMENT_BASE = {'internship': (3, 'internship'), 'full_time': (5, 'full-time role'), 'part_time': (4, 'part-time role'),
                   'contract': (5, 'contract role'), 'unknown': (5, 'role')}
PRIORITY_WEIGHT = {'required': (1, 'essential to the role'), 'preferred': (1, 'essential to the role'),
                   'unspecified': (-1, 'nice to have'), 'suggested': (-1, 'nice to have'), 'conflicting': (0, None)}
CORE_WEIGHT = (1, 'named in the role title')
# (minimum months, weight); the first row the stated months reach applies.
EXPERIENCE_WEIGHT = ((60, 2), (24, 1), (12, 0), (0, -1))
BREADTH_SOURCES, BREADTH_WEIGHT = 3, (1, 'discussed across {n} public sources')
INTERVIEW_WEIGHT = (1, 'probed in reported interviews')
# Stated employer wording: floors raise the score, the ceiling caps it.
STATED_FLOORS = ((r'\b(expert|expertise|mastery|authoritative)\b', 'expert', 9),
                 (r'\b(advanced|proficient|proficiency|complex|in.depth)\b', 'advanced', 7),
                 (None, 'intermediate', 5))
STATED_CEILING = (r'\b(beginner|basic|exposure)\b', 'beginner', 3)
# -------------------------------------------------------------------------------------------------

INTERVIEW_CATEGORY='interview_intelligence'


def _key(name): return ' '.join(name.casefold().split())


def _mentions(name, text):
    """Whole-phrase match that respects symbols in names such as C++ or C#."""
    name=_key(name)
    return len(name)>1 and bool(re.search(r'(?<![\w+#])'+re.escape(name)+r'(?![\w+#])', _key(text or '')))


def role_base(goal):
    for text in (getattr(goal,'seniority_level',None), getattr(goal,'role',None)):
        for pattern,level,label in SENIORITY_BASE:
            if text and re.search(pattern, text, re.I): return level,label
    return EMPLOYMENT_BASE.get(getattr(goal,'employment_type','unknown') or 'unknown', EMPLOYMENT_BASE['unknown'])


def stated_bounds(skill):
    """The employer's own stated level as (floor, ceiling); only employer skills state one."""
    if skill.origin!='employer': return None,None
    text=' '.join(v or '' for v in (skill.evidence, skill.context))
    for pattern,proficiency,level in STATED_FLOORS:
        if skill.required_proficiency==proficiency or pattern and re.search(pattern, text, re.I): return level,None
    pattern,proficiency,level=STATED_CEILING
    if skill.required_proficiency==proficiency or re.search(pattern, text, re.I): return None,level
    return None,None


def fresh_report(research):
    report=getattr(research, 'intelligence', None)
    if not report or report.status not in {'completed','partial'} or report.expires_at<=now(): return None
    return report


def finding_signals(name, categories):
    """Source ids of findings that discuss the skill, and whether interview findings probe it."""
    sources=[];interview=False
    for category,result in (categories or {}).items():
        for finding in result.findings:
            if not _mentions(name, finding.value): continue
            sources+=finding.source_ids;interview=interview or category==INTERVIEW_CATEGORY
    return list(dict.fromkeys(sources)),interview


def reference(skill, goal=None, categories=None):
    """The weighted reference score and the contribution of each weight, before stated bounds.

    `skill` needs name, priority and required_experience_months; `goal` role, seniority_level and
    employment_type; `categories` are fresh research findings by category, if any.
    """
    level,label=role_base(goal)
    reasons=[f'{label} baseline {level}']
    def add(weight, reason):
        nonlocal level
        if weight: level+=weight;reasons.append(f'{reason} {weight:+d}')
    add(*PRIORITY_WEIGHT.get(skill.priority,(0,None)))
    if _mentions(skill.name, getattr(goal,'role',None)): add(*CORE_WEIGHT)
    months=getattr(skill,'required_experience_months',None)
    if months is not None: add(next(w for m,w in EXPERIENCE_WEIGHT if months>=m), f'{months} months’ experience asked')
    sources,interview=finding_signals(skill.name, categories)
    if len(sources)>=BREADTH_SOURCES: add(BREADTH_WEIGHT[0], BREADTH_WEIGHT[1].format(n=len(sources)))
    if interview: add(*INTERVIEW_WEIGHT)
    return max(MIN_LEVEL, min(MAX_LEVEL, level)),reasons


def research_rating(skill, research):
    """The fresh model rating for this skill, the public sources it cites and those discussing the skill."""
    report=fresh_report(research)
    if not report: return None,[],[]
    urls={s.source_id:s.url for s in research.sources}
    rating=next((r for r in getattr(report,'skill_levels',None) or [] if _key(r.skill)==_key(skill.name)), None)
    findings={f.finding_id:f for result in report.categories.values() for f in result.findings}
    cited=[urls[s] for i in (rating.finding_ids if rating else []) if i in findings for s in findings[i].source_ids if s in urls]
    used=[urls[s] for s in finding_signals(skill.name, report.categories)[0] if s in urls]
    return rating,list(dict.fromkeys(cited)),list(dict.fromkeys(used))


def target_for(skill, research=None, goal=None):
    report=fresh_report(research)
    employment=getattr(report,'employment_type','unknown')
    if goal is not None and employment!='unknown' and goal.employment_type=='unknown':
        goal=goal.model_copy(update={'employment_type':employment})
    ref,reasons=reference(skill, goal, report.categories if report else None)
    rating,cited,used=research_rating(skill, research)
    level=rating.level if rating else ref
    floor,ceiling=stated_bounds(skill);bound=None
    if floor and level<floor: level,bound=floor,f'the job description asks for at least {floor}'
    if ceiling and level>ceiling: level,bound=ceiling,f'the job description asks only for basic understanding ({ceiling})'
    explanation=f'Role target: {level}/10. '
    if bound: explanation+=f'Set to {level} because {bound}. '
    explanation+=f"Weighted reference {ref}/10: {'; '.join(reasons)}. "
    if rating:
        explanation+='Rated using cited public research. ' if cited else 'No research findings were cited for the rating. '
    elif used:
        explanation+='Research discussing this skill was weighed. '
    explanation+='This is a planning estimate, not an employer test score.'
    if rating:
        remaining=600-len(explanation)-1
        rationale=rating.rationale
        if len(rationale)>remaining: rationale=rationale[:remaining-1].rstrip()+'…'
        explanation+=f' {rationale}'
    links=cited if rating else used
    basis='job_description' if bound else 'research' if links else 'inferred'
    return CompetenceTarget(level=level, basis=basis, explanation=explanation,
                            source_urls=list(dict.fromkeys([*links,*skill.source_urls]))[:10])


def calibrated_goal(goal, research=None):
    return goal.model_copy(update={'skills':[s.model_copy(update={'competence_target':target_for(s,research,goal)}) for s in goal.skills]})
