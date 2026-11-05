"""Deterministic task placement: no model calls happen here.

Everything works on one saved plan and an injected clock. Comparisons use wall-clock minutes on
local dates in the plan's time zone, so a task is missed once its local calendar day has ended and
a local time that a clock change skips can never be chosen. Repeating this module's reconciliation
produces no further changes, and the workspace's version fence decides between concurrent requests.
"""
import copy
import heapq
from datetime import date, timedelta
from elo_shared.runtime import Problem
from app.planning.capacity import Capacity, missing_local_minutes, to_clock, to_minute, subtract, week_of
from app.schemas.roadmap import PlannerConfig

MAX_AUTO_MOVES=2
MAX_EVENTS=500
UNFINISHED=('scheduled','backlog')
SETTLED_PREREQUISITE=('completed','skipped','removed')

def is_current_schema(plan):
    return bool(plan) and plan.get('schema_version')=='roadmap-v3'
def config_of(plan):
    return PlannerConfig.model_validate(plan['config'])
def day_of(task):
    return date.fromisoformat(str(task['date'])) if task.get('date') else None
def placed(task):
    return task['status']=='scheduled' and bool(task.get('date')) and bool(task.get('start_time'))
def task_span(task):
    begin=to_minute(task['start_time'])
    return begin,begin+task['duration_minutes']
def paused_weeks(plan):
    return [week for week,row in plan.get('week_states',{}).items() if row.get('paused')]
def plan_capacity(plan,now):
    done=[t for t in plan['assignments'] if t['status']=='completed']
    return Capacity(config_of(plan),now,done,paused_weeks(plan))
def slot_label(day,start):
    return f"{day.strftime('%A')} {start}"
def placement(task):
    return {'date':str(task['date']) if task.get('date') else None,'start_time':task.get('start_time'),'status':task['status'],'week_start':task['week_start'],
        'backlog_reason':task.get('backlog_reason'),'auto_moves':task.get('auto_moves',0),'action_needed':task.get('action_needed')}
def by_id(plan,task_id):
    task=next((t for t in plan['assignments'] if t['id']==task_id),None)
    if not task:raise Problem('This task was not found.',404,'not_found')
    return task
def changed(plan,task,now,action,**detail):
    """Every change to a task is recorded on it and fences any older proposal or undo."""
    task['revision']=task.get('revision',0)+1
    plan['revision']=plan.get('revision',0)+1
    task.setdefault('history',[]).append({'at':now.isoformat(),'action':action,**detail})
def add_event(plan,event_id,kind,now,message,*,task_id=None,undo=None):
    events=plan.setdefault('events',[])
    if any(e['id']==event_id for e in events):return False
    events.append({'id':event_id,'type':kind,'at':now.isoformat(),'task_id':task_id,'message':message,'undo':undo,'undone':False})
    del events[:-MAX_EVENTS]
    return True

class Board:
    """Who occupies which minutes, and how much of each week's maximum is used."""
    def __init__(self,plan,now):
        self.plan=plan;self.now=now;self.capacity=plan_capacity(plan,now);self.config=self.capacity.config
        self.occupied={};self.used={}
        for task in plan['assignments']:
            if task['status'] in ('scheduled','completed') and task.get('date'):self.book(task)
    def _week_cost(self,task):
        return task['duration_minutes'] if task.get('count_hours',True) else 0
    def book(self,task):
        day=day_of(task)
        if task.get('start_time'):self.occupied.setdefault(day,[]).append(task_span(task))
        week=week_of(day);self.used[week]=self.used.get(week,0)+self._week_cost(task)
    def release(self,task):
        day=day_of(task)
        if task.get('start_time') and task_span(task) in self.occupied.get(day,[]):self.occupied[day].remove(task_span(task))
        week=week_of(day);self.used[week]=self.used.get(week,0)-self._week_cost(task)
    def overlaps(self,day,begin,end):
        return any(begin<high and low<end for low,high in self.occupied.get(day,[]))
    def free(self,day,kind):
        return subtract(self.capacity.days.get(day,{}).get(kind,[]),self.occupied.get(day,[]))
    def find_slot(self,task,after=None,before=None):
        """Earliest contiguous slot: preferred time first within each week, then backup if permitted.

        Duration is preserved, so a task never splits. after and before are (day, minute) bounds.
        """
        cost=self._week_cost(task);duration=task['duration_minutes']
        weeks={}
        for day in sorted(self.capacity.days):weeks.setdefault(week_of(day),[]).append(day)
        kinds=('preferred','backup') if self.config.use_backup else ('preferred',)
        for week,days in sorted(weeks.items()):
            if self.used.get(week,0)+cost>self.capacity.cap:continue
            for kind in kinds:
                for day in days:
                    if after and day<after[0]:continue
                    if before and day>before[0]:continue
                    for low,high in self.free(day,kind):
                        start=max(low,after[1]) if after and day==after[0] else low
                        limit=min(high,before[1]) if before and day==before[0] else high
                        if start+duration<=limit:return day,start
        return None

