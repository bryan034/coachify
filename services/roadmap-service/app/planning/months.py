"""Explicit calendar-month task previews for accepted outlines.

All scheduling uses local dates and the existing capacity implementation. Published
work remains canonical editable tasks, including removed task tombstones.
"""
import copy
import json
from datetime import date, timedelta
from uuid import NAMESPACE_URL, uuid5
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated, begin, digest, launch, operation_view, stamp
from app.planning.capacity import Capacity, to_clock, to_minute, week_of
from app.planning.generator import PLANNING_SECONDS, set_stage
from app.planning.milestone_membership import mark_plan_membership_changes
from app.planning.state import config_digest, planner_state, saved_config
from app.planning.tasks import ensure_tasks, project_assignments
from app.schemas.base import Mutation
from app.schemas.months import GenerateMonth, MonthDraft
from app.schemas.roadmap import OperationAccepted, PlannerConfig
from app.schemas.planner import Workspace

MONTH_INSTRUCTIONS = '''Write specific tasks for the requested calendar month only, advancing the supplied accepted milestones. Never alter milestone keys or outcomes. Each task has a short title of at most 19 words, detailed instructions, an observable completion outcome, a single date and time and a duration. Use only the supplied available windows and weekly remaining minutes. Routine occurrences are already allocated; do not repeat them. Respect existing work and milestone effort. Use a diagnostic in the first eligible week for each material unknown needing a diagnostic. Return no more than 100 tasks. Do not invent proficiency or guarantees.'''
MAX_MONTH_BYTES=128*1024
MAX_ACTIVE_BYTES=512*1024


def bounded_size(value, limit, message):
    if len(json.dumps(value,ensure_ascii=False,separators=(',',':'),default=str).encode('utf-8'))>limit:
        raise Problem(message,413,'month_capacity')


def month_interval(month, config, now):
    """Return the inclusive first and exclusive last local date of a block."""
    try:
        year, number = map(int, month.split('-'))
        first = date(year, number, 1)
        following = date(year + (number == 12), number % 12 + 1, 1)
    except (ValueError, OverflowError):
        raise Problem('Choose a valid calendar month.', 422, 'invalid_month') from None
    capacity = Capacity(config, now)
    if not capacity.target:
        raise Problem('Choose a target date before planning a month.', 409, 'generation_blocked')
    start = max(first, capacity.start_date, capacity.today)
    end = min(following, capacity.target + timedelta(days=1))
    if start >= end:
        raise Problem('This month has no remaining dates within the roadmap.', 409, 'month_outside_roadmap')
    return start, end


def reservations(plan):
    if not plan:return []
    return [dict(slot) for task in ensure_tasks(copy.deepcopy(plan)) if not task.get('removed') for slot in task.get('schedule', [])]


def revision_basis(active, block, now, config):
    """Release only untouched future generated work belonging to this block.

    Keep tombstones, notes, history and any prerequisite relationship intact.
    Returns an isolated scheduling basis and the IDs explicitly replaced.
    """
    if not active or not block:raise Problem('There is no accepted month to revise.',409,'month_not_found')
    plan=copy.deepcopy(active);tasks=ensure_tasks(plan);belong=set(block.get('task_ids',[]))
    linked={key for task in tasks for key in task.get('prerequisites',[])}
    capacity=Capacity(config,now);replaced=[]
    for task in tasks:
        if task['id'] not in belong or task.get('origin')!='generated' or task.get('removed'):
            continue
        if task.get('status')!='not_started' or task.get('overrides') or task.get('history') or task.get('evidence_note') or task.get('notes') or task.get('self_rating'):
            continue
        if task.get('prerequisites') or task['id'] in linked or not task.get('schedule'):
            continue
        if any(date.fromisoformat(str(s['date']))<capacity.today or
               (date.fromisoformat(str(s['date']))==capacity.today and to_minute(s['start_time'])<capacity.now_minute)
               for s in task['schedule']):
            continue
        replaced.append(task['id'])
    plan['editable_tasks']=[task for task in tasks if task['id'] not in set(replaced)]
    project_assignments(plan)
    return plan,replaced


