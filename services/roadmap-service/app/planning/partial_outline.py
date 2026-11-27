"""Conservative, backend-owned recovery of an outline with invalid requirement IDs."""
from elo_shared.runtime import digest
from app.schemas.outlines import OutlineDraft


def recover_outline(draft,assessment,existing=None):
    """Drop invalid reference rows and their dependants, retaining an audit for review.

    The recovered draft must still pass normal validation before it can be shown. The model's
    deadline claim is never reversed: a recovery that would remove all beyond-deadline work fails instead.
    """
    data=draft.model_dump(mode='json')
    originally_placed={key for m in data['milestones']+data['beyond_deadline'] for key in m['gap_ids']}
    allowed={r['ref'] for section in ('job_skill_gaps','interview_prep_gaps') for r in assessment.get(section,[])}
    omitted=[]
    def record(kind,identifier,title,reason,reference=None):
        omitted.append({'kind':kind,'id':identifier,'title':title,'reason':reason,'requirement_ref':reference})
    bad={g['id'] for g in data['gaps'] if g.get('requirement_ref') and g['requirement_ref'] not in allowed}
    for gap in data['gaps']:
        if gap['id'] in bad:record('gap',gap['id'],gap['name'],'The generated requirement reference is not in this assessment.',gap['requirement_ref'])
    invalid_exclusions=[e for e in data['exclusions'] if e['requirement_ref'] not in allowed]
    for exclusion in invalid_exclusions:record('exclusion',exclusion['requirement_ref'],exclusion['requirement_ref'],'The generated exclusion references an unknown requirement.',exclusion['requirement_ref'])
    if not bad and not invalid_exclusions:return None,None
    if len({g['id'] for g in data['gaps']})!=len(data['gaps']):return None,None
    if len({m['key'] for m in data['milestones']})!=len(data['milestones']):return None,None
    data['gaps']=[g for g in data['gaps'] if g['id'] not in bad]
    data['exclusions']=[e for e in data['exclusions'] if e['requirement_ref'] in allowed]
    removed={m['key'] for m in data['milestones'] if m['gap_ids'] and set(m['gap_ids'])<=bad}
    while True:
        dependent={m['key'] for m in data['milestones'] if removed.intersection(m['prerequisite_keys'])}
        if dependent<=removed:break
        removed.update(dependent)
    if any(t.get('milestone_key') in removed for t in ((existing or {}).get('editable_tasks') or [])):return None,None
    if any(a.get('milestone_key') in removed for a in (existing or {}).get('assignments',[])):return None,None
    if any(m['key'] in removed and ((m.get('outcome') or {}).get('demonstrated') or any(c.get('reached_at') for c in m.get('checkpoints',[]))) for m in (existing or {}).get('milestones',[])):return None,None
    retained=[]
    for milestone in data['milestones']:
        if milestone['key'] in removed:
            record('milestone',milestone['key'],milestone['title'],'This milestone relies on an omitted gap or prerequisite.')
        else:
            milestone['gap_ids']=[key for key in milestone['gap_ids'] if key not in bad]
            retained.append(milestone)
    data['milestones']=retained
    weeks=[]
    for week in data['weeks']:
        if week['milestone_key'] in removed or week['gap_ids'] and set(week['gap_ids'])<=bad:record('week',week['week_start'],week['objective'],'Its milestone or learning gaps were omitted.')
        else:
            week['gap_ids']=[key for key in week['gap_ids'] if key not in bad]
            weeks.append(week)
    data['weeks']=weeks
    routines=[]
    for rule in data['routine_rules']:
        if rule['milestone_key'] in removed:record('routine',rule['id'],rule['activity'],'Its milestone or learning gaps were omitted.')
        else:routines.append(rule)
    data['routine_rules']=routines
    beyond=[]
    for item in data['beyond_deadline']:
        if item['gap_ids'] and set(item['gap_ids'])<=bad:
            record('beyond_deadline','beyond:'+digest(item)[:16],item['title'],'Its learning gaps were omitted.')
        else:
            item['gap_ids']=[key for key in item['gap_ids'] if key not in bad]
            beyond.append(item)
    data['beyond_deadline']=beyond
    if not data['milestones'] or not data['weeks']:return None,None
    if draft.beyond_deadline and not beyond:return None,None
    covered_ids={key for m in data['milestones']+data['beyond_deadline'] for key in m['gap_ids']}
    orphaned={g['id'] for g in data['gaps'] if g['id'] in originally_placed and g['id'] not in covered_ids}
    for gap in data['gaps']:
        if gap['id'] in orphaned:record('gap',gap['id'],gap['name'],'All its plan items relied on an omitted prerequisite.',gap.get('requirement_ref'))
    data['gaps']=[g for g in data['gaps'] if g['id'] not in orphaned]
    covered_refs={g['requirement_ref'] for g in data['gaps'] if g['id'] in covered_ids}
    excluded={e['requirement_ref'] for e in data['exclusions']}
    uncovered=[ref for ref in assessment.get('priorities',[]) if ref not in covered_refs|excluded]
    data['summary']='This is a partial roadmap. Review the retained milestones and weekly objectives; omitted items are listed separately.'
    data['deadline_outcome']['summary']='Only the retained milestones are planned. This partial roadmap does not establish complete coverage of your career goal.'
    data['deadline_outcome']['achievable_by_target']=[m['demonstrable_outcome'] for m in retained]
    return OutlineDraft.model_validate(data),{'omitted_items':omitted,'uncovered_requirements':uncovered}
