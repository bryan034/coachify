"""LLM work for the timed roadmap: settings chat, plan writing and the bounded validation retry."""
import copy
from datetime import date, timedelta
from uuid import NAMESPACE_URL, uuid5
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, digest, stamp
from app.planning.capacity import Capacity, blackout_problem, normalized, to_clock, week_of
from app.planning.checkin import next_week_workload, recap
from app.planning.metrics import detail_needed, included_scheduled, milestone_totals, pace, progress, week_target, window_weeks
from app.planning.proposals import build_proposal, edit_proposal, overflow_warning
from app.planning.schedule import add_event, changed, day_of, is_current_schema, placed, plan_capacity, private_copy, task_span
from app.planning.state import ASSESSMENT_FIELDS, completed_sessions, config_digest, finished_records, planner_state, prior_work, saved_config
from app.planning.validator import check_assignments, check_repetition, check_window_coverage, validate_outline, validate_plan
from app.schemas.roadmap import ChatTurn, PlanDraft, PlanOutline, PlannerConfig, TaskRevision, WindowDetail

MAX_ATTEMPTS=3
PLAN_MAX_TOKENS=24000
DETAIL_MAX_TOKENS=12000
# Assessment polling (90s) plus up to three 55-second model calls for each of the two stages, and their source checks.
PLANNING_SECONDS=450
PROMPT_VERSION='roadmap-plan-v3'

SHARED_RULES='''You own the learning plan: skill gaps, priorities, prerequisite order, milestones, effort estimates, assignments and coaching text. The backend owns dates, capacity, progress totals and finish-date projections, and rejects anything that does not fit. Never assert that a schedule fits, never state hours available or a finish date, and never promise readiness or employment.
prior_completed_work is the user's finished and skipped work, with outcomes, linked skills, dates and feedback. Trust completion for planning: do not repeat it. A refresher or a harder application is allowed only when you justify it in refresher_reason. feedback of too_easy or too_hard should change the difficulty of what follows.'''

OUTLINE_INSTRUCTIONS='''You write the outline of a personal study roadmap towards the user's career goal.
'''+SHARED_RULES+'''

Gaps. assessment holds the evidence-linked comparison of the user's goal with their skills.
- A requirement whose outcome has a confirmed_shortfall component is status confirmed_gap. uncertain or partial outcomes are status unknown: missing proof is not a shortfall. Supported outcomes and members of satisfied "any" groups are not gaps. assessment.constraints are non-learning conditions that study cannot resolve; never list them as gaps.
- A gap from the assessment has source "stated" and its requirement_ref. A requirement you infer about the role yourself has source "inferred", no requirement_ref, an inference_reason and status unknown.
- plan_impact is "material" when the answer would change what the user should study or in what order. A material unknown needs resolution "diagnostic" (a task of 30 minutes or less in the detail stage, with gap_id set) or "confirm_experience" (a short confirmation_question). confirmations are the user's self-reported answers: use them and do not ask again.
- Every id in assessment.priorities must appear in a milestone's gap_ids or in beyond_deadline.

Milestones. estimated_minutes is the effort still remaining. Each needs a projected_start and projected_end inside the runway, prerequisites finishing first, and a demonstrable_outcome the user could show another person. For any date range, the milestones wholly inside it must fit planned_capacity for that range.

The target date is the end of the dated roadmap; never move it. No milestone may end after it. If the goal needs more than the planned capacity, prioritise prerequisites and the work that most directly supports the goal, put what remains in beyond_deadline with estimated_minutes, its key and its dependencies (milestone keys or other beyond_deadline keys), and say plainly in deadline_outcome what the user can reasonably achieve by the target. fits_in_runway is false exactly when beyond_deadline is not empty.

Outline. Write exactly one row for every week in planned_capacity: week_start, a short theme, the milestone_keys it advances, target_minutes no higher than that week's planned_minutes, and a concrete expected_output. A week with zero planned_minutes has target_minutes 0. The targets must add up to at least the milestones' effort. Keep rows brief so that a year-long roadmap stays within the output limit.

An exclusion needs an exact quote from user_message. If validation_errors is present, your previous_output was rejected. Fix every listed error and return the complete corrected object.'''

