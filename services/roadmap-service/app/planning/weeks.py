"""One reviewed week of tasks at a time, for an accepted outline.

The model writes the week's tasks and proposes what happens to unfinished work. The
service places every session (see placement.py), checks the week against the agreed
hours, and applies nothing until the user accepts the preview. Published work stays as
canonical editable tasks, so progress, notes, edits and history are never rewritten.
"""
import copy
import json
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from uuid import NAMESPACE_URL, uuid5
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.plans import FREE_ROADMAP_DETAIL_WEEKS, PREMIUM_REQUIRED, account_type
from elo_shared.runtime import ErrorView, Problem, authenticated, begin, digest, launch, operation_view, stamp
from app.planning.capacity import Capacity, Placer, shortest_session, to_minute
from app.planning.milestone_membership import mark_plan_membership_changes
from app.planning.placement import reservations, week_target
from app.planning.generator import MAX_ATTEMPTS, PLAN_MAX_TOKENS, PLANNING_SECONDS, set_stage
from app.planning.state import config_digest, evaluation_current, planner_state, saved_config, schedule_digest, shape_digest, planning_source_changed
from app.planning.tasks import ensure_tasks, project_assignments
from app.schemas.base import Mutation
from app.schemas.planner import Workspace
from app.schemas.roadmap import OperationAccepted, PlannerConfig
from app.schemas.weeks import GenerateWeek, ReviewCarryover, WeekDraft

WEEK_INSTRUCTIONS='''Plan one week of a personal study roadmap. Write only this week's tasks; the service schedules them, so never give dates or times.

Tasks. Advance this week's objective and the supplied milestones. Each task has a short actionable title of at most 11 whitespace-separated words (under 12 words) that starts with a verb, a brief instructions summary, a detailed description, one observable completion_outcome the user can check for themselves, and duration_minutes for the whole task. The title must effectively summarise the action, not contain the full instructions. description must explain what the task is about and give numbered steps in order, including how to perform them, useful approaches or tools appropriate to the supplied context, and how to check the final result against completion_outcome. Make the guidance specific and usable without inventing resources or URLs. A task longer than session_minutes is split into sessions with breaks by the service, so size tasks by the work, not by the session. New tasks must total no more than new_task_minutes and should come close to it while real work remains in remaining_scope; never invent work only to fill time. Do not repeat routines, saved work or removed work. Use a diagnostic task of at most 30 minutes for each gap in diagnostics_needed.

Adapting. progress and last_week show what the user actually did: completed, in-progress and unfinished tasks, their own difficulty and confidence ratings, and their feedback about workload. Use them to set this week's difficulty, pace and focus. Finishing a task is self-reported progress, not proof of skill.

Unfinished work. For every task in progress.unfinished return one carryover entry with its task_id, a short reason the user can read, and an action: carry (do the whole task this week), split (do `minutes` of it this week and leave the rest in the backlog), defer (leave it in the backlog for a later week) or drop (it is no longer worth doing). Saved sessions, including missed sessions, already count against the capacity of their scheduled week. Carried work also uses this week's available hours. Subtract any carried or split minutes scheduled this week from new_task_minutes, and carry at most carry_limit_minutes. Follow settings.unfinished_default when it is carry or defer unless the progress clearly argues otherwise.

Later weeks. Only when this week's progress means a later week's objective no longer makes sense, return objective_changes for those weeks with the full replacement objective and a reason. Otherwise return none.

summary explains, in two or three sentences addressed to the user, what this week focuses on and how last week's results shaped it. Do not invent proficiency or guarantees. If validation_errors is present, fix every listed error and return the complete corrected week.'''
MAX_WEEK_BYTES=128*1024
MAX_ACTIVE_BYTES=512*1024
MAX_UNFINISHED=40

def bounded_size(value,limit,message):
    if len(json.dumps(value,ensure_ascii=False,separators=(',',':'),default=str).encode('utf-8'))>limit:
        raise Problem(message,413,'week_capacity')

def day_of(value):
    return date.fromisoformat(str(value))

def week_detail_locked(account,outline,week):
    if account_type(account)=='premium':return False
    included=sorted(item['week_start'] for item in outline.get('weeks',[]))[:FREE_ROADMAP_DETAIL_WEEKS]
    return week.isoformat() not in included

def premium_week():
    return Problem('Generating task details after the first two weeks is part of elo Premium.',402,PREMIUM_REQUIRED)

def week_interval(week_start,config,now):
    """The inclusive first and exclusive last local date of a week, clipped to today and the roadmap."""
    capacity=Capacity(config,now)
    if not capacity.target:raise Problem('Choose a target date before planning a week.',409,'generation_blocked')
    if capacity.week(week_start)!=week_start:raise Problem('Choose the first day of a week.',422,'invalid_week')
    start=max(week_start,capacity.start_date,capacity.today)
    end=min(week_start+timedelta(days=7),capacity.target+timedelta(days=1))
    if start>=end:raise Problem('This week has no remaining dates within the roadmap.',409,'week_outside_roadmap')
    return start,end

def week_block(state,week):
    return next((b for b in state.get('week_blocks',[]) if b['week_start']==week.isoformat() and b.get('status')=='accepted'),None)

def week_is_planned(state,week,config,now):
    """Accepted for this week, or covered by a month accepted before weekly planning. A week outside the roadmap needs no plan."""
    try:start,end=week_interval(week,config,now)
    except Problem:return True
    if week_block(state,week):return True
    return any(b.get('status')=='accepted' and b['start_date']<=start.isoformat() and b['end_exclusive']>=end.isoformat() for b in state.get('month_blocks',[]))

def slot_passed(slot,capacity):
    day=day_of(slot['date'])
    return day<capacity.today or (day==capacity.today and to_minute(slot['start_time'])<capacity.now_minute)