def task_record(item, identifier, outline, *, routine_id=None):
    result = {'id':identifier,'title':item['title'],'instructions':item['instructions'],
        'completion_outcome':item['completion_outcome'],'estimated_minutes':item['duration_minutes'],
        'requirement_refs':[],'requirement_source_hash':outline['assessment_hash'],
        'requirement_source_id':outline['assessment_id'],'prerequisites':[],
        'milestone_key':item['milestone_key'], 'schedule':[{'date':str(item['date']),
        'start_time':item['start_time'],'duration_minutes':item['duration_minutes']}],
        'status':'not_started','completed_at':None,'evidence_note':None,'history':[],
        'removed':False,'removal':None,'definition_review_required':False,
        'generated_key':item['key'],'origin':'generated','overrides':[],
        'source_assignment':{'kind':item.get('kind','study'),'gap_id':item.get('gap_id'),'calendar_uses_title':True}}
    if routine_id:result['routine_rule_id']=routine_id
    return result


def future_routine_effort(outline, start, end, today, existing):
    """Reserve milestone effort promised to other unmaterialised occurrences."""
    known={t['id'] for t in ensure_tasks(copy.deepcopy(existing))} if existing else set()
    effort={}
    for rule in outline.get('routine_rules',[]):
        first=max(today,date.fromisoformat(str(rule['start_date'])))
        last=date.fromisoformat(str(rule['end_date']))
        day=first
        while day<=last:
            if not start<=day<end and day.weekday() in rule['weekdays']:
                ident=str(uuid5(NAMESPACE_URL,'roadmap:routine:'+rule['id']+':'+day.isoformat()))
                if ident not in known:effort[rule['milestone_key']]=effort.get(rule['milestone_key'],0)+rule['duration_minutes']
            day+=timedelta(days=1)
    return effort


def routine_occurrences(outline, start, end, now, existing):
    """Allocate every eligible occurrence or return an explicit conflict."""
    config=PlannerConfig.model_validate(outline['config'])
    slots=reservations(existing)
    known={t['id'] for t in ensure_tasks(copy.deepcopy(existing))} if existing else set()
    milestones={m['key'] for m in outline['milestones']}
    output=[]
    for rule in outline.get('routine_rules',[]):
        if rule['milestone_key'] not in milestones:
            raise Problem('A routine refers to a missing milestone.',409,'routine_milestone_missing')
        begin=date.fromisoformat(str(rule['start_date'])); last=date.fromisoformat(str(rule['end_date'])) if rule.get('end_date') else end-timedelta(days=1)
        weekdays=set(rule['weekdays']); day=max(start,begin)
        while day<end and day<=last:
            if day.weekday() not in weekdays:
                day+=timedelta(days=1);continue
            ident=str(uuid5(NAMESPACE_URL, 'roadmap:routine:'+rule['id']+':'+day.isoformat()))
            if ident in known:
                day+=timedelta(days=1);continue
            capacity=Capacity(config,now,slots); duration=rule['duration_minutes']
            windows=capacity.days.get(day,{'preferred':[],'backup':[]})
            choices=windows['preferred']+(windows['backup'] if config.use_backup else [])
            slot=next((low for low,high in choices if high-low>=duration and capacity.week_left(week_of(day))>=duration),None)
            if slot is None:
                raise Problem(f"Routine '{rule['activity']}' cannot fit on {day}. Adjust the routine or availability before generating this month.",409,'routine_conflict')
            topics=rule.get('topic_progression') or []
            index=sum(1 for n in range((day-begin).days+1) if (begin+timedelta(days=n)).weekday() in weekdays)-1
            title=' '.join(str(v).strip() for v in (rule['activity'],rule.get('difficulty'),topics[index%len(topics)] if topics else None) if v and str(v).strip())
            if len(title)>160 or len(title.split())>19:
                raise Problem('Shorten the routine activity, topic or difficulty to fit a task title.',422,'routine_title')
            item={'key':ident,'milestone_key':rule['milestone_key'],'title':title,
                'instructions':f"{rule['activity']}. Review your work and record one lesson.",
                'completion_outcome':'Save your work and a brief reflection.',
                'date':day.isoformat(),'start_time':to_clock(slot),'duration_minutes':duration}
            output.append(task_record(item,ident,outline,routine_id=rule['id']))
            output[-1]['source_assignment']['routine_user_wording']=rule.get('user_wording','')
            slots.extend(output[-1]['schedule']); known.add(ident);day+=timedelta(days=1)
    return output