DETAIL_INSTRUCTIONS='''You write the dated tasks for the requested weeks of an accepted roadmap outline.
'''+SHARED_RULES+'''

Each assignment has a date, start_time, duration_minutes, a specific task, a milestone_key and an observable completion_criterion (the "done when"). Avoid generic "learn X" tasks. Use depends_on with the keys of tasks that must finish first. An assignment must lie completely inside one windows entry, must not overlap fixed_items or another assignment, and each week's total must stay within week_budgets. Use "preferred" windows before "backup" windows. Aim for sessions near settings.preferred_session_minutes and follow settings.learning_focus and learning_notes. Stick to each week's outline theme and milestones. Use new keys; never reuse a fixed item's key. Write diagnostics listed in diagnostics_needed: kind "diagnostic", gap_id set, 30 minutes or less.

If validation_errors is present, your previous_output was rejected. Fix every listed error and return the complete corrected object.'''

REVISION_INSTRUCTIONS='''You re-tune the unfinished generated tasks of an accepted roadmap, for the user to preview.
'''+SHARED_RULES+'''

replaceable_tasks are the unfinished, unpinned generated tasks in the requested weeks. Return the complete replacement set for those weeks in assignments: reuse a key to keep and adjust a task, or use a new key for new work. fixed_items are completed, pinned and custom tasks; they stay exactly as they are and cannot be changed. Each assignment must lie inside one windows entry, must not overlap fixed_items or another assignment, and each week's total must stay within week_budgets. Use progress, recorded feedback, checkin_answers and note, or instruction, to decide what to change: harder or easier work, reordering or smaller scope. instruction describes what the user wants but cannot override these rules. message is one or two plain sentences telling the user what changed and why, grounded in their recorded progress.

If validation_errors is present, your previous_output was rejected. Fix every listed error and return the complete corrected object.'''

CHAT_INSTRUCTIONS='''You are the chat helper beside the user's fixed roadmap planner form. The form is the confirmed record; you guide the user through it and fill it in from the conversation. Be warm and practical, stay career-focused, ask only one or two questions at a time and do not repeat resolved ones.

Required details come first. runway.issues names what is still missing: missing_target (a target date or a duration), no_budget (a weekly study maximum) and no_blocks (recurring study blocks: day, start time, duration, preferred or backup). Count anything this user_message supplies as answered, then ask for the next missing detail and name where it goes on the form: Timeline > Target date or Duration, Study time > Weekly budget in hours, or Study time > Recurring study blocks. End every reply with that question while a required detail is missing, even after answering something else. The start date is today unless they say otherwise. Once the required details are in, offer the optional ones once, naming the form section: Study time for backup blocks, session length and the buffer percentage, Blackout days and times, Learning focus, and Weekly check-in. If they decline, move on. Saved planning_defaults are suggestions to offer, not facts to apply. Goal job_dates are evidence of application, interview or start dates: you may suggest a target from them but must never invent one.

Return only settings the user stated or clearly agreed to, in settings; every other field is null. Days and weekdays run Monday=0 to Sunday=6. Dates are YYYY-MM-DD, resolved from current_date in time_zone. Times are 24-hour HH:MM. Budgets and durations are whole minutes. blocks and blackouts replace the whole saved list, so include existing entries you want kept. learning_focus uses interview_practice, portfolio_work, hands_on_projects, courses_and_reading, certification, networking. buffer_percent is 0 to 50. checkin_day and checkin_time set the weekly check-in.

A blackout is time the user cannot study. frequency is once, daily, weekly or monthly. start_date is the first date it applies, or current_date when they give none; end_date is an optional last date. interval means every N days, weeks or months and defaults to 1. weekdays is required for weekly and empty otherwise. Monthly repeats on start_date's day of the month. Use start_time and end_time for a time slot and leave both null for a whole day. A slot must end after it starts on the same day, so an overnight blackout needs two entries.

Never compute available hours, finish dates or claim the schedule fits: the page shows the calculated numbers. You cannot start generation or apply a plan. When the required details are in, tell the user to review the form and press Generate.

When current_plan is present the user has an accepted roadmap. Settings they ask to change prepare an Edit plan preview. Set revision_instruction to a short, precise description only when they ask to change what unfinished generated tasks say or do; that prepares a task preview. Nothing applies until the user accepts it, and you must say so. Do not set revision_instruction when the user only asks a question. Completed, pinned and custom tasks cannot be changed by you: the user can Complete, Skip, Move, Pin or add custom tasks on the page. Missed tasks move automatically by fixed rules, and the target date only changes if the user accepts a change. Deferred scope stays outside the dated schedule until they accept a scope or date preview. Factual skill corrections belong in Skills Profile, so point the user there.'''

