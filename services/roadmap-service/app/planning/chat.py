"""The settings chat helper beside the fixed planner form."""
from pydantic import ValidationError
from elo_shared.runtime import Problem, stamp
from app.planning.capacity import Capacity, blackout_problem, normalized
from app.planning.outlines import prepare_outline
from app.planning.state import completed_sessions, planner_state, saved_config
from app.schemas.roadmap import ChatTurn, PlannerConfig

CHAT_INSTRUCTIONS='''You are the chat helper beside the user's fixed roadmap planner form. The form is the confirmed record; you guide the user through it and fill it in from the conversation. Be warm and practical, stay career-focused, ask only one or two questions at a time and do not repeat resolved ones.

Required details come first. runway.issues names what is still missing: missing_target (a target date or a duration), no_budget (a weekly study budget) and no_blocks (recurring study blocks: day, start time and duration). Count anything this user_message supplies as answered, then ask for the next missing detail. The start date is today unless they say otherwise. Once the required details are in, offer the optional ones once: blackouts, the longest session they want (preferred_session_minutes), the break they want for each hour studied (break_minutes_per_hour, 0 to 30) and learning focus. plan_day is the weekday (Monday=0) on which next week is planned from this week's results; leave it null for the last day of their week. If they decline, move on. Saved planning_defaults are suggestions to offer, not facts to apply. Goal job_dates are evidence of application, interview or start dates: you may suggest a target from them but must never invent one.

Return only settings the user stated or clearly agreed to, in settings; every other field is null. Days and weekdays run Monday=0 to Sunday=6. Dates are YYYY-MM-DD, resolved from current_date in time_zone. Times are 24-hour HH:MM. Budgets and durations are whole minutes. blocks and blackouts replace the whole saved list, so include existing entries you want kept. learning_focus uses interview_practice, portfolio_work, hands_on_projects, courses_and_reading, certification, networking.

A blackout is time the user cannot study. frequency is once, daily, weekly or monthly. start_date is the first date it applies, or current_date when they give none; end_date is an optional last date. interval means every N days, weeks or months and defaults to 1. weekdays is required for weekly and empty otherwise. Monthly repeats on start_date's day of the month. Use start_time and end_time for a time slot and leave both null for a whole day. A slot must end after it starts on the same day, so an overnight blackout needs two entries.

Never compute available hours or claim the schedule fits: the planner form shows the calculated runway. You cannot start generation or apply a plan. When the required details are in, tell the user to review the form and press Generate.

When current_plan is present and the user asks to change it, set revision_instruction to a short, precise description of the change, and include any settings changes. This prepares a revised outline to preview; nothing applies until the user accepts it. Week-by-week tasks are planned from the roadmap page, not from chat. Do not set revision_instruction when the user only asks a question. Completed sessions cannot be changed. Factual skill corrections belong in Skills Profile, so point the user there.'''

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
        await prepare_outline(app,row,account,assess,read_context,config=updated,instruction=output.revision_instruction,user_message=body['message'])
        state=planner_state(row)
    else:state['config']=updated.model_dump(mode='json')
    row['messages'].append({'id':row['pending']['id']+':reply','role':'assistant','content':reply,'created_at':stamp()})