def check_tasks(draft, outline, start, end, now, existing, routines, *, diagnostic_week=None):
    errors=[]; slots=reservations(existing)+[s for task in routines for s in task['schedule']]
    config=PlannerConfig.model_validate(outline['config'])
    keys=set(); milestones={m['key']:m for m in outline['milestones']};backup_tasks=[]
    saved=ensure_tasks(copy.deepcopy(existing)) if existing else []
    clock=Capacity(config,now)
    # A deleted occurrence remains a tombstone. Do not recreate the same work
    # on the same day merely under a fresh generated identifier.
    signatures={(t.get('milestone_key'),' '.join(t.get('title','').casefold().split()),str(slot['date']))
                for t in [*saved,*routines] for slot in t.get('schedule',[])}
    def overdue(task):
        if task.get('status')=='completed':return False
        for slot in task.get('schedule',[]):
            day=date.fromisoformat(str(slot['date']))
            if day<clock.today or (day==clock.today and to_minute(slot['start_time'])<clock.now_minute):return True
        day=task.get('anytime_date')
        return bool(day and date.fromisoformat(str(day))<clock.today)
    protected={(t.get('milestone_key'),' '.join(t.get('title','').casefold().split()))
               for t in saved if t.get('removed') or overdue(t)}
    for item in draft.tasks:
        label=f"Task '{item.key}'"
        if item.key in keys:errors.append(f'{label} repeats a key.')
        keys.add(item.key)
        signature=(item.milestone_key,' '.join(item.title.casefold().split()),item.date.isoformat())
        if signature in signatures:errors.append(f'{label} duplicates saved or proposed work on the same date.')
        elif signature[:2] in protected:errors.append(f'{label} duplicates removed or overdue work. Review that work explicitly.')
        signatures.add(signature)
        if item.milestone_key not in milestones:errors.append(f'{label} has an unknown milestone.')
        if not start<=item.date<end:errors.append(f'{label} is outside the requested month.');continue
        milestone=milestones.get(item.milestone_key)
        if item.gap_id and (not milestone or item.gap_id not in milestone.get('gap_ids',[]) or not any(g['id']==item.gap_id for g in outline['gaps'])):
            errors.append(f'{label} links a gap outside its milestone.')
        if item.kind=='diagnostic' and not item.gap_id:
            errors.append(f'{label} needs a specific gap for its diagnostic.')
        if milestone and not date.fromisoformat(str(milestone['projected_start']))<=item.date<=date.fromisoformat(str(milestone['projected_end'])):
            errors.append(f'{label} is outside its milestone dates.')
        capacity=Capacity(config,now,slots); low=to_minute(item.start_time);high=low+item.duration_minutes
        windows=capacity.days.get(item.date,{'preferred':[],'backup':[]})
        choices=windows['preferred']+(windows['backup'] if config.use_backup else [])
        if not any(a<=low and high<=b for a,b in choices):errors.append(f'{label} does not fit an available study window.')
        elif not any(a<=low and high<=b for a,b in windows['preferred']):backup_tasks.append(item)
        if item.duration_minutes>capacity.week_left(week_of(item.date)):errors.append(f'{label} exceeds the weekly budget.')
        slots.append({'date':item.date.isoformat(),'start_time':item.start_time,'duration_minutes':item.duration_minutes})
    # Respect preferred windows when the same task could be placed in one
    # within the same week and requested month.
    occupied=Capacity(config,now,slots)
    for item in backup_tasks:
        week=week_of(item.date)
        for offset in range(7):
            day=week+timedelta(days=offset)
            if start<=day<end and any(high-low>=item.duration_minutes for low,high in occupied.days.get(day,{}).get('preferred',[])):
                errors.append(f"Task '{item.key}' uses backup time while a preferred window is free in the same week.")
                break
    # A month cannot silently allocate more than each milestone's estimated effort.
    effort=future_routine_effort(outline,start,end,Capacity(config,now).today,existing)
    for task in (ensure_tasks(copy.deepcopy(existing)) if existing else []) + routines:
        if not task.get('removed'):
            # A revised outline estimates remaining work, so completions
            # recorded before it was created have already been accounted for.
            completed_at=task.get('completed_at')
            if task.get('status')=='completed' and completed_at and completed_at<outline['created_at']:
                continue
            key=task.get('milestone_key');effort[key]=effort.get(key,0)+task.get('estimated_minutes',0)
    for item in draft.tasks:effort[item.milestone_key]=effort.get(item.milestone_key,0)+item.duration_minutes
    for key,minutes in effort.items():
        if key in milestones and minutes>milestones[key]['estimated_minutes']:
            errors.append(f"Tasks for milestone '{key}' exceed its estimated effort.")
    if not draft.tasks and not routines:
        saved_in_month=any(not task.get('removed') and any(start<=date.fromisoformat(str(s['date']))<end for s in task.get('schedule',[])) for task in saved)
        remaining=any(date.fromisoformat(str(m['projected_start']))<end and date.fromisoformat(str(m['projected_end']))>=start
                      and effort.get(m['key'],0)<m['estimated_minutes'] for m in milestones.values())
        available=Capacity(config,now,slots).between(start,end-timedelta(days=1))>0
        if remaining and available and not saved_in_month:
            errors.append('The month has available time and unfinished milestones but no planned work. Add tasks or explain the scope in the outline.')
    if len(draft.tasks)+len(routines)>100:
        errors.append('The month has more than 100 tasks; reduce its scope or routine frequency.')
    if diagnostic_week is not None:
        week=diagnostic_week
        for gap in outline['gaps']:
            if gap.get('status')=='unknown' and gap.get('plan_impact')=='material' and gap.get('resolution')=='diagnostic':
                if not any(t.kind=='diagnostic' and t.gap_id==gap['id'] and t.duration_minutes<=30 and week<=t.date<=week+timedelta(days=6) for t in draft.tasks):
                    errors.append(f"Gap '{gap['id']}' needs a diagnostic of at most 30 minutes in the first planning week.")
    return errors


