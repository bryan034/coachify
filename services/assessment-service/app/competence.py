"""Conservative evidence ceilings shared by both Assessment scoring paths."""
import math
import re
from elo_shared.competence_scale import INDEPENDENT_LEVEL

# v4: reuse reviewed CV levels on the shared scale, retaining conservative evidence ceilings.
RUBRIC_VERSION='evidence-role-v4'
_NOT_PERSONAL={'team','observed','denied'}


def role_level(requirement):
    target=requirement.get('competence_target') or {}
    if isinstance(target.get('level'),int) and 1<=target['level']<=10:
        return target['level']
    # No Career target: working independently with understanding, or complex work when stated advanced.
    return 7 if requirement.get('required_proficiency')=='advanced' else INDEPENDENT_LEVEL


def cv_level(records):
    """The level the CV review already gave this skill on the same scale, across its personal sources."""
    levels=[r['cv_level'] for r in records if isinstance(r.get('cv_level'),int) and r.get('attribution') not in _NOT_PERSONAL]
    return max(levels) if levels else None


def within_cv_level(level,records):
    # Assessment never rates a skill above the CV review's own pessimistic level.
    own=cv_level(records)
    return level if level is None or own is None else min(level,own)


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
    # Valid CV review levels already judged this evidence on the shared scale.
    reviewed=[r for r in records if r.get('reviewed') is True]
    own=cv_level(reviewed)
    if own is not None:proposed=own
    levels=[level for record in records if (level:=source_level(record)) is not None]
    if not levels: return None
    ceiling=max(levels)
    # Missing ownership is an explicit provisional baseline, never verified mastery.
    if ceiling<=5: return within_cv_level(ceiling,records)
    return within_cv_level(min(proposed,ceiling) if proposed is not None else ceiling,records)


# A finished review (answers or skipped topics) lets the model's own level stand where the
# evidence cannot set one; it stays a capped, low-confidence estimate, never verified mastery.
MODEL_ESTIMATE_CEILING=5


def reviewed_estimate(records, proposed):
    """The model's level for evidence the user has reviewed but whose personal part is unconfirmed."""
    if proposed is None: return None
    usable=[r for r in records if r.get('reviewed') and r.get('attribution') not in {'team','observed','denied'}]
    if not usable: return None
    return within_cv_level(max(1,min(int(proposed),MODEL_ESTIMATE_CEILING)),usable)


def unreviewed(records):
    """Cited CV evidence from a review the user has not finished."""
    return any(r.get('reviewed') is False for r in records)


def goal_score(have,need):
    # Only actual target attainment reaches 10; rounding must not turn 9.6 into 10.
    return min(10,math.floor(100*have/need)/10)
