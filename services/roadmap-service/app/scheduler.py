"""Minute-conserving daily workload allocator. No model arithmetic or clock slots."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from fractions import Fraction
from app.schemas import Preferences

DAYS=('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')

def schedule(tasks,preferences):
    prefs=Preferences.model_validate(preferences)
    missing=[]
    if not prefs.start_date:missing.append('Choose when you would like to start.')
    if not prefs.target_date and not prefs.horizon_weeks:missing.append('Choose a preparation target or an ongoing planning horizon.')
    if prefs.weekly_minutes is None:missing.append('Choose a weekly time budget.')
    if not prefs.days:missing.append('Choose the days you would like to work.')
    if missing:return {'status':'needs_preferences','issues':missing,'allocations':[],'remainders':{t['id']:t['estimated_minutes'] for t in tasks if t.get('status')!='completed' and not t.get('removed')},'daily_capacity':{},'milestones':[]}
    start=max(prefs.start_date,datetime.now(ZoneInfo(prefs.time_zone)).date()); end=prefs.target_date or prefs.start_date+timedelta(weeks=prefs.horizon_weeks)
    budgets={d.day:d.minutes for d in prefs.days}; caps={}; week_used={}
    for offset in range((end-start).days):
        day=start+timedelta(days=offset); cap=budgets.get(day.weekday(),0)
        # Profile's reduced weekly rate replaces the baseline rate. Preserve chosen days
        # by scaling their budgets; floor only capacity, never effort.
        for reduced in prefs.reduced_periods:
            period=reduced.model_dump(mode='json')
            if period['start_date']<=day.isoformat()<=period['end_date']:
                baseline=prefs.weekly_minutes or 0
                rate=Fraction(str(period['weekly_hours']))*60
                cap=int(Fraction(cap)*min(Fraction(1),rate/baseline)) if baseline else 0
        caps[day.isoformat()]=cap
    active=[t for t in tasks if not t.get('removed')]; lookup={t['id']:t for t in active}
    if len(lookup)!=len(active):raise ValueError('Task identities must be unique.')
    pending=[t for t in active if t.get('status')!='completed']; ordered=[]; issues=[]; blocked=set(); visiting=set(); visited=set()
    def visit(key):
        if key in visiting:
            blocked.update(visiting);issues.append('A prerequisite cycle needs review.');return
        if key in visited:return
        task=lookup[key]; visiting.add(key)
        for predecessor in task.get('prerequisites',[]):
            if predecessor not in lookup:blocked.add(key);issues.append('A task references removed or unavailable prerequisite work.')
            else:visit(predecessor)
        visiting.remove(key);visited.add(key);ordered.append(task)
    for task in pending:visit(task['id'])
    allocations=[]; remaining={}; finish={t['id']:None for t in active if t.get('status')=='completed'};used={d:0 for d in caps}
    for task in ordered:
        if task.get('status')=='completed':continue
        key=task['id']; left=task['estimated_minutes']; prereqs=task.get('prerequisites',[])
        if key in blocked or any(p not in finish for p in prereqs):
            remaining[key]=left;issues.append(task['title']+': prerequisite work is unfinished or unscheduled.');continue
        not_before=max([finish[p] for p in prereqs if finish[p] is not None],default=start.isoformat())
        for day,cap in caps.items():
            if day<not_before:continue
            week=(date.fromisoformat(day)-timedelta(days=date.fromisoformat(day).weekday())).isoformat()
            available=min(cap-used[day],prefs.weekly_minutes-week_used.get(week,0))
            if available<=0:continue
            if not task.get('splittable',True):
                if left>available or left>prefs.max_session_minutes:continue
                chunks=[left]
            else:
                portion=min(left,available);chunks=[]
                while portion:
                    part=min(portion,prefs.max_session_minutes);chunks.append(part);portion-=part
            for part in chunks:
                if len(allocations)>=10000:
                    issues.append('The 10,000-session allocation limit was reached; remaining work is unscheduled.')
                    break
                allocations.append({'task_id':key,'date':day,'minutes':part,'order':len(allocations)})
                used[day]+=part;week_used[week]=week_used.get(week,0)+part;left-=part
            if left==0:finish[key]=day;break
        remaining[key]=left
        if left:issues.append(task['title']+': '+str(left)+' estimated minutes remain unscheduled.')
    milestones=[]
    for name in dict.fromkeys(t.get('milestone') for t in active if t.get('milestone')):
        members=[t for t in active if t.get('milestone')==name]
        complete=bool(members) and all(t.get('status')=='completed' and not t.get('definition_review_required') for t in members)
        dates=[finish.get(t['id']) for t in members]
        scheduled=all(t['id'] in finish for t in members)
        review=any(t.get('definition_review_required') for t in members)
        milestones.append({'name':name,'task_ids':[t['id'] for t in members],'status':'review_needed' if review else 'completed' if complete else 'in_progress',
            'target_date':max([d for d in dates if d],default=None) if scheduled and not review else None})
    return {'status':'no_work' if not pending else 'partial' if any(remaining.values()) else 'feasible',
        'issues':list(dict.fromkeys(issues)),'allocations':allocations,'remainders':remaining,'daily_capacity':caps,'milestones':milestones,
        'total_estimated_minutes':sum(t['estimated_minutes'] for t in active),
        'remaining_minutes':sum(t['estimated_minutes'] for t in pending),
        'available_minutes':sum(caps.values()),'allocated_minutes':sum(a['minutes'] for a in allocations),'start_date':start.isoformat(),'cutoff_date':end.isoformat()}


def review_saved(plan):
    """Recheck edits/status against the saved allocations, without moving any work."""
    import copy
    result=copy.deepcopy(plan['schedule']);tasks={t['id']:t for t in plan['tasks'] if not t.get('removed')}
    allocated={}; used={}; issues=[]
    for allocation in result.get('allocations',[]):
        task=tasks.get(allocation['task_id'])
        if not task or task['status']=='completed':continue
        allocated[task['id']]=allocated.get(task['id'],0)+allocation['minutes']
        used[allocation['date']]=used.get(allocation['date'],0)+allocation['minutes']
    remainders={}
    for task in tasks.values():
        if task['status']=='completed':continue
        difference=task['estimated_minutes']-allocated.get(task['id'],0);remainders[task['id']]=max(0,difference)
        if difference:issues.append(task['title']+(': missing allocations.' if difference>0 else ': saved allocations exceed the revised estimate.'))
        if any(p not in tasks or tasks[p]['status']!='completed' for p in task['prerequisites']):
            issues.append(task['title']+': prerequisite work is not yet completed.')
        if task.get('definition_review_required'):issues.append(task['title']+': changed definition needs review.')
    for day,minutes in used.items():
        if minutes>result.get('daily_capacity',{}).get(day,0):issues.append(day+': workload exceeds the saved daily budget.')
    result.update(remainders=remainders,issues=list(dict.fromkeys(issues)),remaining_minutes=sum(t['estimated_minutes'] for t in tasks.values() if t['status']!='completed'))
    result['status']='review_needed' if issues else 'feasible' if result['remaining_minutes'] else 'no_work'
    milestones=[]
    old_names={m['name'] for m in result.get('milestones',[])}
    for name in old_names|{t['milestone'] for t in tasks.values() if t.get('milestone')}:
        members=[t for t in tasks.values() if t.get('milestone')==name]
        previous=next((m for m in result.get('milestones',[]) if m['name']==name),{})
        changed=set(previous.get('task_ids',[]))!={t['id'] for t in members}
        review=changed or any(t.get('definition_review_required') for t in members)
        complete=bool(members) and all(t['status']=='completed' for t in members) and not review
        milestones.append({'name':name,'task_ids':[t['id'] for t in members],'target_date':previous.get('target_date') if not review else None,
            'status':'review_needed' if review else 'completed' if complete else 'in_progress'})
    result['milestones']=milestones
    return result


def reschedule_plan(plan):
    """Schedule remaining work while retaining the historical allocations of completed tasks."""
    completed={t['id'] for t in plan['tasks'] if t.get('status')=='completed' and not t.get('removed')}
    history=[a for a in plan.get('schedule',{}).get('allocations',[]) if a['task_id'] in completed]
    result=schedule(plan['tasks'],plan['preferences'])
    result['allocations']=[*history,*result['allocations']]
    return result
