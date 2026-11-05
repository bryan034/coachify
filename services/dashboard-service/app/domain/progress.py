"""Pure, evidence-bounded aggregation of owner-scoped source snapshots."""
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def period_bounds(kind, focus, zone, now):
    local=now.astimezone(ZoneInfo(zone))
    focus=focus or local.date()
    if kind=='daily':start=end=focus
    elif kind=='weekly':
        start=focus-timedelta(days=focus.weekday());end=start+timedelta(days=6)
    elif kind=='monthly':
        start=focus.replace(day=1);end=focus.replace(day=monthrange(focus.year,focus.month)[1])
    else:start=end=None
    return {'kind':kind,'focus_date':focus.isoformat(),'start_date':start.isoformat() if start else None,
        'end_date':end.isoformat() if end else None,'time_zone':zone},start,end

def slots_in_period(task,start,end):
    return [s for s in task.get('schedule',[]) if start is None or start<=date.fromisoformat(str(s['date']))<=end]

def counts(tasks):
    total=len(tasks);completed=sum(t.get('status')=='completed' and not t.get('definition_review_required') for t in tasks)
    # An invalidated completion remains visible as completed, but does not count
    # towards progress until its definition is confirmed again.
    in_progress=sum(t.get('status')=='in_progress' for t in tasks)
    not_started=sum(t.get('status')=='not_started' for t in tasks)
    review=sum(t.get('status')=='completed' and bool(t.get('definition_review_required')) for t in tasks)
    return {'total':total,'completed':completed,'in_progress':in_progress,'not_started':not_started,'completion_review':review,
        'completion_ratio':completed/total if total else None,
        'remaining_estimated_minutes':sum(t['estimated_minutes'] for t in tasks if t.get('status')!='completed' or t.get('definition_review_required'))}

def task_progress(plan,start,end,readiness):
    tasks=plan.get('editable_tasks') or []
    active=[t for t in tasks if not t.get('removed')]
    selected=[t for t in active if start is None or slots_in_period(t,start,end)]
    remainder={t['id']:max(0,t['estimated_minutes']-sum(s['duration_minutes'] for s in t.get('schedule',[]))) for t in active}
    selected_ids={t['id'] for t in selected}
    shown=[t for t in active if t['id'] in selected_ids or remainder[t['id']]>0]
    return {'overall':counts(active),'selected':counts(selected),'selected_task_ids':[t['id'] for t in selected],
        'planned_minutes':sum(s['duration_minutes'] for t in selected for s in slots_in_period(t,start,end)),
        'unscheduled_minutes':sum(remainder.values()),'unscheduled_task_ids':[t['id'] for t in active if remainder[t['id']]>0],
        'remaining_unscheduled_minutes':sum(remainder[t['id']] for t in active if t['status']!='completed' or t.get('definition_review_required')),
        'removed_task_ids':[t['id'] for t in tasks if t.get('removed')],
        'tasks':[{'id':t['id'],'title':t['title'],'status':t['status'],'estimated_minutes':t['estimated_minutes'],
            'schedule':slots_in_period(t,start,end),'unscheduled_minutes':remainder[t['id']],
            'definition_review_required':bool(t.get('definition_review_required')),
            'readiness':readiness.get(t['id'])} for t in shown]}