def unfinished(plan,capacity):
    """Work that needs a decision: not done, with all its planned time already passed, or deferred earlier."""
    if not plan:return []
    result=[]
    for task in ensure_tasks(copy.deepcopy(plan)):
        if task.get('removed') or task['status']=='completed':continue
        schedule=task.get('schedule') or []
        if (schedule and all(slot_passed(slot,capacity) for slot in schedule)) or (not schedule and (task.get('deferred_week') or task.get('anytime_date') and day_of(task['anytime_date'])<capacity.today)):
            result.append(task)
    if len(result)>MAX_UNFINISHED:raise Problem('More than 40 unfinished tasks need review. Review the backlog before planning another week; no work was omitted.',413,'week_capacity')
    return result

def planning(state,now,config=None,ignore_candidate=False):
    """Which week can be planned now, and why."""
    outline=state.get('outline_active');active=state.get('active')
    if not outline or not active:return None
    config=config or saved_config(state);capacity=Capacity(config,now)
    if not capacity.target or capacity.target<capacity.today:return None
    today=capacity.today;current=capacity.week(today);base=max(current,capacity.week(capacity.start))
    tasks=[t for t in ensure_tasks(copy.deepcopy(active)) if not t.get('removed')]
    this_week=[t for t in tasks if any(base<=day_of(s['date'])<base+timedelta(days=7) for s in t.get('schedule',[])) or t.get('anytime_date') and base<=day_of(t['anytime_date'])<base+timedelta(days=7)]
    done=bool(this_week) and all(t['status']=='completed' for t in this_week)
    last=base+timedelta(days=6);following=base+timedelta(days=7)
    plan_date=base+timedelta(days=(config.plan_day-config.week_start_day)%7) if config.plan_day is not None else last
    result={'current_week_start':base.isoformat(),'plan_day':plan_date.isoformat(),'week_done':done,'action':None,'week_start':None,
        'available':False,'reason':None,'unfinished_count':len(unfinished(active,capacity)),'notice':state.get('week_notice')}
    candidate=state.get('week_candidate')
    if candidate and not ignore_candidate:
        result.update(action='review',week_start=candidate['week_start'],available=True,reason='preview_ready')
    elif not week_is_planned(state,base,config,now):
        result.update(action='plan_this',week_start=base.isoformat(),available=True,reason='week_unplanned')
    elif not week_is_planned(state,following,config,now):
        opened=done or today>=plan_date
        result.update(action='plan_next',week_start=following.isoformat(),available=opened,reason='week_done' if done else 'plan_day' if opened else 'waiting')
    return result

def check_basis(state,source,outline,accepted=True):
    if not outline or (accepted and outline.get('status')!='accepted'):raise Problem('Accept a roadmap outline before planning a week.',409,'outline_required')
    if not source.get('ready') or source.get('input_hash')!=outline['assessment_hash']:
        raise Problem('Your goal or evidence changed. Review the outline first.',409,'inputs_changed')
    if not evaluation_current(source):
        raise Problem('Update your skill evaluation before planning or accepting work.',409,'assessment_required')
    if shape_digest(saved_config(state))!=shape_digest(PlannerConfig.model_validate(outline['config'])):
        raise Problem('Your timeline or weekly hours changed. Review the outline first.',409,'settings_changed')
    if digest(state.get('confirmations',{}))!=outline['confirmations_hash']:
        raise Problem('Your confirmations changed. Review the outline first.',409,'inputs_changed')

def revision_basis(active,block,now,config):
    """Release only untouched future generated work belonging to this week.

    Tombstones, notes, history and prerequisite relationships stay intact. Returns an
    isolated scheduling basis and the IDs explicitly replaced.
    """
    if not active or not block:raise Problem('There is no accepted week to revise.',409,'week_not_found')
    plan=copy.deepcopy(active);tasks=ensure_tasks(plan);belong=set(block.get('task_ids',[]))
    linked={key for task in tasks for key in task.get('prerequisites',[])}
    capacity=Capacity(config,now);replaced=[]
    for task in tasks:
        if task['id'] not in belong or task.get('origin')!='generated' or task.get('removed'):continue
        if task.get('status')!='not_started' or task.get('overrides') or task.get('history') or task.get('evidence_note') or task.get('notes') or task.get('self_rating'):continue
        if task.get('prerequisites') or task['id'] in linked or not task.get('schedule'):continue
        if any(slot_passed(slot,capacity) for slot in task['schedule']):continue
        replaced.append(task['id'])
    plan['editable_tasks']=[task for task in tasks if task['id'] not in set(replaced)]
    project_assignments(plan)
    return plan,replaced

def task_record(item,identifier,outline,week,*,routine_id=None):
    gap=next((g for g in outline['gaps'] if g['id']==item.get('gap_id')),None)
    result={'id':identifier,'title':item['title'],'instructions':item['instructions'],'description':item['description'],
        'completion_outcome':item['completion_outcome'],'estimated_minutes':item['duration_minutes'],
        'requirement_refs':[gap['requirement_ref']] if gap and gap.get('requirement_ref') else [],'requirement_source_hash':outline['assessment_hash'],
        'requirement_source_id':outline['assessment_id'],'prerequisites':[],
        'milestone_key':item['milestone_key'],'schedule':copy.deepcopy(item.get('schedule',[])),
        'status':'not_started','completed_at':None,'evidence_note':None,'history':[],
        'removed':False,'removal':None,'definition_review_required':False,
        'generated_key':item['key'],'origin':'generated','overrides':[],'week_start':week.isoformat(),
        'source_assignment':{'kind':item.get('kind','study'),'gap_id':item.get('gap_id'),'calendar_uses_title':True}}
    if routine_id:result['routine_rule_id']=routine_id
    return result

