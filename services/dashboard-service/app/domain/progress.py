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
    return None

def milestone_progress(plan,review,readiness):
    return []

def requirements(result,assessment_state,plan):
    return {'state':'unavailable','items':[],'groups':[], 'unlinked_task_ids':[], 'stale_link_task_ids':[]}

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