def prerequisite_bounds(plan,task,now_key):
    """(after, before, blocker): where a task may go without violating dependency order."""
    keyed={t['key']:t for t in plan['assignments']}
    after=None;blocker=None
    for key in task.get('depends_on',[]):
        other=keyed.get(key)
        if not other or other['status'] in SETTLED_PREREQUISITE:continue
        if not placed(other) or (day_of(other),task_span(other)[0])<now_key:
            blocker=other;continue
        end=(day_of(other),task_span(other)[1])
        if after is None or end>after:after=end
    before=None
    for other in plan['assignments']:
        if task['key'] in other.get('depends_on',[]) and placed(other):
            start=(day_of(other),task_span(other)[0])
            if start>=now_key and (before is None or start<before):before=start
    return after,before,blocker
def dependency_order(plan,tasks):
    """Prerequisites first, then original scheduled time, then the stable task identifier."""
    keys={t['key']:t for t in tasks}
    waiting={t['key']:{k for k in t.get('depends_on',[]) if k in keys} for t in tasks}
    rank=lambda t:(str(t.get('date') or '9999'),t.get('start_time') or '',t['id'])
    ready=[(rank(t),t['key']) for t in tasks if not waiting[t['key']]]
    heapq.heapify(ready);ordered=[];seen=set()
    while ready:
        _,key=heapq.heappop(ready)
        if key in seen:continue
        seen.add(key);ordered.append(keys[key])
        for other,pending in waiting.items():
            if key in pending:
                pending.discard(key)
                if not pending:heapq.heappush(ready,(rank(keys[other]),other))
    return ordered+[t for t in sorted(tasks,key=rank) if t['key'] not in seen]
def to_backlog(plan,task,reason,now,action='backlog'):
    task.update(status='backlog',date=None,start_time=None,backlog_reason=reason,action_needed=None)
    changed(plan,task,now,action,reason=reason)
def place(plan,task,day,start,now,action,**detail):
    task.update(date=day.isoformat(),start_time=to_clock(start),week_start=week_of(day).isoformat(),status='scheduled',backlog_reason=None,action_needed=None)
    changed(plan,task,now,action,**detail)
def needs_action(plan,task,reason,message,now):
    task['action_needed']={'reason':reason,'message':message,'occurrence':str(task.get('date'))}
    changed(plan,task,now,'action_needed',reason=reason)
def now_key(capacity):
    return capacity.today,capacity.now_minute

