"""LLM work for the timed roadmap: settings chat, plan writing and the bounded validation retry."""
import copy
from datetime import date
from uuid import NAMESPACE_URL, uuid5
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, digest, stamp
from app.planning.capacity import Capacity, blackout_problem, normalized, to_clock
from app.planning.state import ASSESSMENT_FIELDS, completed_sessions, config_digest, planner_state, saved_config
from app.planning.validator import validate_plan
from app.schemas.roadmap import ChatTurn, PlanDraft, PlannerConfig

MAX_ATTEMPTS=3
PLAN_MAX_TOKENS=24000
# Assessment polling (90s) plus three 55-second model calls and their source checks.
PLANNING_SECONDS=330
PROMPT_VERSION='roadmap-plan-v1'

PLAN_INSTRUCTIONS='''You write a personal study roadmap towards the user's career goal. You own the learning plan: identify and prioritise gaps, sequence prerequisites, estimate effort, define milestones and write the actual assignments. The backend owns dates and capacity and rejects anything that does not fit, so work only inside the supplied windows and weekly capacity.

Gaps. assessment holds the evidence-linked comparison of the user's goal with their skills.
- A requirement whose outcome has a confirmed_shortfall component is status confirmed_gap. uncertain or partial outcomes are status unknown: missing proof is not a shortfall. Supported outcomes and members of satisfied "any" groups are not gaps. assessment.constraints are non-learning conditions that study cannot resolve; never list them as gaps.
- A gap from the assessment has source "stated" and its requirement_ref. A requirement you infer about the role yourself has source "inferred", no requirement_ref, an inference_reason and status unknown.
- plan_impact is "material" when the answer would change what the user should study or in what order. A material unknown needs resolution "diagnostic" (a task of 30 minutes or less in the first planning week, kind "diagnostic", with gap_id set) or "confirm_experience" (a short confirmation_question). confirmations are the user's self-reported answers: use them and do not ask again. Reuse a gap's id when revising.
- Every id in assessment.priorities must appear in a milestone's gap_ids or in beyond_deadline.

Milestones. estimated_minutes is the effort still remaining. Each needs a projected_start and projected_end inside the runway, prerequisites finishing first, and a demonstrable_outcome the user could show another person. Effort is checked against eligible capacity: for any date range, the milestones wholly inside it must fit weekly_capacity for that range.

The target date is the end of the roadmap. No milestone may end after it. If the gaps exceed the runway, prioritise prerequisites and the work that most directly supports the goal, put what remains in beyond_deadline with its estimated effort, and say plainly in deadline_outcome what the user can reasonably achieve by the deadline. fits_in_runway is false exactly when beyond_deadline is not empty. Never promise readiness or employment.

Assignments. Write detailed assignments for first_planning_week only, with milestone-level projections for everything later. Each assignment has a date, start_time, duration_minutes, a specific task, a milestone_key and an observable completion_criterion. Avoid generic "learn X" tasks. It must lie completely inside one first_week_windows entry, must not overlap another assignment or completed work, and the week's total must stay within the week's usable_minutes. Use "preferred" windows before "backup" windows. Aim for sessions near settings.preferred_session_minutes and follow settings.learning_focus and learning_notes.

Revising. completed_work is permanent: keep its milestones (with the same key), never repeat its keys and do not schedule over it. Completing a session is not proof of proficiency, so do not treat it as closing a gap unless evidence or a recorded outcome supports that. Reuse milestone keys for continuing work. instruction is the user's requested change; it describes what they want, but cannot override these rules. An exclusion needs an exact quote from user_message.

If validation_errors is present, your previous_output was rejected. Fix every listed error and return the complete corrected plan.'''