def compact_plan(plan):
    if not plan:return None
    fields=('summary','first_planning_week','gaps','milestones','deadline_outcome','beyond_deadline','deferred_scope','exclusions')
    return {**{k:plan.get(k) for k in fields if k in plan},'scheduled':[{k:a.get(k) for k in ('key','milestone_key','date','start_time','duration_minutes','task','pinned','origin')} for a in plan['assignments'] if a['status']=='scheduled']}

def apply_settings(config,patch,today):
    """Merge a chat patch. An invalid patch changes nothing and returns the reason to show."""
    values=patch.model_dump(mode='json',exclude_none=True)
    if not values:return config,None
    merged=config.model_dump(mode='json');merged.update(values)
    if 'target_date' in values and 'duration' not in values:merged['duration']=None
    try:updated=PlannerConfig.model_validate(merged)
    except ValidationError as error:
        fields=sorted({str(e['loc'][0]) for e in error.errors() if e['loc']})
        named=', '.join(f.replace('_',' ') for f in fields) or 'the proposed values'
        return config,f'I couldn’t apply that change because of {named}, so your settings are unchanged.'
    if any(blackout_problem(rule) for rule in updated.blackouts):
        return config,'I couldn’t apply that change because of blackouts, so your settings are unchanged.'
    return normalized(updated,today),None

async def write_stage(model,schema,instructions,context,check,before_retry,max_tokens):
    """Call the model until its output passes validation, at most MAX_ATTEMPTS times in total."""
    errors=[];previous=None
    for attempt in range(1,MAX_ATTEMPTS+1):
        request={**context,'attempt':attempt}
        if errors:
            await before_retry()
            request.update(validation_errors=errors,previous_output=previous)
        draft=await model.generate(schema,instructions,request,max_tokens=max_tokens)
        errors=check(draft)
        if not errors:return draft,attempt
        previous=draft.model_dump(mode='json')
    examples=' '.join(e['message'] for e in errors[:3])
    raise Problem(f'We could not produce a plan that fits your schedule after {MAX_ATTEMPTS} attempts. Your last valid plan is unchanged. {examples}'[:1500],502,'plan_validation')

def plan_changes(previous,assignments,milestones):
    """What a preview changes relative to the active plan, shown before the user accepts it."""
    if not previous:return None
    slot=lambda a:(str(a.get('date')),a.get('start_time'),a['duration_minutes'])
    before={a['key']:a for a in previous['assignments'] if a['status']=='scheduled'}
    after={a['key']:a for a in assignments if a['status']=='scheduled'}
    old={m['key']:m for m in previous['milestones']};new={m['key']:m for m in milestones}
    window=lambda m:(str(m['projected_start']),str(m['projected_end']))
    return {'completed_preserved':sum(a['status']=='completed' for a in assignments),
        'assignments_added':[after[k]['task'] for k in after if k not in before],
        'assignments_removed':[before[k]['task'] for k in before if k not in after],
        'assignments_moved':[after[k]['task'] for k in after if k in before and slot(after[k])!=slot(before[k])],
        'milestones_added':[new[k]['title'] for k in new if k not in old],
        'milestones_removed':[old[k]['title'] for k in old if k not in new],
        'milestones_moved':[new[k]['title'] for k in new if k in old and window(new[k])!=window(old[k])]}