def available_windows(capacity,start,end):
    result=[];day=start
    while day<end:
        windows=capacity.days.get(day,{'preferred':[],'backup':[]})
        for kind in (('preferred','backup') if capacity.config.use_backup else ('preferred',)):
            for low,high in windows[kind]:result.append({'date':day.isoformat(),'start_time':to_clock(low),'end_time':to_clock(high),'kind':kind})
        day+=timedelta(days=1)
    return result


def check_basis(state, source, outline):
    if not outline or outline.get('status')!='accepted':raise Problem('Accept a milestone outline before generating tasks.',409,'outline_required')
    if not source.get('ready') or source.get('input_hash')!=outline['assessment_hash']:
        raise Problem('Your goal or evidence changed. Review the outline first.',409,'inputs_changed')
    if config_digest(saved_config(state))!=outline['config_hash']:
        raise Problem('Your settings changed. Review the outline first.',409,'settings_changed')
    if digest(state.get('confirmations',{}))!=outline['confirmations_hash']:
        raise Problem('Your confirmations changed. Review the outline first.',409,'inputs_changed')


async def prepare_month(app,row,account,read_context):
    state=planner_state(row);outline=state.get('outline_active');source=await read_context(account)
    check_basis(state,source,outline)
    month=row['pending']['body']['month']; active=state['active']; now=app.state.clock()
    revise=row['pending']['body'].get('revision',False)
    block=next((b for b in state.get('month_blocks',[]) if b['month']==month and b.get('status')=='accepted'),None)
    if block and not revise:raise Problem('This month is already accepted. Request a revision to review changes.',409,'month_already_accepted')
    if revise and not block:raise Problem('There is no accepted month to revise.',409,'month_not_found')
    config=PlannerConfig.model_validate(outline['config']);start,end=month_interval(month,config,now)
    existing,replaced=revision_basis(active,block,now,config) if revise else (active,[])
    routines=routine_occurrences(outline,start,end,now,existing)
    if len(routines)>100:raise Problem('The routines exceed the 100-task monthly limit. Reduce their frequency before generating.',409,'month_capacity')
    occupied=reservations(existing)+[s for task in routines for s in task['schedule']]
    capacity=Capacity(config,now,occupied)
    await set_stage(app,row,account['id'],'writing')
    progress=[{'id':t['id'],'title':t['title'],'milestone_key':t.get('milestone_key'),'status':t['status'],'removed':t.get('removed',False),'evidence_note':t.get('evidence_note')} for t in (ensure_tasks(copy.deepcopy(existing)) if existing else [])]
    context={'month':month,'start_date':start.isoformat(),'end_exclusive':end.isoformat(),'time_zone':config.time_zone,
        'milestones':[m for m in outline['milestones'] if date.fromisoformat(str(m['projected_start']))<end and date.fromisoformat(str(m['projected_end']))>=start],
        'gaps':outline['gaps'],'routines':routines,'progress':progress,'windows':available_windows(capacity,start,end),
        'weeks':[{'week_start':w['week_start'],'remaining_minutes':capacity.week_left(date.fromisoformat(w['week_start']))} for w in capacity.weeks()]}
    errors=[]
    for attempt in range(1,4):
        if errors:await set_stage(app,row,account['id'],'correcting')
        draft=await app.state.model.generate(MonthDraft,MONTH_INSTRUCTIONS,{**context,'validation_errors':errors},max_tokens=24000)
        # A user returning after a gap reviews the current month, without
        # automatically backfilling the original week.
        diagnostic_week=next((week_of(date.fromisoformat(w['date'])) for w in context['windows']),week_of(start)) if not state.get('month_blocks') else None
        errors=check_tasks(draft,outline,start,end,now,existing,routines,diagnostic_week=diagnostic_week)
        if not errors:break
    else:raise Problem('The proposed month did not fit your schedule. Your accepted work is unchanged. '+errors[0],502,'month_validation')
    latest=await app.state.upstream.account(account['token'])
    if latest['id']!=account['id']:raise Problem('Your account changed while planning.',401,'session')
    fresh=await read_context(latest)
    if fresh.get('input_hash')!=source.get('input_hash'):raise Problem('Your inputs changed during planning. Refresh and retry.',409,'inputs_changed')
    operation_id=row['pending']['id']
    tasks=routines+[task_record(t.model_dump(mode='json'),str(uuid5(NAMESPACE_URL,operation_id+':month-task:'+t.key)),outline) for t in draft.tasks]
    bounded_size(tasks,MAX_MONTH_BYTES,'This month is too large to review safely. Reduce the number or length of tasks and retry.')
    # Checkpointing replaces the row's nested data with a persisted copy.
    state=planner_state(row)
    state['month_candidate']={'id':str(uuid5(NAMESPACE_URL,operation_id+':month')),'month':month,'status':'preview',
        'outline_id':outline['id'],'outline_revision':outline['revision'],'start_date':start.isoformat(),
        'end_exclusive':end.isoformat(),'time_zone':config.time_zone,'basis':digest(active),
        'revision':(block.get('revision',1)+1 if block else 1),'replaces_block_id':block['id'] if block else None,
        'replaced_task_ids':replaced,
        'config_hash':outline['config_hash'],'assessment_hash':outline['assessment_hash'],
        'tasks':tasks,'created_at':stamp(),'generation':{'attempts':attempt,'prompt_version':'roadmap-month-v1'}}


