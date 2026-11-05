"""Progress, pace and finish-date projections. The backend owns these numbers; the model never asserts them."""
from datetime import date, datetime, timedelta
from math import ceil
from app.planning.capacity import split_buffer, to_minute, total, week_of
from app.planning.schedule import Board, config_of, day_of, future_weeks, paused_weeks, placed, plan_capacity, suggest_slot, task_span, UNFINISHED

SIMULATED_DAYS=366*3
RECENT_WEEKS=4
MINIMUM_RECENT_WEEKS=2
ASSUMPTION='Assumes your recurring study blocks, weekly maximum, blackouts and buffer continue unchanged after your target date.'

def counts_toward_roadmap(task):
    """Generated tasks always count. Custom tasks count only when linked to a milestone and included in hours."""
    if task['origin']=='generated':return True
    return bool(task.get('milestone_key')) and task.get('count_hours',True)
def milestone_totals(plan):
    tasks=plan['assignments'];rows={}
    for milestone in plan['milestones']:
        members=[t for t in tasks if t.get('milestone_key')==milestone['key'] and t['origin']=='generated']
        done=sum(t['duration_minutes'] for t in members if t['status']=='completed')
        open_minutes=sum(t['duration_minutes'] for t in members if t['status'] in UNFINISHED)
        removed=sum(t['duration_minutes'] for t in members if t['status']=='removed' and t.get('removed_reason')=='milestone_completed')
        if milestone.get('completion'):planned=done+open_minutes
        else:planned=max(milestone['estimated_minutes']-removed,done+open_minutes)
        rows[milestone['key']]={'planned':planned,'done':done,'open':open_minutes,'undetailed':max(0,planned-done-open_minutes)}
    return rows
def progress(plan):
    totals=milestone_totals(plan);tasks=plan['assignments']
    linked=[t for t in tasks if t['origin']=='custom' and counts_toward_roadmap(t)]
    linked_done=sum(t['duration_minutes'] for t in linked if t['status']=='completed')
    linked_open=sum(t['duration_minutes'] for t in linked if t['status'] in UNFINISHED)
    done=sum(r['done'] for r in totals.values())+linked_done
    planned=sum(r['planned'] for r in totals.values())+linked_done+linked_open
    generated=[t for t in tasks if t['origin']=='generated' and t['status']!='removed']
    custom=[t for t in tasks if t['origin']=='custom' and t['status']=='scheduled']
    return {'label':'Roadmap progress','roadmap_minutes':{'completed':done,'planned':planned},
        'generated_tasks':{'completed':sum(t['status']=='completed' for t in generated),'planned':len(generated)},
        'milestones':{'completed':sum(bool(m.get('completion')) for m in plan['milestones']),'planned':len(plan['milestones'])},
        'custom_scheduled_minutes':sum(t['duration_minutes'] for t in custom if t.get('count_hours',True)),
        'custom_excluded_minutes':sum(t['duration_minutes'] for t in custom if not t.get('count_hours',True)),
        'custom_linked_completed_minutes':linked_done,'remaining_minutes':max(0,planned-done)}
def week_target(plan,week,capacity):
    """The workload target: a per-week override, or the outline's target, never above planned capacity."""
    eligible,planned,_=capacity.week_minutes(week)
    row=plan.get('week_states',{}).get(week.isoformat(),{})
    if row.get('paused'):return 0
    if row.get('workload_minutes') is not None:return min(row['workload_minutes'],eligible)
    outline=next((o for o in plan.get('outline',[]) if o['week_start']==week.isoformat()),None)
    return min(outline['target_minutes'],planned) if outline else planned
def included_scheduled(plan,week):
    return sum(t['duration_minutes'] for t in plan['assignments'] if t['status'] in ('scheduled','completed') and t.get('date') and t.get('count_hours',True) and week_of(day_of(t))==week)

class Forecast:
    """Walks future days with one plan's recurring windows, beyond the target date if needed."""
    def __init__(self,plan,now):
        self.plan=plan;self.capacity=plan_capacity(plan,now);self.config=self.capacity.config;self.day_cache={}
        self.custom={}
        for task in plan['assignments']:
            if task['origin']=='custom' and task['status']=='scheduled' and task.get('date') and task.get('count_hours',True):
                week=week_of(day_of(task));self.custom[week]=self.custom.get(week,0)+task['duration_minutes']
    def _day(self,day):
        if day not in self.day_cache:
            if day in self.capacity.days:windows=self.capacity.days[day]
            else:windows=self.capacity._windows(day)
            self.day_cache[day]=total(windows['preferred'])+(total(windows['backup']) if self.config.use_backup else 0)
        return self.day_cache[day]
    def _budget(self,week,first,weekly_limit):
        days=[week+timedelta(days=i) for i in range(7)]
        minutes=sum(self._day(day) for day in days if day>=first)
        eligible=min(self.capacity.week_left(week),minutes)
        if weekly_limit is not None:budget=min(weekly_limit,eligible)
        else:
            row=self.plan.get('week_states',{}).get(week.isoformat(),{})
            budget=min(row['workload_minutes'],eligible) if row.get('workload_minutes') is not None else split_buffer(eligible,self.config.buffer_percent)[0]
        return max(0,budget-self.custom.get(week,0))
    def finish(self,minutes,weekly_limit=None):
        """The local date on which this many minutes would be finished, or None if it never would."""
        first=self.capacity.start
        if minutes<=0:return self.capacity.today
        day=first;left={}
        for _ in range(SIMULATED_DAYS):
            week=week_of(day)
            if week not in left:left[week]=self._budget(week,first,weekly_limit)
            used=min(left[week],self._day(day))
            left[week]-=used;minutes-=used
            if minutes<=0:return day
            day+=timedelta(days=1)
        return None
