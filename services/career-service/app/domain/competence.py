"""Role targets are planning standards, never invented employer pass marks."""
import re
from app.schemas.analysis import CompetenceTarget
from app.repositories.goals import now


def level_for(text, proficiency=None):
    if re.search(r'\b(expert|expertise|mastery|authoritative)\b', text, re.I): return 10
    if proficiency == 'advanced' or re.search(r'\b(advanced|proficient|proficiency|complex|in.depth)\b', text, re.I): return 9
    # Familiarity is a role-ready standard, not basic exposure to a tool.
    if re.search(r'\bfamiliar(?:ity)?\b', text, re.I): return 8
    if proficiency == 'beginner': return 7
    return 8


def target_for(skill, research=None):
    text=' '.join(v or '' for v in (skill.evidence, skill.context))
    level=level_for(text, skill.required_proficiency)
    stated=bool(skill.required_proficiency or re.search(r'\b(familiar|familiarity|advanced|expert|proficien\w*)\b', text, re.I))
    target=CompetenceTarget(level=level, basis='job_description' if stated and skill.origin=='employer' else 'inferred',
        explanation=f'Role target: {level}/10. '+('Calibrated from the stated skill expectations.' if stated else 'Conservative role-readiness estimate; the description does not specify a level.')+
                    ' Familiarity requires at least 8/10; this is a planning standard, not an employer test score.',
        source_urls=skill.source_urls[:10])
    report=getattr(research, 'intelligence', None)
    category=report.categories.get('interview_intelligence') if report else None
    if not category or category.status not in {'completed','partial'} or (category.expires_at or report.expires_at)<=now(): return target
    sources={s.source_id:s.url for s in research.sources}
    relevant=[]
    for finding in category.findings:
        if finding.field!='preparation_topics' or finding.confidence not in {'high','medium'} or finding.conflict_group: continue
        # Exact token boundaries avoid matching R in React or Java in JavaScript.
        pattern=r'(?<!\w)'+re.escape(skill.name)+r'(?!\w)'
        if not re.search(pattern, finding.value, re.I): continue
        # Only the cited passages can raise the target, not an unsupported summary.
        quoted=' '.join(finding.quotes)
        if not re.search(pattern, quoted, re.I): continue
        relevant.append((level_for(quoted), finding))
    if relevant:
        depth,finding=max(relevant, key=lambda pair:pair[0])
        target=CompetenceTarget(level=max(level,depth), basis='research',
            explanation=f'Role target: {max(level,depth)}/10. Public role/interview evidence informs the expected depth. '+
                ('Related-role evidence is advisory. ' if finding.scope!='exact' else '')+
                'Research can raise, but cannot lower, the description-based target. This is a planning estimate.',
            source_urls=list(dict.fromkeys([*target.source_urls,*[sources[s] for s in finding.source_ids if s in sources]]))[:10])
    return target


def calibrated_goal(goal, research=None):
    return goal.model_copy(update={'skills':[s.model_copy(update={'competence_target':target_for(s,research)}) for s in goal.skills]})