def reconcile_tasks(plan,now):
    """Handle tasks whose local day has ended. Returns how many tasks changed."""
    board=Board(plan,now);today=board.capacity.today;count=0;movable=[]
    for task in plan['assignments']:
        if not placed(task) or day_of(task)>=today or task.get('action_needed'):continue
        title=task['task'];count+=1
        if task['origin']=='custom':needs_action(plan,task,'missed_custom',f'“{title}” was missed. Custom tasks stay where you put them, so choose what to do.',now)
        elif task.get('pinned'):needs_action(plan,task,'missed_pinned',f'“{title}” was pinned and missed. Choose what to do.',now)
        elif task.get('auto_moves',0)>=MAX_AUTO_MOVES:needs_action(plan,task,'auto_move_limit',f'“{title}” has already moved twice automatically. Choose what to do instead.',now)
        else:movable.append(task)
    key=now_key(board.capacity)
    for task in dependency_order(plan,movable):
        origin=placement(task);where=f"{task['date']}:{task['start_time']}"
        board.release(task)
        # The task's old slot is past, so its own span no longer limits anything.
        after,before,blocker=prerequisite_bounds(plan,task,key)
        slot=None if blocker else board.find_slot(task,after,before)
        if slot:
            day,start=slot
            task['auto_moves']=task.get('auto_moves',0)+1
            place(plan,task,day,start,now,'auto_move',origin=origin)
            board.book(task)
            add_event(plan,f"auto:{task['id']}:{where}",'auto_move',now,f'Moved to {slot_label(day,to_clock(start))}',task_id=task['id'],undo={**origin,'revision':task['revision']})
        else:
            if blocker:reason=f"It depends on “{blocker['task']}”, which isn't scheduled yet."
            elif before:reason='No study slot fits before the task that depends on it.'
            else:reason='No study slot of this length fits before your target date.'
            to_backlog(plan,task,reason,now,'auto_backlog')
            add_event(plan,f"auto:{task['id']}:{where}",'auto_backlog',now,'Moved to Backlog: '+reason,task_id=task['id'],undo={**origin,'revision':task['revision']})
        count+=1
    return count

def undo_event(plan,event_id,now):
    event=next((e for e in plan.get('events',[]) if e['id']==event_id),None)
    if not event or not event.get('undo'):raise Problem('This change can no longer be undone.',404,'not_found')
    if event['undone']:return
    task=by_id(plan,event['task_id']);prior=event['undo']
    if task.get('revision',0)!=prior['revision'] or task['status'] not in UNFINISHED:
        raise Problem('This task changed after it moved, so the move can’t be undone. Choose a new time for it instead.',409,'undo_conflict')
    day=date.fromisoformat(prior['date']) if prior['date'] else None
    if day and prior['start_time']:
        board=Board(plan,now)
        if task['status']=='scheduled':board.release(task)
        begin=to_minute(prior['start_time'])
        if board.overlaps(day,begin,begin+task['duration_minutes']):
            raise Problem('Something else now occupies that time, so the move can’t be undone. Choose a new time for it instead.',409,'undo_conflict')
    task.update(date=prior['date'],start_time=prior['start_time'],status=prior['status'],week_start=prior['week_start'],backlog_reason=prior.get('backlog_reason'),auto_moves=prior.get('auto_moves',0))
    needs_action(plan,task,'undone',f'You undid the automatic move of “{task["task"]}”. Choose what to do with it.',now)
    event['undone']=True
    add_event(plan,f"undo:{event_id}",'undo',now,'Automatic move undone',task_id=task['id'])