def remaining_active(plan):
    return progress(plan)['remaining_minutes']
def deferred_minutes(plan):
    return sum(item['estimated_minutes'] for item in plan.get('deferred_scope',[]))
def projection(plan,now):
    forecast=Forecast(plan,now);active=remaining_active(plan);deferred=deferred_minutes(plan)
    target=str(plan['config']['target_date'])
    scheduled=forecast.finish(active);overall=forecast.finish(active+deferred)
    return {'target_date':target,'scheduled_finish':scheduled.isoformat() if scheduled else None,'projected_finish':overall.isoformat() if overall else None,
        'remaining_active_minutes':active,'deferred_minutes':deferred,'fits_target':bool(scheduled and scheduled.isoformat()<=target),'assumption':ASSUMPTION}

def baseline_key(task):
    if not task.get('baseline'):return None
    text=task['baseline'];return date.fromisoformat(text[:10]),to_minute(text[11:16])
def expected_minutes(plan,capacity):
    """Estimated work due by now: unmoved baselines, plus outline targets for past weeks that never got detail."""
    paused=set(paused_weeks(plan));today=capacity.today;minute=capacity.now_minute;expected=0;detailed=set()
    for task in plan['assignments']:
        if not counts_toward_roadmap(task) or task['status']=='removed' or not task.get('baseline'):continue
        day,begin=baseline_key(task)
        detailed.add(day-timedelta(days=day.weekday()))
        if week_of(day).isoformat() in paused:continue
        if (day,begin+task['duration_minutes'])<=(today,minute) or day<today:expected+=task['duration_minutes']
    start=week_of(date.fromisoformat(str(plan['config']['start_date'])))
    for row in plan.get('outline',[]):
        week=date.fromisoformat(row['week_start'])
        if week<start or week+timedelta(days=6)>=today or week in detailed or row['week_start'] in paused:continue
        expected+=row['target_minutes']
    return expected
def completed_by_week(plan,zone):
    """Roadmap minutes by the local calendar week in which they were completed."""
    weeks={}
    for task in plan['assignments']:
        if task['status']=='completed' and task.get('completed_at') and counts_toward_roadmap(task):
            local=datetime.fromisoformat(task['completed_at']).astimezone(zone).date()
            week=week_of(local);weeks[week]=weeks.get(week,0)+task['duration_minutes']
    return weeks
def recent_weeks(plan,capacity):
    """The latest four finished calendar weeks of this plan, including zero-completion weeks.

    A paused week was a decision rather than slow progress, so it doesn't count.
    """
    start=week_of(date.fromisoformat(str(plan['config']['start_date'])))
    paused=set(paused_weeks(plan));week=week_of(capacity.today)-timedelta(days=7);rows=[]
    while week>=start and len(rows)<RECENT_WEEKS:
        if week.isoformat() not in paused:rows.append(week)
        week-=timedelta(days=7)
    return rows
def pace(plan,now):
    capacity=plan_capacity(plan,now);view=progress(plan)
    done=view['roadmap_minutes']['completed'];expected=expected_minutes(plan,capacity)
    status='insufficient_data' if not expected else 'on_track' if done>=expected else 'behind'
    rows=recent_weeks(plan,capacity);recent={'status':'insufficient_data','weeks_used':len(rows),'weekly_minutes':None,'finish_date':None,'weeks_late':None}
    if len(rows)>=MINIMUM_RECENT_WEEKS:
        finished=completed_by_week(plan,capacity.zone)
        weekly=sum(finished.get(week,0) for week in rows)//len(rows)
        recent['weekly_minutes']=weekly
        if not weekly and sum(finished.get(week,0) for week in rows)==0:recent['status']='no_estimate'
        else:
            recent['status']='available'
            finish=Forecast(plan,now).finish(view['remaining_minutes'],weekly_limit=max(weekly,1))
            if finish:
                recent['finish_date']=finish.isoformat()
                target=date.fromisoformat(str(plan['config']['target_date']))
                if finish>target:recent['weeks_late']=ceil((finish-target).days/7)
            else:recent['status']='no_estimate'
    return {'status':status,'completed_minutes':done,'expected_minutes':expected,'behind_minutes':max(0,expected-done) if status=='behind' else 0,'recent':recent}

