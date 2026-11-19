"""Role targets on the shared 1-10 competence scale.

Levels rate understanding of the subject: 1-3 basic, 4-6 moderate, 7-8 good, 9-10 expert.
The research model decides the level, given a weighted reference score as a guideline: a baseline for the
role's seniority, adjusted by how selective the hiring is, the skill's importance, whether it defines the
role, the experience asked for, and how widely and deeply public research discusses it. Until the model
has rated a skill, that reference is the target. A level the employer states outright is a floor (or,
for basic wording, a ceiling) on either. Every weight lives in the tables below.
"""
import re
from elo_shared.competence_scale import MIN_LEVEL, MAX_LEVEL
from app.schemas.analysis import CompetenceTarget, TargetExample
from app.repositories.goals import now

# --- Ranking tables: edit these to re-rank targets -------------------------------------------
# Baseline by seniority, matched in order against the seniority level, then the role title.
SENIORITY_BASE = (
    (r'\b(principal|distinguished|fellow|director|vp|vice president|head of)\b', 9, 'principal or director role'),
    (r'\b(lead|staff|manager)\b', 8, 'lead role'),
    (r'\b(senior|sr)\b', 7, 'senior role'),
    (r'\b(mid|mid.level|intermediate)\b', 6, 'mid-level role'),
    (r'\b(junior|jr|graduate|entry|entry.level|associate|trainee|fresh)\b', 5, 'entry-level role'),
    (r'\b(intern|internship|attachment|placement)\b', 5, 'internship'),
)
# Used when neither the seniority level nor the title names a band.
EMPLOYMENT_BASE = {'internship': (5, 'internship'), 'full_time': (5, 'full-time role'), 'part_time': (5, 'part-time role'),
                   'contract': (5, 'contract role'), 'unknown': (5, 'role')}
PRIORITY_WEIGHT = {'required': (2, 'essential to the role'), 'preferred': (2, 'essential to the role'),
                   'unspecified': (1, 'nice to have'), 'suggested': (1, 'nice to have'), 'conflicting': (0, None)}
# A skill sharing a significant word with the role title defines the role.
CORE_WEIGHT = (2, 'core to the role title')
GENERIC_TITLE_WORDS = frozenset('''intern internship trainee graduate junior senior lead principal staff head manager associate
    analyst specialist officer executive assistant consultant engineer engineering developer scientist summer
    winter spring autumn off cycle programme program role position team and of the for with in to'''.split())
# Highly selective hiring, matched against the role, field and company; applies once per goal, to every skill.
SELECTIVE_HIRING = (
    (r'\b(quant|quantitative)\b.{0,40}\b(trad\w*|research\w*|analyst|developer|strateg\w*)\b|\b(market.mak\w*|prop(rietary)? trading|algorithmic trading|high.frequency trading)\b',
     'quantitative trading or research'),
    (r'\b(investment banking|private equity|hedge funds?|sales (and|&) trading|global markets|equity research|leveraged finance|mergers (and|&) acquisitions|m&a)\b',
     'investment banking, markets or buy-side'),
    (r'\b(optiver|jane street|citadel|imc trading|susquehanna|hudson river trading|jump trading|drw|two sigma|d\.?\s?e\.? shaw|tower research|virtu|flow traders|da vinci|akuna|squarepoint|millennium|point72|goldman sachs|morgan stanley|j\.?\s?p\.? ?morgan|jpmorgan|evercore|lazard|rothschild|centerview|moelis|pjt partners|blackstone|kkr|carlyle|temasek|gic|mckinsey|boston consulting group|bcg|bain (&|and) company)\b',
     'highly selective employer'),
)
SELECTIVE_WEIGHT = 2
# (minimum months, weight); the first row the stated months reach applies.
EXPERIENCE_WEIGHT = ((37, 3), (13, 2), (0, 1))
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


SKILL_FILLER_WORDS = frozenset('and of the for with in to a an skills skill knowledge'.split())


def _words(text): return re.findall(r'[\w+#]+', _key(text or ''))


def _stem(word):
    """Light suffix folding so "solve", "solving" and "problems" match "solving" and "problem"."""
    for suffix in ('ations','ation','ings','ing','ers','er','ies','es','ed','s','e'):
        if word.endswith(suffix) and len(word)-len(suffix)>=3 and not (suffix=='s' and word.endswith('ss')):
            word=word[:-len(suffix)];break
    return word[:-1] if len(word)>3 and word[-1]==word[-2] else word


def _similar(a, b):
    """Words sharing a long enough stem, e.g. quant/quantitative or trader/trading."""
    if a==b: return True
    n=len(next((a[:i] for i in range(min(len(a),len(b)),0,-1) if a[:i]==b[:i]), ''))
    return n>=4 and n*3>=2*min(len(a),len(b))


