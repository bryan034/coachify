"""The weekly check-in's window, recap and workload arithmetic.

A week's check-in opens on the configured local day and time. It stays open until completed or until
next week's first scheduled task starts; with no task next week it expires at the start of that week.
All comparisons use wall-clock local time, so a clock change never opens or closes it twice.
"""
from datetime import date, timedelta
from app.planning.capacity import to_minute, week_of
from app.planning.metrics import counts_toward_roadmap, week_target
from app.planning.schedule import config_of, day_of, placed, plan_capacity, task_span

CLOSED=('completed','expired')
WORKLOAD_STEP=.25

def opening(plan,week):
    config=config_of(plan)
    return week+timedelta(days=config.checkin_day),to_minute(config.checkin_time)
def expiry(plan,week):
    following=week+timedelta(days=7);last=following+timedelta(days=6)
    starts=[(day_of(t),task_span(t)[0]) for t in plan['assignments'] if placed(t) and following<=day_of(t)<=last]
    return min(starts) if starts else (following,0)
def _accepted_key(plan,zone):
    from datetime import datetime
    stamp=plan.get('accepted_at')
    if not stamp:return None
    local=datetime.fromisoformat(stamp).astimezone(zone)
    return local.date(),local.hour*60+local.minute
def candidate_weeks(plan,capacity):
    """Weeks whose check-in opened after the roadmap was accepted, through the target week, excluding paused weeks."""
    accepted=_accepted_key(plan,capacity.zone);weeks=[]
    first=week_of(date.fromisoformat(str(plan['config']['start_date'])));week=first
    last=min(week_of(capacity.today),week_of(capacity.target)) if capacity.target else week_of(capacity.today)
    while week<=last:
        row=plan.get('week_states',{}).get(week.isoformat(),{})
        opened=opening(plan,week)
        if not row.get('paused') and (accepted is None or opened>=accepted) and opened<=(capacity.today,capacity.now_minute):weeks.append(week)
        week+=timedelta(days=7)
    return weeks
def expire_checkins(plan,now):
    """Close check-ins whose window has passed, keeping any saved answers. Returns how many changed."""
    capacity=plan_capacity(plan,now);changed=0;moment=(capacity.today,capacity.now_minute)
    for week in candidate_weeks(plan,capacity):
        key=week.isoformat();record=plan.setdefault('checkins',{}).get(key)
        if record and record.get('status') in CLOSED:continue
        if moment>=expiry(plan,week):
            plan['checkins'][key]={**(record or {}),'status':'expired','expired_at':now.isoformat()}
            changed+=1
    return changed
def open_week(plan,now):
    capacity=plan_capacity(plan,now);moment=(capacity.today,capacity.now_minute)
    for week in reversed(candidate_weeks(plan,capacity)):
        record=plan.get('checkins',{}).get(week.isoformat())
        if record and record.get('status') in CLOSED:continue
        if moment<expiry(plan,week):return week
    return None
def recap(plan,week,capacity):
    moment=(capacity.today,capacity.now_minute);last=week+timedelta(days=6)
    members=[t for t in plan['assignments'] if t.get('date') and week<=day_of(t)<=last and t['status'] in ('scheduled','completed') and t.get('count_hours',True)]
    done=sum(t['duration_minutes'] for t in members if t['status']=='completed')
    remaining=sum(t['duration_minutes'] for t in members if t['status']=='scheduled' and (day_of(t),task_span(t)[0])>=moment)
    due=[t for t in members if t.get('start_time') and (day_of(t),task_span(t)[0])<=moment and counts_toward_roadmap(t)]
    due_minutes=sum(t['duration_minutes'] for t in due)
    completed_due=sum(t['duration_minutes'] for t in due if t['status']=='completed')
    since=week.isoformat()
    moved=[e['message'] for e in plan.get('events',[]) if e['type'] in ('auto_move','auto_backlog','manual_move') and not e['undone'] and e['at'][:10]>=since]
    skipped=[t['task'] for t in plan['assignments'] if t['status']=='skipped' and t['week_start']==since]
    return {'planned_minutes':sum(t['duration_minutes'] for t in members),'completed_minutes':done,'remaining_minutes':remaining,'due_minutes':due_minutes,'completed_due_minutes':completed_due,
        'moved':moved[-20:],'skipped':skipped[:20],'suggest_less':due_minutes>0 and completed_due*2<due_minutes}
def checkin_view(plan,now):
    week=open_week(plan,now)
    if not week:return None
    capacity=plan_capacity(plan,now);record=plan.get('checkins',{}).get(week.isoformat()) or {}
    following=week+timedelta(days=7);opened=opening(plan,week);closes=expiry(plan,week)
    label=lambda key:f'{key[0].isoformat()}T{key[1]//60:02d}:{key[1]%60:02d}'
    return {'week_start':week.isoformat(),'status':record.get('status','open'),'opens_at':label(opened),'expires_at':label(closes),'recap':recap(plan,week,capacity),
        'answers':record.get('answers'),'next_week':following.isoformat(),'next_week_target_minutes':week_target(plan,following,capacity)}
def next_week_workload(plan,week,answer,capacity):
    """The per-week target a choice implies: about 25% more or less, within eligible capacity and the weekly maximum."""
    following=week+timedelta(days=7)
    base=week_target(plan,following,capacity);eligible,planned,_=capacity.week_minutes(following)
    if answer=='same':wanted=base
    elif answer=='more':wanted=int(round(base*(1+WORKLOAD_STEP)/5)*5)
    else:wanted=int(round(base*(1-WORKLOAD_STEP)/5)*5)
    target=min(wanted,eligible)
    return {'week':following,'base':base,'target':target,'uses_buffer':target>planned,'exceeds_capacity':wanted>eligible}