def new_task(item,identifier):
    """A saved generated task from a validated model assignment."""
    day=str(item['date'])
    return {**item,'id':identifier,'origin':'generated','week_start':week_of(date.fromisoformat(day)).isoformat(),'status':'scheduled','pinned':False,'count_hours':True,'note':None,'evidence_note':None,
        'feedback':None,'completed_at':None,'auto_moves':0,'manual_moves':0,'action_needed':None,'backlog_reason':None,'removed_reason':None,'baseline':f"{day} {item['start_time']}",'revision':0,'history':[]}
def carried_custom(active,capacity):
    """Future custom tasks stay the user's when a new roadmap replaces this one. AI work plans around them."""
    if not is_current_schema(active):return []
    rows=[]
    for task in active['assignments']:
        if task['origin']!='custom' or task['status'] not in ('scheduled','backlog'):continue
        late=task['status']=='scheduled' and (day_of(task)<capacity.today or (capacity.target and day_of(task)>capacity.target))
        rows.append({**copy.deepcopy(task),'milestone_key':None,'action_needed':None,
            **({'status':'backlog','date':None,'start_time':None,'backlog_reason':'Carried over from your previous roadmap. Choose a time for it.'} if late else {})})
    return rows
def build_plan(outline,detail,assessment,config,first_week,operation_id,attempts,active,confirmations,carried):
    data=outline.model_dump(mode='json')
    milestones=[{**m,'id':m['key'],'outcome':{'demonstrated':False},'completion':None} for m in data['milestones']]
    tasks=[new_task(a,str(uuid5(NAMESPACE_URL,operation_id+':assignment:'+a['key']))) for a in detail.model_dump(mode='json')['assignments']]
    deferred=[{'id':f'deferred-{b["key"] or index}','key':b['key'] or f'deferred-{index}','title':b['title'],'gap_ids':b['gap_ids'],'reason':b['reason'],'estimated_minutes':b['estimated_minutes'],'dependencies':b['dependencies'],'source_milestone':None}
        for index,b in enumerate(data['beyond_deadline'],1)]
    assignments=[*carried,*tasks]
    return {'schema_version':'roadmap-v3','id':str(uuid5(NAMESPACE_URL,operation_id+':roadmap')),'revision':0,'progress_revision':0,
        'assessment_id':assessment['id'],'assessment_hash':assessment['input_hash'],'assessment':{k:assessment.get(k) for k in ASSESSMENT_FIELDS},
        'config':config.model_dump(mode='json'),'config_hash':config_digest(config),'confirmations_hash':digest(confirmations),
        'base_active_id':(active or {}).get('id'),'base_progress_revision':(active or {}).get('progress_revision',0) if active else None,'created_at':stamp(),'accepted_at':None,'first_planning_week':first_week.isoformat(),
        'summary':data['summary'],'gaps':data['gaps'],'milestones':milestones,'outline':data['outline'],'assignments':assignments,'deferred_scope':deferred,
        'deadline_outcome':data['deadline_outcome'],'exclusions':data['exclusions'],'week_states':{},'checkins':{},'events':[],
        'changes':plan_changes(active,assignments,milestones),'generation':{'prompt_version':PROMPT_VERSION,'attempts':attempts,'stages':['outline','detail']}}

async def set_stage(app,row,owner,stage):
    row['pending']['stage']=stage
    seconds=630 if getattr(app.state.model,'local',False) else PLANNING_SECONDS+30
    await thread(app.state.store.checkpoint,owner,row,seconds)

def fixed_items(tasks):
    """Compact occupied time a generation stage must plan around."""
    return [{'key':t['key'],'date':str(t['date']),'start_time':t['start_time'],'duration_minutes':t['duration_minutes'],'kind':t.get('origin','generated')} for t in tasks if t.get('date') and t.get('start_time')]
def window_context(capacity,weeks,budgets):
    return {'requested_weeks':[w.isoformat() for w in weeks],'week_budgets':{w.isoformat():budgets[w] for w in weeks},
        'windows':[window for w in weeks for window in capacity.windows_for_week(w)]}