def routine_occurrences(outline,config,start,end,now,existing):
    """Place every eligible routine occurrence on its own day, or return an explicit conflict."""
    known={t['id'] for t in ensure_tasks(copy.deepcopy(existing))} if existing else set()
    milestones={m['key'] for m in outline['milestones']}
    placer=Placer(config,now,reservations(existing),start,end);output=[]
    for rule in outline.get('routine_rules',[]):
        if rule['milestone_key'] not in milestones:raise Problem('A routine refers to a missing milestone.',409,'routine_milestone_missing')
        first=day_of(rule['start_date']);last=day_of(rule['end_date']) if rule.get('end_date') else end-timedelta(days=1)
        weekdays=set(rule['weekdays']);day=max(start,first)
        while day<end and day<=last:
            ident=str(uuid5(NAMESPACE_URL,'roadmap:routine:'+rule['id']+':'+day.isoformat()))
            if day.weekday() in weekdays and ident not in known:
                schedule=placer.place(rule['duration_minutes'],only=day)
                if not schedule:
                    raise Problem(f"Routine '{rule['activity']}' cannot fit on {day}. Adjust the routine or your study times before planning this week.",409,'routine_conflict')
                topics=rule.get('topic_progression') or []
                index=sum(1 for n in range((day-first).days+1) if (first+timedelta(days=n)).weekday() in weekdays)-1
                title=' '.join(str(v).strip() for v in (rule['activity'],rule.get('difficulty'),topics[index%len(topics)] if topics else None) if v and str(v).strip())
                if len(title)>160 or len(title.split())>11:raise Problem('Shorten the routine activity, topic or difficulty to fit a task title.',422,'routine_title')
                item={'key':ident,'milestone_key':rule['milestone_key'],'title':title,'instructions':f"{rule['activity']}. Review your work and record one lesson.",
                    'description':f"1. Prepare your practice material for {title}. Choose an exercise suited to this topic and difficulty.\n2. Work through the exercise, checking your approach as you go and noting questions or mistakes.\n3. Review the result, correct mistakes, and save your work with a brief reflection on one lesson.",
                    'completion_outcome':'Save your work and a brief reflection.','duration_minutes':rule['duration_minutes'],'schedule':schedule}
                output.append(task_record(item,ident,outline,placer.capacity.week(day),routine_id=rule['id']))
                output[-1]['source_assignment']['routine_user_wording']=rule.get('user_wording','')
                known.add(ident)
            day+=timedelta(days=1)
    return output

def remaining_scope(outline,existing,routines,end):
    """Per milestone that has begun, the estimated effort not yet given to a task."""
    used={}
    for task in (ensure_tasks(copy.deepcopy(existing)) if existing else [])+routines:
        if task.get('removed'):continue
        used[task.get('milestone_key')]=used.get(task.get('milestone_key'),0)+task.get('estimated_minutes',0)
    return {m['key']:max(0,m['estimated_minutes']-used.get(m['key'],0)) for m in outline['milestones'] if day_of(m['projected_start'])<end}

def carry_limit(config):
    return config.max_carry_minutes if config.max_carry_minutes is not None else (config.weekly_minutes or 0)//2

def arrange(config,now,existing,start,end,routines,carryover,tasks):
    """Place carried work, then new tasks. What cannot fit is deferred or listed, never dropped or squeezed in."""
    placer=Placer(config,now,reservations(existing)+[slot for task in routines for slot in task['schedule']],start,end)
    limit=carry_limit(config);carried=0
    for entry in carryover:
        entry['schedule']=[]
        if entry['action'] not in ('carry','split'):continue
        minutes=entry['minutes'] if entry['action']=='split' else entry['estimated_minutes']
        if carried+minutes>limit:
            entry.update(action='defer',adjusted=True,reason=f'Kept in your backlog: carrying it would put more than {limit} minutes of unfinished work into one week.');continue
        schedule=placer.place(minutes)
        if not schedule:
            entry.update(action='defer',adjusted=True,reason='Kept in your backlog: no free study time this week can hold it.');continue
        entry['schedule']=schedule;carried+=minutes
    placed=[];unplaced=[]
    for task in tasks:
        schedule=placer.place(task['estimated_minutes'])
        if schedule:placed.append({**task,'schedule':schedule})
        else:unplaced.append({**task,'schedule':[]})
    return placed,unplaced

def week_opening(week,config):
    """Start of the planned week, for validating later projected capacity."""
    return datetime.combine(day_of(week),datetime.min.time(),tzinfo=ZoneInfo(config.time_zone))

