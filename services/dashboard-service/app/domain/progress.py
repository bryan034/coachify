"""Pure, evidence-bounded aggregation of owner-scoped source snapshots."""
from calendar import monthrange
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from elo_shared.milestone_review import removal_needs_review


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
        outcome=m.get('outcome') or {}
        if any(removal_needs_review(t,outcome,bool(members)) for t in all_members):review_reasons.append({'code':'removed_work','message':'Some milestone work was removed and needs review.'})
        if any(t.get('definition_review_required') for t in members):review_reasons.append({'code':'task_definition_changed','message':'A task completion definition needs review.'})
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
    baseline_id=plan.get('pace_baseline_id')
    cutoff=min(now,datetime.combine(end+timedelta(days=1),time.min,ZoneInfo(zone))-timedelta(microseconds=1)) if end else now
    result={'state':'unavailable','baseline_id':baseline_id,'baseline_created_at':None,'baseline_updated_at':None,
        'as_of':cutoff.astimezone(timezone.utc).isoformat(),'items':[],'unscheduled_task_ids':[], 'added_task_ids':[],
        'historical_added_scope_unknown':False, 'planned_minutes':None,
        'note':'Estimates use the saved schedule; they are not actual hours or a forecast.'}
    if not baseline_id or not baseline:return result
    if baseline.get('id')!=baseline_id:return result
    tasks_at_baseline=baseline_tasks(baseline)
    if tasks_at_baseline is None:return result
    accepted_at=parse_timestamp(baseline.get('updated_at'))
    if accepted_at is None:return result
    result.update(baseline_created_at=baseline.get('created_at'),baseline_updated_at=baseline.get('updated_at'))
    current={t['id']:t for t in plan.get('editable_tasks') or []}
    cohort=[t for t in tasks_at_baseline if not t.get('removed')]
    cohort_ids={t['id'] for t in cohort}
    added=[t['id'] for t in current.values() if not t.get('removed') and t['id'] not in cohort_ids]
    if cutoff==now:result['added_task_ids']=added
    else:result['historical_added_scope_unknown']=bool(added)
    result['unscheduled_task_ids']=[t['id'] for t in cohort if not t.get('schedule')]
    relevant=[t for t in cohort if slots_in_period(t,start,end)]
    result['planned_minutes']=sum(s['duration_minutes'] for t in relevant for s in slots_in_period(t,start,end))
    result['state']='available' if relevant else 'empty'
    today=cutoff.astimezone(ZoneInfo(zone)).date()
    for old in relevant:
        selected_slots=slots_in_period(old,start,end)
        dates=sorted({str(s['date']) for s in selected_slots})
        due=max(date.fromisoformat(day) for day in dates)
        cur=current.get(old['id']);reason=None;completed_at=None
        removed_at=parse_timestamp((cur or {}).get('removal',{}).get('at')) if (cur or {}).get('removal') else None
        history=(cur or {}).get('history',[])
        scope_edits=[event for event in history if event.get('event')=='edited' and
            set(event.get('fields',[])) & {'schedule','estimated_minutes','completion_outcome'}]
        unknown_history=any(parse_timestamp(event.get('at')) is None for event in scope_edits)
        later_edit=any(parse_timestamp(event.get('at')) and parse_timestamp(event['at'])>cutoff for event in scope_edits)
        if cutoff<accepted_at:
            classification='non_comparable';reason='The selected period ended before this baseline was accepted.'
        elif not cur:
            classification='non_comparable';reason='The baseline task is unavailable in the current roadmap.'
        elif cur.get('removed') and not removed_at:
            classification='non_comparable';reason='The removal time is unavailable.'
        elif cur.get('removed') and removed_at<=cutoff:
            classification='removed';reason='This task was removed after the baseline.'
        elif len(selected_slots)!=len(old.get('schedule',[])):
            classification='non_comparable';reason='Completion is recorded for the whole task, not individual scheduled segments.'
        elif unknown_history or later_edit:
            classification='non_comparable';reason='The task definition or schedule at this period cutoff cannot be established safely.'
        elif any(cur.get(k)!=old.get(k) for k in ('completion_outcome','estimated_minutes','schedule')):
            classification='changed';reason='The task definition, estimate or schedule changed after the baseline.'
        elif cur.get('definition_review_required'):
            classification='non_comparable';reason='The completion definition needs review.'
        else:
            events=[{**event,'to':'not_started' if event.get('to')=='scheduled' else event.get('to'),
                'from':'not_started' if event.get('from')=='scheduled' else event.get('from')} for event in cur.get('history',[])
                if event.get('to') in ('scheduled','not_started','in_progress','completed')]
            parsed=[(parse_timestamp(event.get('at')),event) for event in events]
            if any(moment is None for moment,event in parsed):
                classification='non_comparable';reason='A task status change has no valid time.'
            else:
                parsed.sort(key=lambda pair:pair[0]);status=old.get('status');last=None
                for moment,event in parsed:
                    if moment<=cutoff:
                        if event['to']!='completed':last=None
                        elif event.get('from')!='completed':last=event
                    if accepted_at<moment<=cutoff:status=event['to']
                if cutoff==now and status!=cur.get('status'):
                    classification='non_comparable';reason='The task status cannot be reconstructed from its history.'
                elif status=='completed':
                    last=last or {};completed_at=last.get('at');moment=parse_timestamp(completed_at)
                    if (not moment or last.get('completion_definition')!=old.get('completion_outcome') or
                        last.get('estimated_minutes_at_completion')!=old.get('estimated_minutes')):
                        classification='non_comparable';reason='Completion time, definition or estimate provenance is missing or changed.'
                    else:
                        completed_day=moment.astimezone(ZoneInfo(zone)).date()
                        classification='completed_early' if completed_day<due else 'completed_on_time' if completed_day==due else 'completed_late'
                elif status in ('not_started','in_progress'):classification='overdue' if due<today else 'upcoming'
                else:classification='non_comparable';reason='The task status at the baseline is unavailable.'
        result['items'].append({'task_id':old['id'],'planned_date':due.isoformat(),'planned_dates':dates,'classification':classification,
            'completed_at':completed_at,'reason':reason})
    return result