def accept_month(state,source,identifier,now):
    outline=state.get('outline_active');check_basis(state,source,outline)
    candidate=state.get('month_candidate')
    if not candidate or candidate['id']!=identifier:raise Problem('The month preview changed. Reload and review it.',409,'month_changed')
    if candidate['outline_id']!=outline['id'] or candidate['outline_revision']!=outline['revision'] or candidate['basis']!=digest(state['active']):
        raise Problem('Your outline or progress changed. Generate a fresh month preview.',409,'month_stale')
    block=next((b for b in state.get('month_blocks',[]) if b['month']==candidate['month'] and b.get('status')=='accepted'),None)
    if block and block['id']!=candidate.get('replaces_block_id'):
        raise Problem('This month is already accepted.',409,'month_already_accepted')
    if candidate.get('replaces_block_id') and not block:raise Problem('The accepted month changed.',409,'month_stale')
    config=PlannerConfig.model_validate(outline['config'])
    base,replaced=revision_basis(state['active'],block,now,config) if block else (state['active'],[])
    if replaced!=candidate.get('replaced_task_ids',[]):
        raise Problem('The month changed or a session has passed. Generate a fresh preview.',409,'month_stale')
    capacity=Capacity(config,now,reservations(base))
    for task in candidate['tasks']:
        slot=task['schedule'][0];day=date.fromisoformat(slot['date']);low=to_minute(slot['start_time']);high=low+slot['duration_minutes']
        windows=capacity.days.get(day,{'preferred':[],'backup':[]});eligible=windows['preferred']+(windows['backup'] if config.use_backup else [])
        if not any(a<=low and high<=b for a,b in eligible) or slot['duration_minutes']>capacity.week_left(week_of(day)):
            raise Problem('The schedule changed or a session has passed. Generate a fresh preview.',409,'month_stale')
        capacity=Capacity(config,now,[*reservations(base),*[s for t in candidate['tasks'][:candidate['tasks'].index(task)+1] for s in t['schedule']]])
    active=copy.deepcopy(base)
    if active:
        ensure_tasks(active)
        previous={m['key']:m for m in active['milestones']}
        milestones=copy.deepcopy(outline['milestones'])
        for m in milestones:
            if m['key'] in previous:
                old=previous[m['key']]
                outcome=copy.deepcopy(old.get('outcome') or m['outcome'])
                if outcome.get('demonstrated') and old.get('demonstrable_outcome')!=m.get('demonstrable_outcome'):
                    outcome['definition_review_required']=True
                    outcome.setdefault('previous_definition',old.get('demonstrable_outcome'))
                m['outcome']=outcome
                old_checkpoints={c['key']:c for c in old.get('checkpoints',[])}
                for checkpoint in m.get('checkpoints',[]):
                    prior=old_checkpoints.get(checkpoint['key']) or {}
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
    active['editable_tasks'].extend(copy.deepcopy(candidate['tasks']));project_assignments(active)
    mark_plan_membership_changes(state['active'],active)
    bounded_size(active,MAX_ACTIVE_BYTES,'This roadmap is too large to add another month safely. Your saved work remains available.')
    state['active']=active
    new_block={k:copy.deepcopy(v) for k,v in candidate.items() if k not in ('tasks','basis','replaced_task_ids')}
    retained=[i for i in (block or {}).get('task_ids',[]) if i not in replaced]
    new_block.update(status='accepted',task_ids=retained+[t['id'] for t in candidate['tasks']],accepted_at=stamp())
    if block:
        if len(state.get('month_history',[]))>=100:
            raise Problem('This workspace reached its retained month revision limit. Your saved work remains available.',413,'workspace_capacity')
        state.setdefault('month_history',[]).append(copy.deepcopy(block))
        state['month_blocks'][state['month_blocks'].index(block)]=new_block
    else:state.setdefault('month_blocks',[]).append(new_block)
    state['month_candidate']=None