def week_rows(plan,now):
    capacity=plan_capacity(plan,now);config=capacity.config
    start=week_of(date.fromisoformat(str(config.start_date)));target=date.fromisoformat(str(config.target_date))
    current=week_of(max(capacity.today,date.fromisoformat(str(config.start_date))))
    outline={row['week_start']:row for row in plan.get('outline',[])}
    rows=[];week=start
    while week<=target:
        key=week.isoformat();state=plan.get('week_states',{}).get(key,{});item=outline.get(key,{})
        members=[t for t in plan['assignments'] if t['week_start']==key and t['status'] in ('scheduled','completed','skipped') or (t.get('date') and week_of(day_of(t))==week and t['status'] in ('scheduled','completed'))]
        members=sorted({t['id']:t for t in members}.values(),key=lambda t:(str(t.get('date') or '9999'),t.get('start_time') or '',t['id']))
        eligible,planned,buffer=capacity.week_minutes(week)
        rows.append({'week_start':key,'state':'past' if week<current else 'current' if week==current else 'next' if week==current+timedelta(days=7) else 'later',
            'theme':item.get('theme'),'expected_output':item.get('expected_output'),'milestone_keys':item.get('milestone_keys',[]),'target_minutes':week_target(plan,week,capacity),
            'eligible_minutes':eligible,'planned_minutes':planned,'buffer_minutes':buffer,
            'scheduled_minutes':sum(t['duration_minutes'] for t in members if t['status']=='scheduled' and t.get('count_hours',True)),
            'completed_minutes':sum(t['duration_minutes'] for t in members if t['status']=='completed' and t.get('count_hours',True)),
            'paused':bool(state.get('paused')),'exception_task_ids':state.get('exception_task_ids',[]),'workload_source':state.get('workload_source'),
            'task_ids':[t['id'] for t in members],'contains_target':week<=target<=week+timedelta(days=6)})
        week+=timedelta(days=7)
    return rows
def backlog_rows(plan,now):
    board=Board(plan,now);rows=[]
    for task in plan['assignments']:
        if task['status']=='backlog':
            rows.append({'task_id':task['id'],'reason':task.get('backlog_reason') or 'Not scheduled yet.','week_start':task['week_start'],'suggested_slot':suggest_slot(plan,task,board)})
    return rows
def plan_budget_minutes(plan,now):
    capacity=plan_capacity(plan,now)
    return capacity.report(allow_past_start=True)['budget']['planned_minutes']
def archive_summary(plan,identifier,archived_at):
    """A compact past-roadmaps row, for either saved schema."""
    tasks=plan.get('assignments',[]);config=plan.get('config',{})
    if plan.get('schema_version')=='roadmap-v3':
        view=progress(plan);done,planned=view['roadmap_minutes']['completed'],view['roadmap_minutes']['planned']
        generated=[t for t in tasks if t.get('origin')=='generated' and t['status']!='removed']
        finished=sum(bool(m.get('completion')) for m in plan['milestones'])
    else:
        done=sum(t['duration_minutes'] for t in tasks if t['status']=='completed');planned=sum(m['estimated_minutes'] for m in plan['milestones'])+done
        generated=tasks;finished=sum(bool(m.get('outcome',{}).get('demonstrated')) for m in plan['milestones'])
    return {'id':identifier,'schema_version':plan.get('schema_version','unknown'),'role':(plan.get('assessment') or {}).get('role'),'summary':plan['summary'],
        'start_date':str(config.get('start_date')) if config.get('start_date') else None,'target_date':str(config.get('target_date')) if config.get('target_date') else None,'archived_at':archived_at,
        'completed_minutes':done,'planned_minutes':planned,'tasks_completed':sum(t['status']=='completed' for t in generated),'tasks_total':len(generated),
        'milestones_completed':finished,'milestones_total':len(plan['milestones'])}

DETAIL_MINIMUM=15
def window_weeks(capacity):
    """The current week and next week, both within the plan's dates."""
    current=week_of(max(capacity.today,capacity.start_date))
    return [week for week in (current,current+timedelta(days=7)) if capacity.target and week<=capacity.target]
def detail_needed(plan,now):
    """Weeks in the window that still only have an outline and have accepted work to fill them with."""
    capacity=plan_capacity(plan,now);rows=[]
    if not sum(row['undetailed'] for row in milestone_totals(plan).values()):return rows
    paused=set(paused_weeks(plan))
    for week in window_weeks(capacity):
        if week.isoformat() in paused:continue
        if any(t['origin']=='generated' and t['week_start']==week.isoformat() and t['status'] in ('scheduled','completed','skipped') for t in plan['assignments']):continue
        if capacity.between(week,week+timedelta(days=6))<DETAIL_MINIMUM or week_target(plan,week,capacity)-included_scheduled(plan,week)<DETAIL_MINIMUM:continue
        rows.append(week)
    return rows