async def prepare_plan(app,row,account,assess,read_context,*,config=None,instruction=None,user_message=None):
    """Compare skills, write and validate a new roadmap in two stages, and store it as the candidate.

    The row is only changed after both stages validate, so a failure keeps every earlier plan and an
    incomplete generation is never presented for acceptance.
    """
    owner=account['id'];state=planner_state(row)
    config=config or saved_config(state)
    pending=row['pending'];operation_id=pending['id']
    await set_stage(app,row,owner,'assessing')
    result=await assess(account,operation_id,pending['body'].get('allow_partial_assessment',False))
    source=await read_context(account)
    if not source['ready'] or source.get('input_hash')!=result['input_hash']:raise Problem('Your selected inputs changed. Refresh before planning.',409,'inputs_changed')
    await set_stage(app,row,owner,'writing')
    state=planner_state(row)
    active=state['active'];confirmations=state['confirmations'];now=app.state.clock()
    completed=completed_sessions(active)
    capacity=Capacity(config,now,completed)
    config=normalized(config,capacity.today)
    capacity=Capacity(config,now,completed)
    report=capacity.report(allow_past_start=bool(active))
    if not report['can_generate']:raise Problem(' '.join(i['message'] for i in report['issues']),409,'generation_blocked')
    first_week=date.fromisoformat(report['first_planning_week'])
    prior=prior_work(state)
    carried=carried_custom(active,capacity)
    local=now.astimezone(capacity.zone)
    shared={'current_date':capacity.today.isoformat(),'current_time':to_clock(local.hour*60+local.minute),'time_zone':config.time_zone,'target_date':capacity.target.isoformat(),
        'goal':source['goal'],'settings':config.model_dump(mode='json'),'prior_completed_work':prior,'confirmations':confirmations,'instruction':instruction,'user_message':user_message}
    corrected=lambda:set_stage(app,row,owner,'correcting')
    outline_check=lambda draft:validate_outline(draft,capacity,result,confirmations=confirmations,instruction=user_message)
    outline,outline_attempts=await write_stage(app.state.model,PlanOutline,OUTLINE_INSTRUCTIONS,{**shared,'stage':'outline','assessment':{k:result.get(k) for k in ASSESSMENT_FIELDS},
        'runway':{k:report[k] for k in ('calendar','study','budget')},
        'planned_capacity':[{k:w[k] for k in ('week_start','planned_minutes','partial')} for w in report['weeks']]},outline_check,corrected,PLAN_MAX_TOKENS)
    await set_stage(app,row,owner,'detailing')
    weeks=window_weeks(capacity)
    occupied=[t for t in carried if t['status']=='scheduled']
    used={week:sum(t['duration_minutes'] for t in occupied if week_of(day_of(t))==week and t.get('count_hours',True)) for week in weeks}
    budgets={week:max(0,capacity.week_minutes(week)[1]-used[week]) for week in weeks}
    fixed=[*completed,*occupied]
    def detail_check(detail):
        combined=PlanDraft.model_validate({**outline.model_dump(mode='json'),'assignments':detail.model_dump(mode='json')['assignments']})
        return [*validate_plan(combined,capacity,result,first_week,completed=fixed,retained_milestones=(),confirmations=confirmations,instruction=user_message,weeks=weeks,prior=prior),
            *check_window_coverage(combined,weeks,budgets,sum(m.estimated_minutes for m in outline.milestones))]
    outline_view=[row_ for row_ in outline.model_dump(mode='json')['outline'] if date.fromisoformat(row_['week_start']) in weeks]
    needed=[g.id for g in outline.gaps if g.status=='unknown' and g.plan_impact=='material' and g.resolution=='diagnostic' and g.id not in confirmations]
    detail,detail_attempts=await write_stage(app.state.model,WindowDetail,DETAIL_INSTRUCTIONS,{**shared,'stage':'detail','milestones':outline.model_dump(mode='json')['milestones'],'outline':outline_view,
        'diagnostics_needed':needed,'fixed_items':fixed_items(fixed),**window_context(capacity,weeks,budgets)},detail_check,corrected,DETAIL_MAX_TOKENS)
    latest=await app.state.upstream.account(account['token'])
    if latest['id']!=owner:raise Problem('Your account changed while preparing this plan.',401,'session')
    fresh=await read_context(latest)
    if fresh.get('input_hash')!=source['input_hash']:raise Problem('Your evidence or goal changed while preparing this plan. Retry with the latest inputs.',409,'inputs_changed')
    state=planner_state(row)
    state['config']=config.model_dump(mode='json')
    state['candidate']=build_plan(outline,detail,result,config,first_week,operation_id,outline_attempts+detail_attempts,active,confirmations,carried)
    row['assessment']={k:result.get(k) for k in ASSESSMENT_FIELDS}