def register_month_routes(app,context,mutate,worker):
    prefix='/api/v1/roadmaps/planner/months'
    @app.post(prefix+'/generate',status_code=202,response_model=OperationAccepted)
    async def generate(body:GenerateMonth,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id']);state=planner_state(row)
        repeated=any(r['id']==str(body.mutation_id) for r in row['receipts']) or (row.get('pending') or {}).get('id')==str(body.mutation_id)
        if not repeated:
            check_basis(state,await context(account),state.get('outline_active'))
            block=next((b for b in state.get('month_blocks',[]) if b['month']==body.month and b.get('status')=='accepted'),None)
            if block and not body.revision:raise Problem('This month is already accepted. Request a revision to review changes.',409,'month_already_accepted')
            if body.revision and not block:raise Problem('There is no accepted month to revise.',409,'month_not_found')
            candidate=state.get('month_candidate') or {}
            if (candidate.get('month')==body.month and bool(candidate.get('replaces_block_id'))==body.revision and candidate.get('outline_id')==state['outline_active']['id']
                    and candidate.get('basis')==digest(state['active'])):
                raise Problem('A preview for this month is already available to review.',409,'month_preview_exists')
            month_interval(body.month,PlannerConfig.model_validate(state['outline_active']['config']),app.state.clock())
        row=await thread(begin,app.state.store,account['id'],body,'month_generate',PLANNING_SECONDS,True)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    @app.post(prefix+'/{identifier}/accept',response_model=Workspace)
    async def accept(identifier:str,body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            accept_month(planner_state(row),source,identifier,app.state.clock());return row
        return await mutate(body,account,apply,operation='month.accept:'+identifier,mark_baseline=True)

    @app.post(prefix+'/{identifier}/discard',response_model=Workspace)
    async def discard(identifier:str,body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row);candidate=state.get('month_candidate')
            if not candidate or candidate['id']!=identifier:
                raise Problem('The month preview changed. Reload before discarding it.',409,'month_changed')
            state['month_candidate']=None
            return row
        return await mutate(body,account,apply,operation='month.discard:'+identifier)