def milestone_progress(plan,review,readiness):
    result=[]; tasks=plan.get('editable_tasks') or []
    for m in plan.get('milestones',[]):
        all_members=[t for t in tasks if t.get('milestone_key')==m['key']]
        members=[t for t in all_members if not t.get('removed')]
        blocked=[t for t in members if not readiness.get(t['id'],{}).get('actionable',False) and t.get('status')!='completed']
        reasons=[]
        for task in blocked:
            for reason in readiness.get(task['id'],{}).get('reasons',[]):reasons.append({'task_id':task['id'],**reason})
        progress=dict((review or {}).get('milestones',{}).get(m['id'],{}))
        if 'completed_minutes' in progress:
            progress['completed_scheduled_minutes_estimate']=progress.pop('completed_minutes')
        review_reasons=[]
        if not members:review_reasons.append({'code':'no_active_tasks','message':'This milestone has no active tasks.'})
        if any(t.get('removed') for t in all_members):review_reasons.append({'code':'removed_work','message':'Some milestone work was removed and needs review.'})
        if any(t.get('definition_review_required') for t in all_members):review_reasons.append({'code':'task_definition_changed','message':'A task completion definition needs review.'})
        outcome=m.get('outcome') or {}
        if outcome.get('membership_review_required'):review_reasons.append({'code':'membership_changed','message':'The milestone tasks changed and its outcome needs review.'})
        elif outcome.get('definition_review_required'):review_reasons.append({'code':'outcome_definition_changed','message':'The milestone outcome changed and needs review.'})
        if not (m.get('outcome') or {}).get('demonstrated'):review_reasons.append({'code':'outcome_unconfirmed','message':'The milestone outcome has not been confirmed; detailed tasks may not cover all remaining work.'})
        if progress.get('review_needed') and not review_reasons:review_reasons.append({'code':'roadmap_review_required','message':'Roadmap reports that this milestone needs review.'})
        result.append({'id':m['id'],'title':m['title'],'outcome':m.get('outcome') or {},
            'progress':progress,'review_reasons':review_reasons,
            'blocked_task_ids':[t['id'] for t in blocked], 'blocked_reasons':reasons})
    return result

def requirements(result,assessment_state,plan):
    items=[];groups=[];tasks=[t for t in (plan or {}).get('editable_tasks',[]) if not t.get('removed')]
    if result:
        snapshot_id=result.get('id'); snapshot_hash=result.get('input_hash')
        for section in ('job_skill_gaps','interview_prep_gaps','constraints'):
            for outcome in result.get(section,[]):
                ref=outcome['ref']
                linked=[t['id'] for t in tasks if ref in t.get('requirement_refs',[]) and
                    t.get('requirement_source_id')==snapshot_id and t.get('requirement_source_hash')==snapshot_hash]
                items.append({'ref':ref,'name':outcome.get('name'),'kind':outcome.get('kind'),
                    'match_status':outcome.get('match_status'),'components':outcome.get('components',[]),'linked_task_ids':linked})
        for group in result.get('groups',[]):
            group=dict(group)
            group['linked_task_ids']=[t['id'] for t in tasks if group['id'] in t.get('requirement_refs',[]) and
                t.get('requirement_source_id')==snapshot_id and t.get('requirement_source_hash')==snapshot_hash]
            groups.append(group)
    known={i['ref'] for i in items}|{g['id'] for g in groups}
    stale=[t['id'] for t in tasks if t.get('requirement_refs') and (not result or
        t.get('requirement_source_id')!=result.get('id') or t.get('requirement_source_hash')!=result.get('input_hash') or
        any(ref not in known for ref in t['requirement_refs']))]
    return {'state':assessment_state,'items':items,'groups':groups,
        'unlinked_task_ids':[t['id'] for t in tasks if not t.get('requirement_refs')], 'stale_link_task_ids':stale}

def parse_timestamp(value):
    if not value:return None
    try:
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        return result if result.tzinfo else None
    except (TypeError,ValueError):return None

def baseline_tasks(baseline):
    """Project timed legacy assignments without changing the immutable source."""
    if baseline.get('editable_tasks') is not None:return baseline['editable_tasks']
    if baseline.get('schema_version')!='roadmap-v2' or not isinstance(baseline.get('assignments'),list):return None
    return [{'id':a['id'],'status':'completed' if a['status']=='completed' else 'not_started',
        'estimated_minutes':a['duration_minutes'],'completion_outcome':a['completion_criterion'],
        'schedule':[{'date':str(a['date']),'start_time':a['start_time'],'duration_minutes':a['duration_minutes']}],
        'removed':False,'history':a.get('history',[])} for a in baseline['assignments']]

def pace(plan,baseline,start,end,zone,now):
    return {'state':'unavailable','as_of':now.astimezone(timezone.utc).isoformat(), 'note':'No comparable saved baseline is available.'}
