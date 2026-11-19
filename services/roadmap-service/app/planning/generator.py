"""The settings chat helper, and helpers shared by outline and week generation."""
import copy
from datetime import date
from uuid import NAMESPACE_URL, uuid5
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, stamp
from app.planning.capacity import Capacity, blackout_problem, normalized, to_clock, to_minute
from app.planning.state import ASSESSMENT_FIELDS, completed_sessions, planner_state, saved_config
from app.schemas.roadmap import ChatTurn, PlannerConfig

MAX_ATTEMPTS=3
PLAN_MAX_TOKENS=24000
# Total operation budget, including up to 60 Assessment polls at two-second intervals.
PLANNING_SECONDS=240

CHAT_INSTRUCTIONS='''You are the chat helper beside the user's fixed roadmap planner form. The form is the confirmed record; you guide the user through it and fill it in from the conversation. Be warm and practical, stay career-focused, ask only one or two questions at a time and do not repeat resolved ones.

Required details come first. runway.issues names what is still missing: missing_target (a target date or a duration), no_budget (a weekly study budget) and no_blocks (recurring study blocks: day, start time and duration). Count anything this user_message supplies as answered, then ask for the next missing detail. The start date is today unless they say otherwise. Once the required details are in, offer the optional ones once: blackouts, the longest session they want (preferred_session_minutes), the break they want for each hour studied (break_minutes_per_hour, 0 to 30) and learning focus. plan_day is the weekday (Monday=0) on which next week is planned from this week's results; leave it null for the last day of their week. If they decline, move on. Saved planning_defaults are suggestions to offer, not facts to apply. Goal job_dates are evidence of application, interview or start dates: you may suggest a target from them but must never invent one.

Return only settings the user stated or clearly agreed to, in settings; every other field is null. Days and weekdays run Monday=0 to Sunday=6. Dates are YYYY-MM-DD, resolved from current_date in time_zone. Times are 24-hour HH:MM. Budgets and durations are whole minutes. blocks and blackouts replace the whole saved list, so include existing entries you want kept. learning_focus uses interview_practice, portfolio_work, hands_on_projects, courses_and_reading, certification, networking.

A blackout is time the user cannot study. frequency is once, daily, weekly or monthly. start_date is the first date it applies, or current_date when they give none; end_date is an optional last date. interval means every N days, weeks or months and defaults to 1. weekdays is required for weekly and empty otherwise. Monthly repeats on start_date's day of the month. Use start_time and end_time for a time slot and leave both null for a whole day. A slot must end after it starts on the same day, so an overnight blackout needs two entries.

Never compute available hours or claim the schedule fits: the planner form shows the calculated runway. You cannot start generation or apply a plan. When the required details are in, tell the user to review the form and press Generate.

When current_plan is present and the user asks to change it, set revision_instruction to a short, precise description of the change, and include any settings changes. This prepares a revised outline to preview; nothing applies until the user accepts it. Week-by-week tasks are planned from the roadmap page, not from chat. Do not set revision_instruction when the user only asks a question. Completed sessions cannot be changed. Factual skill corrections belong in Skills Profile, so point the user there.'''

def planning_assessment(result):
    """Keep the saved skill judgements and their evidence handles without copying raw source documents."""
    value={k:result.get(k) for k in ASSESSMENT_FIELDS if k!='evidence'}
    value['evidence']={ref:{k:record[k] for k in ('name','kind','attribution','reviewed','cv_level','canonical_skill_id') if k in record}
        for ref,record in result.get('evidence',{}).items()}
    return value

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

def protected_tasks(plan):
    """Student intent and task history survive replacement of generated sessions."""
    if not plan:return []
    from app.planning.tasks import ensure_tasks
    tasks=ensure_tasks(copy.deepcopy(plan))
    protected=[t for t in tasks if
        t.get('origin')=='user' or t.get('overrides') or t.get('removed') or
        t.get('status') in ('in_progress','completed') or t.get('history') or t.get('notes')]
    # Preserve both prerequisites and dependants, including their identities.
    ids={t['id'] for t in protected}
    while True:
        linked={t['id'] for t in tasks if t['id'] in ids or ids.intersection(t.get('prerequisites',[]))}
        linked.update(p for t in tasks if t['id'] in ids for p in t.get('prerequisites',[]))
        if linked<=ids:break
        ids.update(linked)
    return [t for t in tasks if t['id'] in ids]

def reserved_sessions(plan,now):
    """Capacity occupied by completed sessions and protected saved schedules; each slot counts once."""
    completed=completed_sessions(plan)
    reserved=[dict(s) for s in completed]
    seen={s['id'] for s in completed}
    if not plan:return reserved
    calendar=Capacity(PlannerConfig.model_validate(plan['config']),now)
    for task in protected_tasks(plan):
        if task.get('removed'):continue
        for index,slot in enumerate(task.get('schedule',[])):
            day=date.fromisoformat(str(slot['date']))
            slot=dict(slot)
            if task['status']!='completed':
                end=to_minute(slot['start_time'])+slot['duration_minutes']
                if day<calendar.today or (day==calendar.today and end<=calendar.now_minute):continue
                if day==calendar.today and to_minute(slot['start_time'])<calendar.now_minute:
                    slot['start_time']=to_clock(calendar.now_minute)
                    slot['duration_minutes']=end-calendar.now_minute
            ident=task['id'] if index==0 else str(uuid5(NAMESPACE_URL,task['id']+':slot:'+str(index)))
            if ident in seen:continue
            seen.add(ident)
            reserved.append({'id':ident,**slot})
    return reserved

async def set_stage(app,row,owner,stage):
    row['pending']['stage']=stage
    seconds=row['pending'].get('work_seconds',PLANNING_SECONDS)+30
    await thread(app.state.store.checkpoint,owner,row,seconds)

async def chat_turn(app,row,account,assess,read_context):
    """One saved chat message: answer, collect settings and, with a plan present, prepare a preview."""
    body=row['pending']['body'];state=planner_state(row)
    source=await read_context(account)
    if not source['ready']:raise Problem('Complete your selected CV and extracted Career goal first.',409,'inputs_missing')
    config=saved_config(state,periods=source['planning_defaults']['availability_periods']);now=app.state.clock()
    capacity=Capacity(config,now,completed_sessions(state['active']))
    report=capacity.report(allow_past_start=bool(state['active'] or state['outline_active']))
    outline=state['outline_candidate'] or state['outline_active']
    output=await app.state.model.generate(ChatTurn,CHAT_INSTRUCTIONS,{
        'current_date':capacity.today.isoformat(),'time_zone':config.time_zone,'goal':source['goal'],'planning_defaults':source['planning_defaults'],
        'settings':config.model_dump(mode='json',exclude={'reduced_periods'}),'runway':{k:report[k] for k in ('issues','notices','calendar','study')},
        'current_plan':outline,'messages':row['messages'][-12:],'history_window':'Latest 12 messages; saved settings preserve earlier choices.',
        'user_message':body['message']})
    updated,note=apply_settings(config,output.settings,capacity.today)
    reply=output.reply+(f'\n\n{note}' if note else '')
    if output.revision_instruction and (outline or state['active']) and not note:
        from app.planning.outlines import prepare_outline
        await prepare_outline(app,row,account,assess,read_context,config=updated,instruction=output.revision_instruction,user_message=body['message'])
        state=planner_state(row)
    else:state['config']=updated.model_dump(mode='json')
    row['messages'].append({'id':row['pending']['id']+':reply','role':'assistant','content':reply,'created_at':stamp()})