CHAT_INSTRUCTIONS='''You are the chat helper beside the user's fixed roadmap planner form. The form is the confirmed record; you guide the user through it and fill it in from the conversation. Be warm and practical, stay career-focused, ask only one or two questions at a time and do not repeat resolved ones.

Required details come first. runway.issues names what is still missing: missing_target (a target date or a duration), no_budget (a weekly study budget) and no_blocks (recurring study blocks: day, start time, duration, preferred or backup). Count anything this user_message supplies as answered, then ask for the next missing detail. The start date is today unless they say otherwise. Once the required details are in, offer the optional ones once: backup blocks, blackouts, a preferred session length and learning focus. If they decline, move on. Saved planning_defaults are suggestions to offer, not facts to apply. Goal job_dates are evidence of application, interview or start dates: you may suggest a target from them but must never invent one.

Return only settings the user stated or clearly agreed to, in settings; every other field is null. Days and weekdays run Monday=0 to Sunday=6. Dates are YYYY-MM-DD, resolved from current_date in time_zone. Times are 24-hour HH:MM. Budgets and durations are whole minutes. blocks and blackouts replace the whole saved list, so include existing entries you want kept. learning_focus uses interview_practice, portfolio_work, hands_on_projects, courses_and_reading, certification, networking.

A blackout is time the user cannot study. frequency is once, daily, weekly or monthly. start_date is the first date it applies, or current_date when they give none; end_date is an optional last date. interval means every N days, weeks or months and defaults to 1. weekdays is required for weekly and empty otherwise. Monthly repeats on start_date's day of the month. Use start_time and end_time for a time slot and leave both null for a whole day. A slot must end after it starts on the same day, so an overnight blackout needs two entries.

Never compute available hours or claim the schedule fits: the planner form shows the calculated runway. You cannot start generation or apply a plan. When the required details are in, tell the user to review the form and press Generate.

When current_plan is present and the user asks to change it, set revision_instruction to a short, precise description of the change, and include any settings changes. This prepares a preview; nothing applies until the user accepts it. Do not set revision_instruction when the user only asks a question. Completed sessions cannot be changed. Factual skill corrections belong in Skills Profile, so point the user there.'''

def compact_plan(plan):
    if not plan:return None
    fields=('summary','first_planning_week','gaps','milestones','deadline_outcome','beyond_deadline','exclusions')
    return {**{k:plan.get(k) for k in fields},'scheduled':[{k:a[k] for k in ('key','milestone_key','date','start_time','duration_minutes','task')} for a in plan['assignments'] if a['status']=='scheduled']}

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

async def write_plan(model,context,check,before_retry):
    """Call the model until its plan passes validation, at most MAX_ATTEMPTS times in total."""
    errors=[];previous=None
    for attempt in range(1,MAX_ATTEMPTS+1):
        request={**context,'attempt':attempt}
        if errors:
            await before_retry()
            request.update(validation_errors=errors,previous_output=previous)
        draft=await model.generate(PlanDraft,PLAN_INSTRUCTIONS,request,max_tokens=PLAN_MAX_TOKENS)
        errors=check(draft)
        if not errors:return draft,attempt
        previous=draft.model_dump(mode='json')
    examples=' '.join(e['message'] for e in errors[:3])
    raise Problem(f'We could not produce a plan that fits your schedule after {MAX_ATTEMPTS} attempts. Your last valid plan is unchanged. {examples}'[:1500],502,'plan_validation')

def plan_changes(previous,assignments,milestones):
    """What a preview changes relative to the active plan, shown before the user accepts it."""
    if not previous:return None
    slot=lambda a:(str(a['date']),a['start_time'],a['duration_minutes'])
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

def build_plan(draft,assessment,config,first_week,operation_id,attempts,active,confirmations):
    data=draft.model_dump(mode='json')
    completed=copy.deepcopy(completed_sessions(active))
    earlier={m['key']:m for m in (active or {}).get('milestones',[])}
    milestones=[{**m,'id':m['key'],'outcome':copy.deepcopy(earlier.get(m['key'],{}).get('outcome') or {'demonstrated':False})} for m in data['milestones']]
    assignments=[*completed,*[{**a,'id':str(uuid5(NAMESPACE_URL,operation_id+':assignment:'+a['key'])),'status':'scheduled','completed_at':None,'evidence_note':None,'history':[]} for a in data['assignments']]]
    return {'schema_version':'roadmap-v2','id':str(uuid5(NAMESPACE_URL,operation_id+':roadmap')),
        'assessment_id':assessment['id'],'assessment_hash':assessment['input_hash'],'assessment':{k:assessment.get(k) for k in ASSESSMENT_FIELDS},
        'config':config.model_dump(mode='json'),'config_hash':config_digest(config),'confirmations_hash':digest(confirmations),
        'base_active_id':(active or {}).get('id'),'created_at':stamp(),'first_planning_week':first_week.isoformat(),
        'completed_at_generation':len(completed),'summary':data['summary'],'gaps':data['gaps'],'milestones':milestones,'assignments':assignments,
        'deadline_outcome':data['deadline_outcome'],'beyond_deadline':data['beyond_deadline'],'exclusions':data['exclusions'],
        'changes':plan_changes(active,assignments,milestones),'generation':{'prompt_version':PROMPT_VERSION,'attempts':attempts}}