def check_placement(plan,task,day,start,now,confirm_outside=False):
    """Validate a user's chosen slot. Returns (paused_week, outside_blocks), or raises a Problem that explains the failure."""
    capacity=plan_capacity(plan,now);begin=to_minute(start);end=begin+task['duration_minutes']
    if end>1440:raise Problem('This task would run past midnight. Choose an earlier time.',409,'slot_invalid')
    if (day,begin)<now_key(capacity):raise Problem('That time has already passed. Choose a later one.',409,'slot_in_past')
    if capacity.target and day>capacity.target:raise Problem(f'That is after your target date of {capacity.target}. Change the target date with Edit plan to go beyond it.',409,'after_target')
    if any(begin<high and low<end for low,high in missing_local_minutes(day,capacity.zone)):raise Problem('That local time is skipped by a clock change. Choose another time.',409,'slot_invalid')
    if any(begin<high and low<end for low,high in capacity.blackout_windows(day)):raise Problem('That time is inside one of your blackouts. Choose another time.',409,'slot_blackout')
    board=Board(plan,now)
    if task['status']=='scheduled' and task.get('date'):board.release(task)
    if board.overlaps(day,begin,end):raise Problem('Another task already occupies that time. Choose another placement.',409,'slot_occupied')
    week=week_of(day)
    if task.get('count_hours',True) and board.used.get(week,0)+task['duration_minutes']>capacity.cap:
        raise Problem(f'That week would pass your weekly maximum of {capacity.cap/60:g} hours. Choose another week, or exclude a custom task from hours.',409,'weekly_maximum')
    after,before,blocker=prerequisite_bounds(plan,task,now_key(capacity))
    if after and (day,begin)<after:raise Problem('This task depends on one scheduled later. Choose a time after it finishes.',409,'dependency_order')
    if before and (day,end)>before:raise Problem('Another task depends on this one. Choose a time before that task starts.',409,'dependency_order')
    if blocker and task['origin']=='generated':raise Problem(f"This task depends on “{blocker['task']}”, which isn't scheduled yet. Place that task first.",409,'dependency_order')
    paused=week.isoformat() in paused_weeks(plan)
    windows=capacity.days.get(day,{'preferred':[],'backup':[]})
    allowed=[*windows['preferred'],*(windows['backup'] if capacity.config.use_backup else [])]
    inside=any(low<=begin and end<=high for low,high in allowed)
    if not inside and not confirm_outside:
        message='That week is paused. Keep this task there as an exception?' if paused else 'That time is outside your enabled study blocks. Place it there anyway?'
        raise Problem(message,409,'paused_week' if paused else 'outside_study_blocks')
    return paused,not inside
def move_task(plan,task,day,start,now,confirm_outside=False):
    if task['status'] not in UNFINISHED:raise Problem('Only unfinished tasks can be moved.',409,'task_finished')
    paused,_=check_placement(plan,task,day,start,now,confirm_outside)
    origin=placement(task)
    baseline=task.get('baseline')
    if baseline and week_of(date.fromisoformat(baseline[:10]))==week_of(day):task['baseline']=f'{day} {start}'
    if not baseline:task['baseline']=f'{day} {start}'
    task['manual_moves']=task.get('manual_moves',0)+1
    place(plan,task,day,to_minute(start),now,'manual_move',origin=origin)
    if paused:
        row=plan.setdefault('week_states',{}).setdefault(week_of(day).isoformat(),{})
        row.setdefault('exception_task_ids',[])
        if task['id'] not in row['exception_task_ids']:row['exception_task_ids'].append(task['id'])
    add_event(plan,f"manual:{task['id']}:{task['revision']}",'manual_move',now,f'Moved to {slot_label(day,start)}',task_id=task['id'])
    if task['origin']=='custom':plan['progress_revision']=plan.get('progress_revision',0)+1

def complete_task(plan,task,note,feedback,now,capacity):
    if task['status']=='completed' and (task.get('evidence_note')==note or note is None) and (feedback is None or feedback==task.get('feedback')):return False
    if task['status'] in ('skipped','removed'):raise Problem('Return this task to Backlog before completing it.',409,'task_finished')
    prior=task['status']
    task.setdefault('history',[]).append({'at':now.isoformat(),'from':prior,'to':'completed','evidence_note':task.get('evidence_note')})
    if not task.get('date'):task['date']=capacity.today.isoformat();task['week_start']=week_of(capacity.today).isoformat()
    task.update(status='completed',completed_at=now.isoformat(),evidence_note=note,action_needed=None,backlog_reason=None)
    if feedback:task['feedback']=feedback
    task['revision']=task.get('revision',0)+1;plan['revision']=plan.get('revision',0)+1;plan['progress_revision']=plan.get('progress_revision',0)+1
    add_event(plan,f"complete:{task['id']}:{task['revision']}",'complete',now,f"Completed “{task['task']}”",task_id=task['id'])
    return True
