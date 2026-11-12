"""Conservative evidence ceilings shared by both Assessment scoring paths."""
import math
import re

RUBRIC_VERSION='evidence-role-v2'


def role_level(requirement):
    target=requirement.get('competence_target') or {}
    if isinstance(target.get('level'),int) and 1<=target['level']<=10:
        return target['level']
    return 9 if requirement.get('required_proficiency')=='advanced' else 8


def source_level(record):
    """Return an evidence ceiling, with 3 explicitly provisional for ambiguous projects."""
    if record.get('attribution') in {'team','observed','denied'} or record.get('unscoped_item'): return None
    project=record.get('source_kind') in {'project','experience'}
    if record.get('support_uncertain') or record.get('attribution')!='personal':
        return 3 if project else None
    facts=record.get('review_facts',[])
    if any(f['status']=='conflicting' and f['field'] in {'personal_contribution','skill_use','assistance','outcome'} for f in facts):
        return 3 if project else None
    known={f['field'] for f in facts if f['status']=='supported'}
    if any(f['field']=='replication_confidence' and f['status']=='supported' and
           re.search(r'\b(low|unsure|not confident|need help|cannot repeat|can.t repeat)\b',f.get('value') or '',re.I) for f in facts): return 3
    outcomes=[f for f in facts if f['field']=='outcome' and f['status']=='supported']
    if any(re.search(r'\b(failed|unsuccessful|unfinished|incomplete|not completed|not successful|did not work|could not|couldn.t)\b',f.get('value') or '',re.I) for f in outcomes): return 3
    independent=record.get('assistance')=='independent' or record.get('application_level') in {'independent_application','complex_application'}
    if not independent: return 3
    # Independence alone does not establish successful delivery.
    successful=any(f.get('attribution') not in {'team','observed','denied'} and
        re.search(r'\b(success\w*|succeeded|delivered|completed|achieved|passed|working|improved|reduced|increased|met|deployed|launched)\b',f.get('value') or '',re.I) for f in outcomes)
    if not successful: return 4
    if not {'complexity','problem_solving'}<=known: return 5
    # High levels need successful, complex and sustained skill-specific work.
    if not {'frequency','recency'}<=known or (record.get('experience_months') or 0)<24: return 7
    return 9


def evidence_level(records, proposed=None):
    levels=[level for record in records if (level:=source_level(record)) is not None]
    if not levels: return None
    ceiling=max(levels)
    # Missing ownership is an explicit provisional baseline, never verified mastery.
    if ceiling<=5: return ceiling
    return min(proposed,ceiling) if proposed is not None else ceiling


def goal_score(have,need):
    # Only actual target attainment reaches 10; rounding must not turn 9.6 into 10.
    return min(10,math.floor(100*have/need)/10)