def check_week(draft,outline,config,existing,routines,pending,target,scope,*,feedback=None,diagnostics=()):
    """Every reason the proposed week cannot be used, before any session is placed."""
    errors=[];keys=set();milestones={m['key']:m for m in outline['milestones']}
    saved=ensure_tasks(copy.deepcopy(existing)) if existing else []
    normal=lambda text:' '.join(text.casefold().split())
    blocked={(t.get('milestone_key'),normal(t.get('title',''))) for t in [*saved,*routines]}
    new_minutes=0;effort={}
    for item in draft.tasks:
        label=f"Task '{item.key}'"
        if item.key in keys:errors.append(f'{label} repeats a key.')
        keys.add(item.key)
        signature=(item.milestone_key,normal(item.title))
        if signature in blocked:errors.append(f'{label} repeats saved, unfinished or removed work. Use carryover for unfinished work instead of writing it again.')
        blocked.add(signature)
        milestone=milestones.get(item.milestone_key)
        if not milestone:errors.append(f'{label} has an unknown milestone.');continue
        if item.milestone_key not in scope:errors.append(f'{label} belongs to a milestone that has not started yet.')
        if item.gap_id and (item.gap_id not in milestone.get('gap_ids',[]) or not any(g['id']==item.gap_id for g in outline['gaps'])):
            errors.append(f'{label} links a gap outside its milestone.')
        if item.kind=='diagnostic' and not item.gap_id:errors.append(f'{label} needs a specific gap for its diagnostic.')
        if item.kind=='diagnostic' and item.duration_minutes>30:errors.append(f'{label} is a diagnostic and must take at most 30 minutes.')
        new_minutes+=item.duration_minutes;effort[item.milestone_key]=effort.get(item.milestone_key,0)+item.duration_minutes
    for key,minutes in effort.items():
        if minutes>scope.get(key,0):errors.append(f"Tasks for milestone '{key}' exceed its remaining estimated effort of {scope.get(key,0)} minutes.")
    known={task['id']:task for task in pending};seen=set()
    for entry in draft.carryover:
        task=known.get(entry.task_id)
        if not task:errors.append(f"Carryover '{entry.task_id}' is not one of the unfinished tasks.");continue
        if entry.task_id in seen:errors.append(f"Carryover '{entry.task_id}' is listed twice.")
        seen.add(entry.task_id)
        if entry.action=='split' and not (entry.minutes and shortest_session(config)<=entry.minutes<task['estimated_minutes']):
            errors.append(f"Carryover '{entry.task_id}' is split, so minutes must be less than its {task['estimated_minutes']} minutes and at least {shortest_session(config)}.")
    carryover=build_carryover(draft,pending,config)
    carried=0
    for entry in carryover:
        minutes=entry.get('minutes') if entry['action']=='split' else entry['estimated_minutes']
        if entry['action'] in ('carry','split') and minutes and carried+minutes<=carry_limit(config):carried+=minutes
    room=max(0,target['target_minutes']-sum(t['estimated_minutes'] for t in routines)-carried)
    if new_minutes>room:errors.append(f'New tasks total {new_minutes} minutes but this week has room for {room} after routines and carried work.')
    wanted=min(room,sum(scope.values()))
    if feedback and feedback.get('workload')=='too_much':wanted=wanted*7//10
    slack=max(shortest_session(config),target['target_minutes']//10)
    if not errors and new_minutes<wanted-slack:
        errors.append(f'This week is {wanted-new_minutes} minutes under the agreed hours while work remains. Add tasks that advance the objective, up to {room} minutes of new work in total.')
    for gap_id in diagnostics:
        if not any(t.kind=='diagnostic' and t.gap_id==gap_id for t in draft.tasks):
            errors.append(f"Gap '{gap_id}' needs a diagnostic of at most 30 minutes in the first planned week.")
    weeks={w['week_start'] for w in outline.get('weeks',[])};changed=set()
    for change in draft.objective_changes:
        label=f"Objective change for {change.week_start}"
        if change.week_start.isoformat() not in weeks or change.week_start.isoformat()<=target['week_start']:errors.append(f'{label} must name a later week of this roadmap.')
        if change.week_start in changed:errors.append(f'{label} is repeated.')
        changed.add(change.week_start)
        if change.milestone_key not in milestones:errors.append(f'{label} has an unknown milestone.')
        if change.estimated_minutes>(config.weekly_minutes or 0):errors.append(f'{label} estimates more than the weekly hours.')
        if any(gap not in {g['id'] for g in outline['gaps']} for gap in change.gap_ids):errors.append(f'{label} names an unknown gap.')
    changed_rows={change.week_start.isoformat():change.model_dump(mode='json') for change in draft.objective_changes}
    projected=[changed_rows.get(row['week_start'],row) for row in outline.get('weeks',[])]
    estimates={}
    for row in projected:
        estimates[row['milestone_key']]=estimates.get(row['milestone_key'],0)+row['estimated_minutes']
    for key,minutes in estimates.items():
        if key in milestones and minutes>milestones[key]['estimated_minutes']:errors.append(f"Future objectives exceed milestone '{key}' estimated effort.")
    available=Capacity(config,week_opening(target['week_start'],config)).weeks() if draft.objective_changes else []
    available={row['week_start']:row['usable_minutes'] for row in available}
    for change in draft.objective_changes:
        milestone=milestones.get(change.milestone_key)
        if milestone:
            if change.estimated_minutes and (day_of(milestone['projected_start'])>change.week_start+timedelta(days=6) or day_of(milestone['projected_end'])<change.week_start):errors.append('A revised objective falls outside its milestone dates.')
            if not set(change.gap_ids)<=set(milestone.get('gap_ids',[])):errors.append('A revised objective names skills outside its milestone.')
        if change.estimated_minutes>available.get(change.week_start.isoformat(),0):errors.append('A revised objective exceeds that week’s available study capacity.')
    return errors[:60]

def snapshot(task):
    return {key:copy.deepcopy(task.get(key)) for key in ('id','status','removed','schedule','anytime_date','estimated_minutes','title','instructions','description','completion_outcome','milestone_key','prerequisites','requirement_refs','overrides','history','notes','self_rating','definition_review_required')}

def week_basis(outline,existing,week,pending):
    """What a preview depends on: the outline, the target week's saved tasks and the unfinished work it moves."""
    tasks=ensure_tasks(copy.deepcopy(existing)) if existing else []
    inside=[snapshot(t) for t in tasks if any(week<=day_of(s['date'])<week+timedelta(days=7) for s in t.get('schedule',[])) or t.get('anytime_date') and week<=day_of(t['anytime_date'])<week+timedelta(days=7)]
    return digest({'outline':[outline['id'],outline['revision']],'week':sorted(inside,key=lambda t:t['id']),'pending':sorted([snapshot(t) for t in pending],key=lambda t:t['id'])})

def last_week_summary(existing,week):
    tasks=[t for t in (ensure_tasks(copy.deepcopy(existing)) if existing else []) if not t.get('removed')]
    previous=week-timedelta(days=7)
    members=[t for t in tasks if any(previous<=day_of(s['date'])<week for s in t.get('schedule',[])) or t.get('anytime_date') and previous<=day_of(t['anytime_date'])<week]
    done=[t for t in members if t['status']=='completed']
    ratings=[t['self_rating'] for t in done if t.get('self_rating')]
    mean=lambda name:round(sum(r[name] for r in ratings if r.get(name))/max(1,sum(1 for r in ratings if r.get(name))),1) if any(r.get(name) for r in ratings) else None
    minutes=lambda t:t['estimated_minutes'] if t.get('anytime_date') else sum(s['duration_minutes'] for s in t.get('schedule',[]) if previous<=day_of(s['date'])<week)
    return {'tasks_planned':len(members),'tasks_completed':len(done),'minutes_planned':sum(minutes(t) for t in members),
        'minutes_completed':sum(minutes(t) for t in done),'average_difficulty':mean('difficulty'),'average_confidence':mean('confidence')}

def first_open_week(state,outline,config,now):
    """The week a new outline should open with: the current roadmap week when it still needs sessions."""
    capacity=Capacity(config,now)
    if not capacity.target:return None
    base=max(capacity.week(capacity.today),capacity.week(capacity.start))
    week=base
    while week<=capacity.target:
        candidate_week=week;week+=timedelta(days=7)
        if any(item['kind']=='week' and item['id']==candidate_week.isoformat() for item in (outline.get('partial_review') or {}).get('omitted_items',[])):continue
        if week_is_planned(state,candidate_week,config,now):continue
        try:start,end=week_interval(candidate_week,config,now)
        except Problem:continue
        if week_target(config,now,reservations(state.get('active')),start,end)['target_minutes']:return candidate_week
    return None

def log_rejection(operation_id,attempt,draft,target,errors):
    logging.getLogger('uvicorn.error').warning('Week draft rejected %s',json.dumps({'operation_id':operation_id,'attempt':attempt,
        'target_minutes':target['target_minutes'],'task_minutes':[t.duration_minutes for t in draft.tasks],'errors':errors[:5]}))

async def prepare_week(app,row,account,read_context,*,initial=False,into=None):
    """Write, check and place one week, and store it as the preview in `into`, or in the planner state.

    A failure leaves every saved plan unchanged. A checkpoint replaces the row's planner state, so it is read again before saving.
    """
    def destination():return planner_state(row) if into is None else into
    state=destination();source=await read_context(account);now=app.state.clock()
    config=saved_config(state,periods=source.get('planning_defaults',{}).get('availability_periods'))
    outline=state.get('outline_candidate') if initial else state.get('outline_active')
    check_basis(state,source,outline,accepted=not initial)
    active=state['active'];body=row['pending']['body']
    if initial:
        week=first_open_week(state,outline,config,now);revise=False;feedback=None
        if not week:return False
    else:week=day_of(body['week_start']);revise=body.get('revision',False);feedback=body.get('feedback')
    if week_detail_locked(account,outline,week):
        if initial:return False
        raise premium_week()
    block=week_block(state,week)
    if block and not revise:raise Problem('This week is already accepted. Request a revision to review changes.',409,'week_already_accepted')
    if revise and not block:raise Problem('There is no accepted week to revise.',409,'week_not_found')
    start,end=week_interval(week,config,now)
    existing,replaced=revision_basis(active,block,now,config) if revise else (active,[])
    capacity=Capacity(config,now)
    pending=unfinished(existing,capacity)
    routines=routine_occurrences(outline,config,start,end,now,existing)
    target={'week_start':week.isoformat(),**week_target(config,now,reservations(existing),start,end)}
    scope=remaining_scope(outline,existing,routines,end)
    first=not state.get('week_blocks') and not state.get('month_blocks') and not (existing or {}).get('editable_tasks')
    diagnostics=[g['id'] for g in outline['gaps'] if g.get('status')=='unknown' and g.get('plan_impact')=='material' and g.get('resolution')=='diagnostic'] if first else []
    await set_stage(app,row,account['id'],'scheduling' if initial else 'writing')
    tasks=[t for t in (ensure_tasks(copy.deepcopy(existing)) if existing else []) if not t.get('removed')]
    brief=lambda t:{'task_id':t['id'],'title':t['title'],'milestone_key':t.get('milestone_key'),'status':t['status'],'estimated_minutes':t['estimated_minutes'],
        'difficulty':(t.get('self_rating') or {}).get('difficulty'),'confidence':(t.get('self_rating') or {}).get('confidence')}
    objectives=sorted(outline.get('weeks',[]),key=lambda w:w['week_start'])
    routine_minutes=sum(t['estimated_minutes'] for t in routines)
    context={'week_start':week.isoformat(),'start_date':start.isoformat(),'end_exclusive':end.isoformat(),'time_zone':config.time_zone,'goal':source.get('goal'),
        'objective':next((w for w in objectives if w['week_start']==week.isoformat()),None),
        'later_objectives':[w for w in objectives if w['week_start']>week.isoformat()][:6],
        'milestones':[m for m in outline['milestones'] if m['key'] in scope],'gaps':outline['gaps'],'remaining_scope':scope,
        'target_minutes':target['target_minutes'],'new_task_minutes':max(0,target['target_minutes']-routine_minutes),'carry_limit_minutes':carry_limit(config),
        'session_minutes':config.preferred_session_minutes,'diagnostics_needed':diagnostics,
        'routines':[{'title':t['title'],'minutes':t['estimated_minutes']} for t in routines],
        'progress':{'completed':[brief(t) for t in tasks if t['status']=='completed'][-40:],'in_progress':[brief(t) for t in tasks if t['status']=='in_progress'],
            'unfinished':[brief(t) for t in pending],'removed':[t['title'] for t in (ensure_tasks(copy.deepcopy(existing)) if existing else []) if t.get('removed')][-20:]},
        'last_week':last_week_summary(existing,week),'feedback':feedback,
        'settings':{k:getattr(config,k) for k in ('learning_focus','learning_notes','learning_topics','unfinished_default')}}
    errors=[];operation_id=row['pending']['id']
    for attempt in range(1,MAX_ATTEMPTS+1):
        if errors:await set_stage(app,row,account['id'],'correcting')
        draft=await app.state.model.generate(WeekDraft,WEEK_INSTRUCTIONS,{**context,'validation_errors':errors},max_tokens=PLAN_MAX_TOKENS)
        errors=check_week(draft,outline,config,existing,routines,pending,target,scope,feedback=feedback,diagnostics=diagnostics)
        if errors:
            log_rejection(operation_id,attempt,draft,target,errors);continue
        carryover=build_carryover(draft,pending,config)
        records=[task_record({**t.model_dump(mode='json'),'schedule':[]},str(uuid5(NAMESPACE_URL,operation_id+':week-task:'+t.key)),outline,week) for t in draft.tasks]
        placed,unplaced=arrange(config,now,existing,start,end,routines,carryover,records)
        errors=[f"Task '{t['generated_key']}' could not be scheduled: {t['estimated_minutes']} minutes do not fit the free study time left this week. Shorten or remove it." for t in unplaced]
        if not errors:break
        log_rejection(operation_id,attempt,draft,target,errors)
    else:raise Problem('The proposed week did not fit your schedule. Your accepted work is unchanged. '+errors[0],502,'week_validation')
    scheduled=sum(slot['duration_minutes'] for task in routines+placed for slot in task['schedule'])+sum(slot['duration_minutes'] for entry in carryover for slot in entry['schedule'])
    if scheduled<target['target_minutes']:
        code='lighter_workload' if feedback and feedback.get('workload')=='too_much' else 'remaining_scope'
        target['reasons'].append({'code':code,'message':f"This preview schedules {scheduled} minutes against {target['target_minutes']} available minutes. "+('Your workload feedback calls for a lighter week.' if code=='lighter_workload' else 'The remaining scoped tasks do not fill the target exactly; no filler work was added. Review workload, scope or deadline if needed.')})
    latest=await app.state.upstream.account(account['token'])
    if latest['id']!=account['id']:raise Problem('Your account changed while planning.',401,'session')
    fresh=await read_context(latest)
    if planning_source_changed(source,fresh):raise Problem('Your inputs, evaluation or availability changed during planning. Refresh and retry.',409,'inputs_changed')
    current={w['week_start']:w for w in outline.get('weeks',[])}
    changes=[{**change.model_dump(mode='json'),'previous':copy.deepcopy(current.get(change.week_start.isoformat()))} for change in draft.objective_changes]
    candidate={'id':str(uuid5(NAMESPACE_URL,operation_id+':week')),'week_start':week.isoformat(),'status':'preview',
        'outline_id':outline['id'],'outline_revision':outline['revision'],'start_date':start.isoformat(),'end_exclusive':end.isoformat(),
        'time_zone':config.time_zone,'basis':week_basis(outline,existing,week,pending),'schedule_hash':schedule_digest(config),
        'revision':(block.get('revision',1)+1 if block else 1),'replaces_block_id':block['id'] if block else None,'replaced_task_ids':replaced,
        'summary':draft.summary,'feedback':feedback,'target':target,'routine_task_ids':[t['id'] for t in routines],
        'tasks':routines+placed,'unplaced':[],'carryover':carryover,'objective_changes':changes,
        'created_at':stamp(),'generation':{'attempts':attempt,'prompt_version':'roadmap-week-v1'}}
    bounded_size(candidate,MAX_WEEK_BYTES,'This week is too large to review safely. Reduce the number or length of tasks and retry.')
    state=destination();state['config']=config.model_dump(mode='json');state['week_candidate']=candidate;state['week_notice']=None
    return True

def build_carryover(draft,pending,config):
    """One reviewed decision per unfinished task. A task the model skipped gets the user's default, never silence."""
    chosen={entry.task_id:entry for entry in draft.carryover}
    fallback='defer' if config.unfinished_default=='defer' else 'carry'
    result=[]
    for task in pending:
        entry=chosen.get(task['id'])
        action=entry.action if entry else fallback
        result.append({'task_id':task['id'],'title':task['title'],'milestone_key':task.get('milestone_key'),'status':task['status'],
            'estimated_minutes':task['estimated_minutes'],'action':action,'proposed_action':action,
            'minutes':entry.minutes if entry and entry.action=='split' else None,
            'reason':entry.reason if entry else 'Not finished last week, so it follows your setting for unfinished work.',
            'previous_schedule':copy.deepcopy(task.get('schedule',[])),'schedule':[],'adjusted':False})
    return result

def review_carryover(state,identifier,decisions,now,source=None):
    """Apply the user's own choices to the preview and place the week again. No model call."""
    candidate=state.get('week_candidate')
    if not candidate or candidate['id']!=identifier:raise Problem('The week preview changed. Reload and review it.',409,'week_changed')
    entries={entry['task_id']:entry for entry in candidate['carryover']}
    for decision in decisions:
        entry=entries.get(decision.task_id)
        if not entry:raise Problem('That task is not part of this preview.',404,'not_found')
        if decision.action=='split' and not entry.get('minutes'):raise Problem('This task has no proposed split. Carry, defer or drop it.',422,'validation')
        entry.update(action=decision.action,adjusted=False)
        if decision.action!=entry['proposed_action']:entry['reason']='Your choice.'
    config=saved_config(state,periods=((source or {}).get('planning_defaults') or {}).get('availability_periods'));week=day_of(candidate['week_start'])
    if schedule_digest(config)!=candidate['schedule_hash']:raise Problem('Your settings changed. Generate a fresh preview.',409,'week_stale')
    block=week_block(state,week)
    existing,_=revision_basis(state['active'],block,now,config) if block else (state['active'],[])
    if candidate['basis']!=week_basis(state['outline_candidate'] or state['outline_active'],existing,week,unfinished(existing,Capacity(config,now))):raise Problem('Your saved work changed. Generate a fresh preview.',409,'week_stale')
    start,end=week_interval(week,config,now)
    routines=[t for t in candidate['tasks'] if t['id'] in candidate.get('routine_task_ids',[])]
    drafts=[{**t,'schedule':[]} for t in [*candidate['tasks'],*candidate.get('unplaced',[])] if t['id'] not in candidate.get('routine_task_ids',[])]
    placed,unplaced=arrange(config,now,existing,start,end,routines,candidate['carryover'],drafts)
    candidate['tasks']=routines+placed;candidate['unplaced']=unplaced

def publish_outline(outline,active):
    """The active plan carrying this outline's milestones, keeping recorded outcomes, reached checkpoints and every task."""
    active=copy.deepcopy(active)
    if active:
        ensure_tasks(active)
        previous={m['key']:m for m in active['milestones']}
        milestones=copy.deepcopy(outline['milestones'])
        for m in milestones:
            old=previous.get(m['key'])
            if not old:continue
            outcome=copy.deepcopy(old.get('outcome') or m['outcome'])
            if outcome.get('demonstrated') and old.get('demonstrable_outcome')!=m.get('demonstrable_outcome'):
                outcome['definition_review_required']=True
                outcome.setdefault('previous_definition',old.get('demonstrable_outcome'))
            m['outcome']=outcome
            reached={c['key']:c for c in old.get('checkpoints',[])}
            for checkpoint in m.get('checkpoints',[]):
                prior=reached.get(checkpoint['key']) or {}
                if prior.get('reached_at') and prior.get('title')==checkpoint['title'] and str(prior.get('date'))==str(checkpoint['date']):
                    checkpoint['reached_at']=prior['reached_at']
        keys={m['key'] for m in milestones};milestones.extend(copy.deepcopy(m) for m in active['milestones'] if m['key'] not in keys)
    else:
        active={'schema_version':'roadmap-v2','id':outline['id'],'assignments':[],'editable_tasks':[],
            'created_at':stamp(),'base_active_id':None,'completed_at_generation':0,'revision_review':[],'changes':None}
        milestones=copy.deepcopy(outline['milestones'])
    for key in ('assessment_id','assessment_hash','assessment','config','config_hash','confirmations_hash','first_planning_week','summary','gaps','deadline_outcome','beyond_deadline','exclusions','generation'):
        active[key]=copy.deepcopy(outline[key])
    active['milestones']=milestones
    project_assignments(active)
    return active

def accept_week(state,source,identifier,now):
    outline=state.get('outline_active');check_basis(state,source,outline)
    candidate=state.get('week_candidate')
    if not candidate or candidate['id']!=identifier:raise Problem('The week preview changed. Reload and review it.',409,'week_changed')
    stale=lambda message:Problem(message+' Generate a fresh preview.',409,'week_stale')
    if candidate['outline_id']!=outline['id'] or candidate['outline_revision']!=outline['revision']:raise stale('Your outline changed.')
    config=saved_config(state,periods=(source.get('planning_defaults') or {}).get('availability_periods'));week=day_of(candidate['week_start'])
    if schedule_digest(config)!=candidate['schedule_hash']:raise stale('Your study settings changed.')
    block=week_block(state,week)
    if block and block['id']!=candidate.get('replaces_block_id'):raise Problem('This week is already accepted.',409,'week_already_accepted')
    if candidate.get('replaces_block_id') and not block:raise stale('The accepted week changed.')
    base,replaced=revision_basis(state['active'],block,now,config) if block else (state['active'],[])
    if replaced!=candidate.get('replaced_task_ids',[]):raise stale('A session in this week has passed or changed.')
    capacity=Capacity(config,now)
    pending=unfinished(base,capacity);moved={entry['task_id'] for entry in candidate['carryover']}
    if candidate['basis']!=week_basis(outline,base,week,pending) or moved!={t['id'] for t in pending}:raise stale('Your progress on this week or on its unfinished work changed.')
    if candidate.get('unplaced'):raise Problem('Some tasks no longer fit this week. Change a carry-over choice or generate a fresh preview.',409,'week_unplaced')
    start,end=week_interval(week,config,now)
    placer=Placer(config,now,reservations(base),start,end)
    proposed=[slot for task in candidate['tasks'] for slot in task['schedule']]+[slot for entry in candidate['carryover'] if entry['action'] in ('carry','split') for slot in entry['schedule']]
    for slot in sorted(proposed,key=lambda slot:(slot['date'],slot['start_time'])):
        day=day_of(slot['date']);low=to_minute(slot['start_time'])
        if not placer.accepts(day,low,slot['duration_minutes']):raise stale('A session has passed, its time was taken or it no longer fits your scheduling rules.')
        placer.take(day,low,slot['duration_minutes'])
    active=publish_outline(outline,base)
    active['config']=config.model_dump(mode='json');active['config_hash']=config_digest(config)
    at=stamp();tasks={task['id']:task for task in ensure_tasks(active)}
    for entry in candidate['carryover']:
        task=tasks[entry['task_id']];event={'at':at,'event':{'carry':'carried','split':'split','defer':'deferred','drop':'removed'}[entry['action']],
            'week_start':candidate['week_start'],'reason':entry['reason'],'previous_schedule':copy.deepcopy(task.get('schedule',[]))}
        if entry['action'] in ('carry','split'):
            task['schedule']=copy.deepcopy(entry['schedule']);task['anytime_date']=None;task.pop('deferred_week',None)
        elif entry['action']=='defer':
            task['schedule']=[];task['anytime_date']=None;task['deferred_week']=candidate['week_start']
        else:
            task['removed']=True;task['removal']={'at':at,'reason':entry['reason']}
        if entry['action']=='split':
            remaining=task['estimated_minutes']-entry['minutes']
            remainder=copy.deepcopy(task)
            remainder.update(id=str(uuid5(NAMESPACE_URL,task['id']+':remainder:'+candidate['id'])),
                title=task['title'],estimated_minutes=remaining,schedule=[],anytime_date=None,
                status='not_started',completed_at=None,evidence_note=None,notes=None,notes_updated_at=None,
                deferred_week=candidate['week_start'],history=[{'at':at,'event':'split_remainder','reason':entry['reason'],'previous_schedule':[]}])
            remainder['history'][0]['source_task_id']=task['id']
            remainder['original']=None
            remainder['prerequisites']=[task['id']]
            for dependent in active['editable_tasks']:
                if task['id'] in dependent.get('prerequisites',[]):
                    prior=copy.deepcopy(dependent['prerequisites'])
                    dependent['prerequisites']=[remainder['id'] if ident==task['id'] else ident for ident in prior]
                    dependent.setdefault('history',[]).append({'at':at,'event':'split_dependency','previous':{'prerequisites':prior},'reason':entry['reason']})
            event['estimated_minutes_before_split']=task['estimated_minutes']
            task['estimated_minutes']=entry['minutes']
            active['editable_tasks'].append(remainder)
        task.setdefault('history',[]).append(event)
    active['editable_tasks'].extend(copy.deepcopy(candidate['tasks']));project_assignments(active)
    mark_plan_membership_changes(state['active'],active)
    bounded_size(active,MAX_ACTIVE_BYTES,'This roadmap is too large to add another week safely. Your saved work remains available.')
    if candidate['objective_changes']:
        history=state.setdefault('outline_history',[])
        if len(history)>=100:raise Problem('This workspace reached its outline revision capacity.',413,'workspace_capacity')
        history.append(copy.deepcopy(outline))
        changes={change['week_start']:change for change in candidate['objective_changes']}
        outline['weeks']=[{**w,**{k:v for k,v in changes[w['week_start']].items() if k not in ('previous','reason')},'revised_reason':changes[w['week_start']]['reason']} if w['week_start'] in changes else w for w in outline.get('weeks',[])]
        outline['revision']+=1
        for accepted in state.get('week_blocks',[]):
            if accepted['week_start'] in changes:accepted['needs_review']=True
    state['active']=active
    record={k:copy.deepcopy(v) for k,v in candidate.items() if k not in ('tasks','basis','replaced_task_ids','unplaced','schedule_hash','routine_task_ids')}
    retained=[i for i in (block or {}).get('task_ids',[]) if i not in replaced]
    record.update(status='accepted',outline_revision=outline['revision'],task_ids=retained+[t['id'] for t in candidate['tasks']],accepted_at=at)
    if block:
        if len(state.get('week_history',[]))>=100:raise Problem('This workspace reached its retained week revision limit. Your saved work remains available.',413,'workspace_capacity')
        state.setdefault('week_history',[]).append(copy.deepcopy(block))
        state['week_blocks'][state['week_blocks'].index(block)]=record
    else:state.setdefault('week_blocks',[]).append(record)
    state['week_candidate']=None;state['week_notice']=None

def register_week_routes(app,context,mutate,worker):
    prefix='/api/v1/roadmaps/planner/weeks'
    @app.post(prefix+'/generate',status_code=202,response_model=OperationAccepted,
        responses={402:{'model':ErrorView,'description':'Generating later roadmap week details requires elo Premium.'}})
    async def generate(body:GenerateWeek,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id']);state=planner_state(row);now=app.state.clock()
        repeated=any(r['id']==str(body.mutation_id) for r in row['receipts']) or (row.get('pending') or {}).get('id')==str(body.mutation_id)
        if not repeated:
            source=await context(account);outline=state.get('outline_active')
            check_basis(state,source,outline)
            config=saved_config(state,periods=(source.get('planning_defaults') or {}).get('availability_periods'));block=week_block(state,body.week_start)
            week_interval(body.week_start,config,now)
            if week_detail_locked(account,outline,body.week_start):raise premium_week()
            if body.revision:
                if not block:raise Problem('There is no accepted week to revise.',409,'week_not_found')
            else:
                if block:raise Problem('This week is already accepted. Request a revision to review changes.',409,'week_already_accepted')
                open_week=planning(state,now,config,ignore_candidate=True)
                if not open_week or open_week['week_start']!=body.week_start.isoformat():
                    raise Problem('This week cannot be planned yet. Plan the current week first.',409,'week_not_open')
                if not open_week['available']:
                    raise Problem(f"Next week opens for planning on {open_week['plan_day']}, or as soon as every task this week is done.",409,'week_not_open')
            candidate_base,_=revision_basis(state['active'],block,now,config) if body.revision else (state['active'],[])
            candidate=state.get('week_candidate') or {}
            if candidate.get('week_start')==body.week_start.isoformat() and bool(candidate.get('replaces_block_id'))==body.revision and candidate.get('outline_id')==outline['id'] \
                    and candidate.get('basis')==week_basis(outline,candidate_base,body.week_start,unfinished(candidate_base,Capacity(config,now))) and candidate.get('schedule_hash')==schedule_digest(config) and candidate.get('feedback')==(body.feedback.model_dump(mode='json') if body.feedback else None):
                raise Problem('A preview for this week is already available to review.',409,'week_preview_exists')
        row=await thread(begin,app.state.store,account['id'],body,'week_generate',PLANNING_SECONDS,True)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    @app.post(prefix+'/{identifier}/carryover',response_model=Workspace)
    async def carryover(identifier:str,body:ReviewCarryover,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            review_carryover(planner_state(row),identifier,body.decisions,app.state.clock(),source);return row
        return await mutate(body,account,apply,operation='week.carryover:'+identifier)

    @app.post(prefix+'/{identifier}/accept',response_model=Workspace)
    async def accept(identifier:str,body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            accept_week(planner_state(row),source,identifier,app.state.clock());return row
        return await mutate(body,account,apply,operation='week.accept:'+identifier,mark_baseline=True)

    @app.post(prefix+'/{identifier}/discard',response_model=Workspace)
    async def discard(identifier:str,body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,_source):
            state=planner_state(row);candidate=state.get('week_candidate')
            if not candidate or candidate['id']!=identifier:raise Problem('The week preview changed. Reload before discarding it.',409,'week_changed')
            state['week_candidate']=None
            return row
        return await mutate(body,account,apply,operation='week.discard:'+identifier)