def reopen_task(plan,task,now,capacity):
    if task['status']!='completed':return False
    task.setdefault('history',[]).append({'at':now.isoformat(),'from':'completed','to':'scheduled','evidence_note':task.get('evidence_note')})
    task.update(status='scheduled',completed_at=None,evidence_note=None,feedback=None)
    task['revision']=task.get('revision',0)+1;plan['revision']=plan.get('revision',0)+1;plan['progress_revision']=plan.get('progress_revision',0)+1
    if not task.get('start_time'):
        task.update(status='backlog',date=None,backlog_reason='Reopened after completion.')
    elif day_of(task)<capacity.today or (day_of(task)==capacity.today and task_span(task)[0]<capacity.now_minute):
        task['action_needed']={'reason':'reopened','message':f"You reopened “{task['task']}”. Its time has passed, so choose what to do.",'occurrence':str(task['date'])}
    add_event(plan,f"reopen:{task['id']}:{task['revision']}",'reopen',now,f"Reopened “{task['task']}”",task_id=task['id'])
    return True
def skip_task(plan,task,now):
    if task['status'] not in UNFINISHED:raise Problem('Only unfinished tasks can be skipped.',409,'task_finished')
    origin=placement(task)
    task.update(status='skipped',action_needed=None,backlog_reason=None)
    changed(plan,task,now,'skip',origin=origin)
    plan['progress_revision']=plan.get('progress_revision',0)+1
    add_event(plan,f"skip:{task['id']}:{task['revision']}",'skip',now,f"Skipped “{task['task']}”",task_id=task['id'])
def restore_task(plan,task,now):
    if task['status'] not in ('skipped','removed'):raise Problem('Only skipped or removed tasks can return to Backlog.',409,'task_finished')
    task.update(status='backlog',date=None,start_time=None,backlog_reason='Returned to Backlog by you.',removed_reason=None,action_needed=None)
    changed(plan,task,now,'restore')
    plan['progress_revision']=plan.get('progress_revision',0)+1
    add_event(plan,f"restore:{task['id']}:{task['revision']}",'restore',now,f"Returned “{task['task']}” to Backlog",task_id=task['id'])
def suggest_slot(plan,task,board):
    after,before,blocker=prerequisite_bounds(plan,task,now_key(board.capacity))
    slot=None if blocker else board.find_slot(task,after,before)
    return {'date':slot[0].isoformat(),'start_time':to_clock(slot[1])} if slot else None

def replan_future(plan,now):
    """Keep future generated tasks that are still valid; re-place the rest. Pinned and custom tasks stay put.

    Used by previews, on a private copy of the plan. Returns titles moved and titles sent to Backlog.
    """
    capacity=plan_capacity(plan,now);key=now_key(capacity);board=Board(plan,now)
    movable=[t for t in plan['assignments'] if placed(t) and t['origin']=='generated' and not t.get('pinned') and (day_of(t),task_span(t)[0])>=key]
    for task in movable:board.release(task)
    moved=[];sent=[];loose=[]
    for task in dependency_order(plan,movable):
        day=day_of(task);begin,end=task_span(task)
        windows=capacity.days.get(day,{'preferred':[],'backup':[]})
        allowed=[*windows['preferred'],*(windows['backup'] if capacity.config.use_backup else [])]
        week=week_of(day);cost=board._week_cost(task)
        fits=any(low<=begin and end<=high for low,high in allowed) and not board.overlaps(day,begin,end) and board.used.get(week,0)+cost<=capacity.cap
        if fits:board.book(task)
        else:loose.append(task)
    waiting={t['id'] for t in loose}
    for task in loose:
        waiting.discard(task['id'])
        after,before,blocker=prerequisite_bounds({**plan,'assignments':[t for t in plan['assignments'] if t['id'] not in waiting]},task,key)
        slot=None if blocker else board.find_slot(task,after,before)
        if slot:
            place(plan,task,slot[0],slot[1],now,'replanned');task['baseline']=f"{slot[0]} {to_clock(slot[1])}";board.book(task);moved.append(task['task'])
        else:
            to_backlog(plan,task,'No study slot of this length fits before your target date.',now,'replanned');sent.append(task['task'])
    return moved,sent
def private_copy(plan):
    return copy.deepcopy(plan)
def future_weeks(plan,now):
    capacity=plan_capacity(plan,now)
    week=week_of(capacity.start);rows=[]
    while capacity.target and week<=capacity.target:
        rows.append(week);week+=timedelta(days=7)
    return rows