def detail_context(plan,capacity,now):
    return {'current_date':capacity.today.isoformat(),'time_zone':capacity.config.time_zone,'target_date':capacity.target.isoformat(),'settings':plan['config'],
        'milestones':plan['milestones'],'gaps':plan['gaps'],'progress':progress(plan),'pace':{k:v for k,v in pace(plan,now).items() if k!='recent'}}
def validate_detail(output,plan,capacity,weeks,budgets,fixed):
    keys={m['key'] for m in plan['milestones']}
    errors=check_assignments(output,capacity,fixed,weeks[0],keys,weeks=weeks,budgets=budgets)
    errors.extend(check_repetition(output,finished_records(plan)))
    return errors

async def fill_window(app,row,account):
    """Rolling detail: fill outline-only weeks in the two-week window, within accepted scope and workload.

    It runs without a preview because it adds tasks only and never changes an existing one.
    """
    owner=account['id'];state=planner_state(row);plan=state['active'];now=app.state.clock()
    if not is_current_schema(plan):raise Problem('This roadmap can’t be detailed. Start a new roadmap.',409,'legacy_plan')
    weeks=detail_needed(plan,now)
    if not weeks:return
    await set_stage(app,row,owner,'rolling')
    plan=planner_state(row)['active'];capacity=plan_capacity(plan,now)
    budgets={week:max(0,week_target(plan,week,capacity)-included_scheduled(plan,week)) for week in weeks}
    fixed=[t for t in plan['assignments'] if t.get('date') and t.get('start_time') and t['status'] in ('scheduled','completed')]
    outline=[r for r in plan.get('outline',[]) if date.fromisoformat(r['week_start']) in weeks]
    needed=[g['id'] for g in plan['gaps'] if g['status']=='unknown' and g['plan_impact']=='material' and g.get('resolution')=='diagnostic' and g['id'] not in state['confirmations'] and not any(t.get('gap_id')==g['id'] for t in plan['assignments'])]
    context={**detail_context(plan,capacity,now),'stage':'rolling_detail','outline':outline,'diagnostics_needed':needed,'fixed_items':fixed_items(fixed),'prior_completed_work':prior_work(state),
        'confirmations':state['confirmations'],**window_context(capacity,weeks,budgets)}
    undetailed=sum(row['undetailed'] for row in milestone_totals(plan).values())
    def check(output):
        return [*validate_detail(output,plan,capacity,weeks,budgets,fixed),*check_window_coverage(output,weeks,budgets,undetailed)]
    output,_=await write_stage(app.state.model,WindowDetail,DETAIL_INSTRUCTIONS,context,check,lambda:set_stage(app,row,owner,'rolling'),DETAIL_MAX_TOKENS)
    plan=planner_state(row)['active']
    operation=row['pending']['id']
    for item in output.model_dump(mode='json')['assignments']:
        plan['assignments'].append(new_task(item,str(uuid5(NAMESPACE_URL,operation+':assignment:'+item['key']))))
    plan['revision']=plan.get('revision',0)+1
    add_event(plan,f'detail:{operation}','detail_added',now,'Added detail for '+', '.join(w.isoformat() for w in weeks))

