"""Conservative understanding ceilings shared by both Assessment scoring paths."""
import math
from elo_shared.competence_scale import MODERATE_LEVEL

RUBRIC_VERSION='evidence-role-v5'
_NOT_PERSONAL={'team','observed','denied'}


def role_level(requirement):
    target=requirement.get('competence_target') or {}
    if isinstance(target.get('level'),int) and 1<=target['level']<=10:
        return target['level']
    return 7 if requirement.get('required_proficiency')=='advanced' else MODERATE_LEVEL


def cv_level(records):
    """The level the CV review already gave this skill on the same scale, across its personal sources."""
    levels=[r['cv_level'] for r in records if isinstance(r.get('cv_level'),int) and r.get('attribution') not in _NOT_PERSONAL]
    return max(levels) if levels else None


def within_cv_level(level,records):
    own=cv_level(records)
    return level if level is None or own is None else min(level,own)


def source_level(record):
    """Return an evidence ceiling, with 3 explicitly provisional for ambiguous projects."""
    if record.get('attribution') in {'team','observed','denied'} or record.get('unscoped_item'): return None
    project=record.get('source_kind') in {'project','experience'}
    if record.get('support_uncertain') or record.get('attribution')!='personal':
        return 3 if project else None
    facts=record.get('review_facts',[])
    if any(f['status']=='conflicting' and f['field'] in {'personal_contribution','skill_use','outcome'} for f in facts):
        return 3 if project else None
    known={f['field'] for f in facts if f['status']=='supported' and f['field'] not in {'self_rating','replication_confidence'}}
    if not known: return 3
    if not {'complexity','problem_solving'}<=known: return 5
    if not {'frequency','recency'}<=known or (record.get('experience_months') or 0)<24: return 7
    return 9


def evidence_level(records, proposed=None):
    reviewed=[r for r in records if r.get('reviewed') is True]
    own=cv_level(reviewed)
    if own is not None:proposed=own
    levels=[level for record in records if (level:=source_level(record)) is not None]
    if not levels: return None
    ceiling=max(levels)
    if ceiling<=5: return within_cv_level(ceiling,records)
    return within_cv_level(min(proposed,ceiling) if proposed is not None else ceiling,records)


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
    return min(10,math.floor(100*have/need)/10)