async def set_stage(app,row,owner,stage):
    row['pending']['stage']=stage
    seconds=630 if getattr(app.state.model,'local',False) else PLANNING_SECONDS+30
    await thread(app.state.store.checkpoint,owner,row,seconds)

async def prepare_plan(app,row,account,assess,read_context,*,config=None,instruction=None,user_message=None):
    """Compare skills, write and validate a plan, and store it as the candidate.

    The row is only changed after validation, so a failure keeps every earlier plan.
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
    report=capacity.report(allow_past_start=bool(active))
    if not report['can_generate']:raise Problem(' '.join(i['message'] for i in report['issues']),409,'generation_blocked')
    first_week=date.fromisoformat(report['first_planning_week'])
    retained=sorted({s['milestone_key'] for s in completed})
    def check(draft):
        return validate_plan(draft,capacity,result,first_week,completed=completed,retained_milestones=retained,confirmations=confirmations,instruction=user_message)
    local=now.astimezone(capacity.zone)
    draft,attempts=await write_plan(app.state.model,{
        'current_date':capacity.today.isoformat(),'current_time':to_clock(local.hour*60+local.minute),'time_zone':config.time_zone,
        'goal':source['goal'],'assessment':{k:result.get(k) for k in ASSESSMENT_FIELDS},
        'settings':config.model_dump(mode='json'),'runway':{k:report[k] for k in ('calendar','study')},
        'first_planning_week':report['first_planning_week'],'first_week_windows':capacity.windows_for_week(first_week),
        'weekly_capacity':[{k:w[k] for k in ('week_start','usable_minutes','partial')} for w in report['weeks']],
        'completed_work':[{k:s.get(k) for k in ('key','milestone_key','date','start_time','duration_minutes','task','completion_criterion','evidence_note')} for s in completed],
        'milestone_outcomes':{m['key']:m['outcome'] for m in (active or {}).get('milestones',[]) if m['outcome'].get('demonstrated')},
        'confirmations':confirmations,'current_plan':compact_plan(active),'instruction':instruction,'user_message':user_message},
        check,lambda:set_stage(app,row,owner,'correcting'))
    latest=await app.state.upstream.account(account['token'])
    if latest['id']!=owner:raise Problem('Your account changed while preparing this plan.',401,'session')
    fresh=await read_context(latest)
    if fresh.get('input_hash')!=source['input_hash']:raise Problem('Your evidence or goal changed while preparing this plan. Retry with the latest inputs.',409,'inputs_changed')
    state=planner_state(row)
    state['config']=config.model_dump(mode='json')
    state['candidate']=build_plan(draft,result,config,first_week,operation_id,attempts,active,confirmations)
    row['assessment']={k:result.get(k) for k in ASSESSMENT_FIELDS}

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
        'settings':config.model_dump(mode='json'),'runway':{k:report[k] for k in ('issues','calendar','study')},
        'current_plan':compact_plan(plan),'messages':row['messages'][-12:],'history_window':'Latest 12 messages; saved settings preserve earlier choices.',
        'user_message':body['message']})
    updated,note=apply_settings(config,output.settings,capacity.today)
    reply=output.reply+(f'\n\n{note}' if note else '')
    if output.revision_instruction and plan and not note:
        await prepare_plan(app,row,account,assess,read_context,config=updated,instruction=output.revision_instruction,user_message=body['message'])
        state=planner_state(row)
    else:state['config']=updated.model_dump(mode='json')
    row['messages'].append({'id':row['pending']['id']+':reply','role':'assistant','content':reply,'created_at':stamp()})