async def revise_tasks(app,row,account,*,weeks,budgets,extra,kind,config=None,key,week=None,overrides=None,effect=None):
    """Model-written replacement tasks for the given weeks, validated and stored as a proposal.

    Completed, pinned and custom tasks are fixed. Nothing changes until the user accepts.
    """
    owner=account['id'];state=planner_state(row);now=app.state.clock();plan=state['active']
    working=private_copy(plan)
    if config is not None:
        working['config']=config.model_dump(mode='json');working['config_hash']=config_digest(config)
    capacity=plan_capacity(working,now)
    moment=(capacity.today,capacity.now_minute)
    replaceable=[t for t in working['assignments'] if placed(t) and t['origin']=='generated' and not t.get('pinned') and week_of(day_of(t)) in weeks and (day_of(t),task_span(t)[0])>=moment]
    replaced={t['id'] for t in replaceable}
    fixed=[t for t in working['assignments'] if t.get('date') and t.get('start_time') and t['status'] in ('scheduled','completed') and t['id'] not in replaced]
    fixed_minutes={w:sum(t['duration_minutes'] for t in fixed if week_of(day_of(t))==w and t.get('count_hours',True)) for w in weeks}
    room={w:max(0,budgets[w]-fixed_minutes[w]) for w in weeks}
    context={**detail_context(working,capacity,now),'stage':kind,'outline':[r for r in working.get('outline',[]) if date.fromisoformat(r['week_start']) in weeks],'prior_completed_work':prior_work(state),
        'replaceable_tasks':[{k:t.get(k) for k in ('key','milestone_key','date','start_time','duration_minutes','task','completion_criterion','depends_on')} for t in replaceable],
        'fixed_items':fixed_items(fixed),**window_context(capacity,weeks,room),**extra}
    def check(output):
        replacing={t['key'] for t in replaceable}
        cleared=[t for t in fixed if t['key'] not in replacing]
        errors=check_assignments(output,capacity,cleared,weeks[0],{m['key'] for m in working['milestones']},weeks=weeks,budgets=room)
        return errors
    output,attempts=await write_stage(app.state.model,TaskRevision,REVISION_INSTRUCTIONS,context,check,lambda:set_stage(app,row,owner,'revising'),DETAIL_MAX_TOKENS)
    data=output.model_dump(mode='json')
    old_by_key={t['key']:t for t in replaceable};added=[];moved=[];removed=[]
    for item in data['assignments']:
        prior=old_by_key.pop(item['key'],None)
        if prior:
            if (str(prior['date']),prior['start_time'])!=(item['date'],item['start_time']):moved.append(item['task'])
            prior.update({k:item[k] for k in ('task','completion_criterion','date','start_time','duration_minutes','milestone_key','depends_on','refresher_reason','kind','gap_id')})
            prior['week_start']=week_of(date.fromisoformat(item['date'])).isoformat();prior['baseline']=f"{item['date']} {item['start_time']}"
            changed(working,prior,now,'revised')
        else:
            working['assignments'].append(new_task(item,str(uuid5(NAMESPACE_URL,key+':assignment:'+item['key']))));added.append(item['task'])
    for task in old_by_key.values():
        task.update(status='removed',removed_reason='revised',action_needed=None);changed(working,task,now,'revised');removed.append(task['task'])
    if overrides:
        for code,value in overrides.items():
            working.setdefault('week_states',{}).setdefault(code,{}).update(value)
    return build_proposal(plan,working,kind,now,key,effect.pop('summary'),message=data['message'],week=week,moved=moved,added=added,removed=removed,warnings=overflow_warning(working,now),**effect)

