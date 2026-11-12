"""Read-time status of the saved evaluation; never persist a freshness flag."""
from app.competence import RUBRIC_VERSION


def evaluation_status(row, snapshot=None, unavailable=False):
    result=row.get('result')
    profile=(result or {}).get('skill_profile')
    operation=row.get('pending') or row.get('last_operation') or {}
    processing='evaluating' if row.get('pending') else 'failed' if operation.get('status')=='failed' else 'idle'
    reasons=[]
    if unavailable:
        freshness='unavailable'
    elif not result:
        freshness='missing'
    else:
        before=result.get('inputs') or {};now=(snapshot or {}).get('inputs') or {}
        if not (snapshot or {}).get('ready'):
            reasons.append('inputs_not_ready')
        for reason,fields in (
            ('cv_changed',('cv_id','cv_version','extraction_version','effective_version','cv_selection_version')),
            ('evidence_changed',('evidence_hash','declarations_version','profile_version','as_of_date')),
            ('goal_changed',('goal_id','goal_version','goal_selection_version')),
            ('research_changed',('research_id','research_version','research_coverage')),
            ('registry_changed',('registry_version',))):
            if any(before.get(field)!=now.get(field) for field in fields):reasons.append(reason)
        if not profile or profile.get('rubric_version')!=RUBRIC_VERSION or profile.get('status')=='failed':
            reasons.append('evaluation_update_required')
        if result.get('input_hash')!=(snapshot or {}).get('input_hash') and not reasons:reasons.append('evaluation_update_required')
        freshness='outdated' if reasons else 'current'
    complete=bool(result and result.get('analysis_status')=='succeeded' and profile and profile.get('status') in ('evaluated','empty'))
    return {'freshness':freshness,'processing':processing,'completeness':('complete' if complete else 'partial') if result else None,
        'evaluated_at':(result or {}).get('created_at'),'reasons':reasons}