def _mentions(name, text):
    """Whole phrase (respecting symbols such as C++ or C#), or every significant word of the skill in any form or order."""
    name=_key(name)
    if len(name)<=1: return False
    if re.search(r'(?<![\w+#])'+re.escape(name)+r'(?![\w+#])', _key(text or '')): return True
    wanted={_stem(w) for w in _words(name) if w not in SKILL_FILLER_WORDS and len(w)>1}
    return bool(wanted) and wanted<={_stem(w) for w in _words(text)}


def core_to_role(name, title):
    title_words=[w for w in _words(title) if w not in GENERIC_TITLE_WORDS and len(w)>1]
    return any(_similar(s,t) for s in _words(name) if s not in SKILL_FILLER_WORDS and len(s)>1 for t in title_words)


def selective_hiring(goal):
    text=' '.join(getattr(goal,k,None) or '' for k in ('role','field','company'))
    return next((label for pattern,label in SELECTIVE_HIRING if re.search(pattern, text, re.I)), None)


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

    `skill` needs name, priority and required_experience_months; `goal` role, seniority_level,
    employment_type and optionally field and company; `categories` are fresh research findings by category, if any.
    """
    level,label=role_base(goal)
    reasons=[f'{label} baseline {level}']
    def add(weight, reason):
        nonlocal level
        if weight: level+=weight;reasons.append(f'{reason} {weight:+d}')
    selective=selective_hiring(goal)
    if selective: add(SELECTIVE_WEIGHT, f'selective hiring ({selective})')
    add(*PRIORITY_WEIGHT.get(skill.priority,(0,None)))
    if core_to_role(skill.name, getattr(goal,'role',None)): add(*CORE_WEIGHT)
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


def _plain_reason(reason):
    """A reference weight without its number, e.g. "internship baseline 5" -> "internship"."""
    return re.sub(r'(\s+baseline)?\s+[+-]?\d+$', '', reason)


def _fit(text, room):
    return text if len(text)<=room else text[:max(room-1,0)].rstrip()+'…'


def reported_examples(rating, research):
    """The rating's reported examples, each linked to the first public source of the finding it restates."""
    if not rating: return []
    urls={s.source_id:s.url for s in research.sources}
    findings={f.finding_id:f for result in research.intelligence.categories.values() for f in result.findings}
    examples=[]
    for example in getattr(rating,'reported_examples',None) or []:
        finding=findings.get(example.finding_id)
        if not finding: continue
        url=next((urls[s] for s in finding.source_ids if s in urls), None)
        examples.append(TargetExample(text=_fit(example.text,600), source_url=url))
    return examples[:2]


def target_for(skill, research=None, goal=None):
    report=fresh_report(research)
    employment=getattr(report,'employment_type','unknown')
    if goal is not None and employment!='unknown' and goal.employment_type=='unknown':
        goal=goal.model_copy(update={'employment_type':employment})
    ref,reasons=reference(skill, goal, report.categories if report else None)
    rating,cited,used=research_rating(skill, research)
    level=rating.level if rating else ref
    floor,ceiling=stated_bounds(skill);bound=None
    if floor and level<floor: level,bound=floor,f'The job description asks for at least {floor}.'
    if ceiling and level>ceiling: level,bound=ceiling,f'The job description asks only for basic understanding ({ceiling}).'
    # Research rated it: the model's own reason. Otherwise the role facts the estimate rests on, without weights.
    reason=_fit(rating.rationale,600) if rating else None
    facts=[f for f in (_plain_reason(r) for r in reasons) if f!='role']
    summary=reason or ('Research hasn’t rated this skill yet, so elo estimated it from '+(f"the role: {'; '.join(facts)}." if facts else 'the role.'))
    explanation=_fit(f'{bound} {summary}' if bound else summary, 600)
    demand=getattr(rating,'employer_demand',None) if rating else None
    links=cited if rating else used
    basis='job_description' if bound else 'research' if links else 'inferred'
    return CompetenceTarget(level=level, basis=basis, explanation=explanation,
                            employer_demand=_fit(demand,600) if demand else None,
                            reported_examples=reported_examples(rating, research),
                            rating_reason=_fit(f'{bound} {reason}',600) if bound and reason else reason,
                            source_urls=list(dict.fromkeys([*links,*skill.source_urls]))[:10])


def calibrated_goal(goal, research=None):
    return goal.model_copy(update={'skills':[s.model_copy(update={'competence_target':target_for(s,research,goal)}) for s in goal.skills]})