async def propose_checkin(app,row,account):
    body=row['pending']['body'];state=planner_state(row);plan=state['active'];now=app.state.clock()
    if not is_current_schema(plan):raise Problem('This roadmap can’t take a check-in. Start a new roadmap.',409,'legacy_plan')
    code=body['week_start'];record=plan.get('checkins',{}).get(code) or {}
    answers=record.get('answers')
    if not answers:raise Problem('Answer the check-in questions first.',409,'checkin_answers')
    if record.get('status') in ('completed','expired'):raise Problem('This check-in has closed. Your workload target is unchanged.',409,'checkin_closed')
    week=date.fromisoformat(code);capacity=plan_capacity(plan,now)
    load=next_week_workload(plan,week,answers['next_week'],capacity);following=load['week']
    await set_stage(app,row,account['id'],'revising')
    state=planner_state(row);plan=state['active']
    if capacity.target<following or week_target(plan,following,capacity)==0 and load['target']==0:
        working=private_copy(plan)
        proposal=build_proposal(plan,working,'checkin',now,row['pending']['id'],'Keep your plan as it is. There is no next-week work to adjust.',message='There is no study time to adjust next week, so nothing changes.',week=code,workload_before_minutes=load['base'],workload_after_minutes=load['target'])
    else:
        overrides={following.isoformat():{'workload_minutes':load['target'],'workload_source':'checkin'}} if load['target']!=load['base'] else {}
        extra={'checkin_answers':{k:answers.get(k) for k in ('week_feel','next_week')},'note':answers.get('note'),'recap':recap(plan,week,capacity),'workload_target_minutes':load['target']}
        proposal=await revise_tasks(app,row,account,weeks=[following],budgets={following:load['target']},extra=extra,kind='checkin',key=row['pending']['id'],week=code,overrides=overrides,
            effect={'summary':f"Next week's workload becomes {load['target']/60:g} hours.",'workload_before_minutes':load['base'],'workload_after_minutes':load['target'],'uses_buffer':load['uses_buffer'],'add_block_suggested':load['exceeds_capacity']})
    state=planner_state(row);state['proposal']=proposal;plan=state['active']
    plan['checkins'][code]={**plan['checkins'].get(code,{}),'status':'proposed'}

async def chat_turn(app,row,account,assess,read_context):
    """One saved chat message: answer, collect settings and, with a plan present, prepare a preview."""
    body=row['pending']['body'];state=planner_state(row)
    source=await read_context(account)
    if not source['ready']:raise Problem('Complete your selected CV and extracted Career goal first.',409,'inputs_missing')
    config=saved_config(state);now=app.state.clock()
    capacity=Capacity(config,now,completed_sessions(state['active']))
    report=capacity.report(allow_past_start=bool(state['active']))
    plan=state['candidate'] or state['active']
    output=await app.state.model.generate(ChatTurn,CHAT_INSTRUCTIONS,{
        'current_date':capacity.today.isoformat(),'time_zone':config.time_zone,'goal':source['goal'],'planning_defaults':source['planning_defaults'],
        'settings':config.model_dump(mode='json'),'runway':{k:report[k] for k in ('issues','calendar','study','budget')},
        'current_plan':compact_plan(plan),'messages':row['messages'][-12:],'history_window':'Latest 12 messages; saved settings preserve earlier choices.',
        'user_message':body['message']})
    updated,note=apply_settings(config,output.settings,capacity.today)
    reply=output.reply+(f'\n\n{note}' if note else '')
    active=state['active'];settings_changed=config_digest(updated)!=config_digest(config)
    if is_current_schema(active) and not state['candidate'] and not note and (output.revision_instruction or settings_changed):
        key=row['pending']['id']
        if output.revision_instruction:
            working_capacity=plan_capacity({**active,'config':updated.model_dump(mode='json')},now)
            weeks=[w for w in window_weeks(working_capacity) if working_capacity.between(w,w+timedelta(days=6))>0]
            if weeks:
                budgets={w:working_capacity.week_minutes(w)[1] for w in weeks}
                proposal=await revise_tasks(app,row,account,weeks=weeks,budgets=budgets,extra={'instruction':output.revision_instruction,'user_message':body['message']},kind='revision',config=updated if settings_changed else None,key=key,effect={'summary':'Revise your unfinished generated tasks.'})
                planner_state(row)['proposal']=proposal
        else:
            try:state['proposal']=edit_proposal(active,updated,now,key)
            except Problem as problem:reply+=f'\n\n{problem.detail}'
        state=planner_state(row)
    elif output.revision_instruction and plan and not note:
        await prepare_plan(app,row,account,assess,read_context,config=updated,instruction=output.revision_instruction,user_message=body['message'])
        state=planner_state(row)
    elif is_current_schema(active) and not state['candidate']:pass
    else:state['config']=updated.model_dump(mode='json')
    row['messages'].append({'id':row['pending']['id']+':reply','role':'assistant','content':reply,'created_at':stamp()})
