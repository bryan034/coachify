"""Read projections and change detection for the timed roadmap. No model calls happen here."""
from datetime import timedelta
from elo_shared.runtime import digest
from elo_shared.skill_groups import skill_groups
from app.planning.capacity import Capacity, to_minute
from app.schemas.roadmap import PlannerConfig

COMPLETED_WORK_LIMIT=300

ASSESSMENT_FIELDS=('id','input_hash','role','target_type','job_skill_gaps','interview_prep_gaps','constraints','groups','priorities','research_coverage','evidence')

def planner_state(row):
    state=row.setdefault('planner',{})
    for key,value in (('config',None),('candidate',None),('active',None),('proposal',None)):state.setdefault(key,value)
    state.setdefault('confirmations',{})
    state.setdefault('archived',[])
    state.setdefault('completed_work',[])
    return state
def saved_config(state,default_zone=None):
    if state['config'] is None and default_zone:
        try:return PlannerConfig(time_zone=default_zone)
        except ValueError:pass
    return PlannerConfig.model_validate(state['config'] or {})
def config_digest(config):
    return digest(config.model_dump(mode='json'))
def settings_differ(plan,state):
    """Compares current forms, so a saved plan's older settings format never reads as a change."""
    return config_digest(PlannerConfig.model_validate(plan['config']))!=config_digest(saved_config(state))
def completed_sessions(plan):
    return [a for a in (plan or {}).get('assignments',[]) if a['status']=='completed']
def work_record(plan,task):
    """What generation is told about finished or skipped work: outcome, linked skills, dates and feedback."""
    milestone=next((m for m in plan.get('milestones',[]) if m['key']==task.get('milestone_key')),{})
    gaps={g['id']:g['name'] for g in plan.get('gaps',[])}
    return {'task':task['task'],'outcome':task['status'],'minutes':task['duration_minutes'],'milestone':milestone.get('title'),'skills':[gaps[g] for g in milestone.get('gap_ids',[]) if g in gaps],
        'completed_at':task.get('completed_at'),'feedback':task.get('feedback'),'note':task.get('evidence_note'),'kind':task.get('kind','study'),'plan_id':plan.get('id')}
def finished_records(plan):
    return [work_record(plan,task) for task in (plan or {}).get('assignments',[]) if task['status'] in ('completed','skipped')]
def prior_work(state):
    """Completed work from past roadmaps and the current one, trusted for planning. Skills Profile evidence is unchanged."""
    return [*state.get('completed_work',[]),*finished_records(state.get('active'))][-COMPLETED_WORK_LIMIT:]
def session_has_passed(session,capacity):
    day=str(session['date']);today=capacity.today.isoformat()
    return day<today or (day==today and to_minute(session['start_time'])<capacity.now_minute)

def plan_inputs(source):
    """The same evidence records the model receives, summarised for display."""
    skills=[];experience=[]
    for reference,entry in (source.get('evidence') or {}).items():
        record={'ref':reference,'name':entry.get('name'),'kind':entry.get('kind'),'text':entry.get('text') or ''}
        if entry.get('kind') in ('skill','user_declaration'):
            skills.append({**record,**{k:entry.get(k) for k in ('attribution','assistance','proficiency','experience_months','support_uncertain')}})
        elif entry.get('kind')!='education':
            experience.append({**record,**{k:entry.get(k) for k in ('start_date','end_date','ongoing')}})
    return {'goal':source.get('goal'),'cv':source.get('cv'),'skills':skills,'experience':experience,
        'skill_groups':skill_groups((s['name'],None) for s in skills if s['name'])}

def plan_review(plan,now):
    if not plan:return None
    capacity=Capacity(PlannerConfig.model_validate(plan['config']),now,completed_sessions(plan))
    scheduled=sorted((a for a in plan['assignments'] if a['status']=='scheduled' and a.get('date')),key=lambda a:(str(a['date']),a['start_time']))
    missed=[a['id'] for a in scheduled if session_has_passed(a,capacity)]
    upcoming=[a for a in scheduled if a['id'] not in missed]
    milestones={}
    for milestone in plan['milestones']:
        members=[a for a in plan['assignments'] if a.get('milestone_key')==milestone['key'] and a['status'] not in ('removed','skipped')]
        done=[a for a in members if a['status']=='completed']
        milestones[milestone['id']]={'sessions_total':len(members),'sessions_completed':len(done),'completed_minutes':sum(a['duration_minutes'] for a in done)}
    return {'next_assignment_id':upcoming[0]['id'] if upcoming else None,'missed_assignment_ids':missed,
        'remaining':capacity.report(allow_past_start=True),'milestones':milestones}

def candidate_blockers(state,source,now):
    """Reasons the current preview can no longer be applied as shown."""
    candidate=state['candidate'];active=state['active'];blockers=[]
    if not candidate:return blockers
    add=lambda code,message:blockers.append({'code':code,'message':message})
    if candidate.get('base_active_id')!=(active or {}).get('id') or (active and candidate.get('base_progress_revision') not in (None,active.get('progress_revision',0))):
        add('active_changed','Your active roadmap changed after this preview was prepared. Prepare a fresh preview.')
    if source.get('availability')=='unavailable':
        add('sources_unavailable','Your CV and Career goal cannot be checked right now. Retry before accepting.')
    elif not source.get('ready') or candidate['assessment_hash']!=source.get('input_hash'):
        add('inputs_changed','Your CV or Career goal changed after this preview was prepared. Generate a fresh plan.')
    if settings_differ(candidate,state):
        add('settings_changed','Your settings changed after this preview was prepared. Generate a fresh plan.')
    capacity=Capacity(PlannerConfig.model_validate(candidate['config']),now)
    if any(a['status']=='scheduled' and a.get('date') and session_has_passed(a,capacity) for a in candidate['assignments']):
        add('plan_expired','A session in this preview has already passed. Generate a fresh plan.')
    return blockers

def revision_signals(state,source,now):
    candidate=state['candidate'];active=state['active'];signals=[]
    add=lambda kind,message:signals.append({'kind':kind,'message':message})
    plan=candidate or active
    if not plan:return signals
    if digest(state['confirmations'])!=plan['confirmations_hash']:
        add('evidence','You answered experience questions after this plan was prepared.')
    if candidate or not active:return signals
    if settings_differ(active,state):
        add('settings','Your saved settings differ from this roadmap. Use Edit plan to preview applying them, or Start new roadmap to plan with them.' if active.get('schema_version')=='roadmap-v3' else 'Your study settings changed since this roadmap was accepted.')
    if source.get('input_hash') and active['assessment_hash']!=source['input_hash']:
        add('evidence','Your CV, skills or Career goal changed since this roadmap was prepared.')
    if active.get('schema_version')=='roadmap-v3':return signals
    capacity=Capacity(PlannerConfig.model_validate(active['config']),now)
    scheduled=[a for a in active['assignments'] if a['status']=='scheduled']
    done=completed_sessions(active)
    if len(done)>active.get('completed_at_generation',0):
        add('progress',f"You've completed {len(done)-active.get('completed_at_generation',0)} session(s) since this roadmap was prepared.")
    if any(session_has_passed(a,capacity) for a in scheduled):
        add('progress','Some sessions passed without being completed.')
    if not scheduled or not any(not session_has_passed(a,capacity) for a in scheduled):
        add('next_week','Your detailed sessions are finished or have passed. Plan your next week.')
    return signals

def retry_body(row,kind):
    last=row.get('last_operation') or {}
    if last.get('status')=='failed' and last.get('kind','message')==kind:return last.get('body')
    return None

def coach_messages(plan,view,now):
    """Short messages grounded only in recorded progress. Nothing here calls a model."""
    done=view['this_week'];pace=view['pace'];messages=[]
    if done['planned']:messages.append(f"This week: {done['completed']/60:g} of {done['planned']/60:g} scheduled hours done.")
    if pace['status']=='behind':messages.append(f"You are {pace['behind_minutes']/60:g} hours behind the work due by now.")
    elif pace['status']=='on_track':messages.append('You are on track with the work due by now.')
    hard=[t for t in plan['assignments'] if t.get('feedback')=='too_hard'][-1:]
    easy=[t for t in plan['assignments'] if t.get('feedback')=='too_easy'][-1:]
    if hard:messages.append(f"You marked “{hard[0]['task']}” as too hard. Later planning takes that into account.")
    elif easy:messages.append(f"You marked “{easy[0]['task']}” as too easy. Later planning takes that into account.")
    return messages
def active_view(row,plan,now,*,model_available=True):
    from app.planning.checkin import checkin_view
    from app.planning.metrics import backlog_rows, detail_needed, pace, progress, projection, week_rows, window_weeks
    from app.planning.schedule import day_of, placed, plan_capacity, task_span
    from elo_shared.runtime import operation_view
    capacity=plan_capacity(plan,now);today=capacity.today;moment=(today,capacity.now_minute)
    upcoming=sorted((t for t in plan['assignments'] if placed(t) and (day_of(t),task_span(t)[0])>=moment and not t.get('action_needed')),key=lambda t:(day_of(t),t['start_time'],t['id']))
    weeks=window_weeks(capacity);current=weeks[0] if weeks else today
    week_tasks=[t for t in plan['assignments'] if t.get('date') and day_of(t)>=current and (day_of(t)-current).days<7 and t['status'] in ('scheduled','completed') and t.get('count_hours',True)]
    this_week={'completed':sum(t['duration_minutes'] for t in week_tasks if t['status']=='completed'),'planned':sum(t['duration_minutes'] for t in week_tasks)}
    action=[t['id'] for t in plan['assignments'] if t.get('action_needed') and t['status'] in ('scheduled','backlog')]
    moves=[e for e in plan.get('events',[]) if e['type'] in ('auto_move','auto_backlog') and not e['undone']][-5:]
    notices=[];expired=[key for key,record in plan.get('checkins',{}).items() if record.get('status')=='expired' and key>=(current-timedelta(days=7)).isoformat()]
    if expired:notices.append('Your last check-in closed before it was finished. Your workload target stayed the same and your next tasks were still planned.')
    need=detail_needed(plan,now);operation=row.get('pending') or {};last=row.get('last_operation') or {}
    rolling={'status':'idle','weeks':[w.isoformat() for w in need],'error':None,'retry_after':None}
    if operation.get('kind')=='rolling':rolling['status']='running'
    elif need:
        if last.get('kind')=='rolling' and last.get('status')=='failed':
            shown=operation_view(row) or {}
            rolling.update(status='failed',error=(last.get('error') or {}).get('detail'),retry_after=shown.get('retry_after'))
        else:rolling['status']='needed' if model_available else 'unavailable'
    view={'today':today.isoformat(),'current_week':current.isoformat(),'next_week':weeks[1].isoformat() if len(weeks)>1 else None,'next_task_id':upcoming[0]['id'] if upcoming else None,
        'today_task_ids':[t['id'] for t in plan['assignments'] if t.get('date') and day_of(t)==today and t['status'] in ('scheduled','completed')],'this_week':this_week,
        'progress':progress(plan),'pace':pace(plan,now),'projection':projection(plan,now),'weeks':week_rows(plan,now),'backlog':backlog_rows(plan,now),'checkin':checkin_view(plan,now),
        'rolling':rolling,'skipped_task_ids':[t['id'] for t in plan['assignments'] if t['status']=='skipped']}
    view['coach']={'messages':coach_messages(plan,view,now),'action_needed_task_ids':action,'recent_moves':moves,'notices':notices}
    return view
def candidate_view(plan,now):
    from app.planning.metrics import progress, projection, week_rows
    return {'progress':progress(plan),'projection':projection(plan,now),'weeks':week_rows(plan,now)}
def roadmap_summary(state,now):
    from app.planning.metrics import pace, progress, projection
    from app.planning.schedule import day_of, is_current_schema, placed, plan_capacity, task_span, week_of
    plan=state['active']
    if not plan:return {'has_active':False}
    if not is_current_schema(plan):return {'has_active':True,'schema_version':plan.get('schema_version'),'role':plan['assessment'].get('role'),'target_date':str(plan['config'].get('target_date'))}
    capacity=plan_capacity(plan,now);moment=(capacity.today,capacity.now_minute)
    upcoming=sorted((t for t in plan['assignments'] if placed(t) and (day_of(t),task_span(t)[0])>=moment),key=lambda t:(day_of(t),t['start_time'],t['id']))
    next_task={k:(str(upcoming[0][k]) if k=='date' else upcoming[0][k]) for k in ('id','task','date','start_time','duration_minutes')} if upcoming else None
    return {'has_active':True,'schema_version':plan['schema_version'],'role':plan['assessment'].get('role'),'target_date':str(plan['config']['target_date']),'current_week':week_of(capacity.today).isoformat(),
        'next_task':next_task,'progress':progress(plan),'pace':pace(plan,now),'projection':projection(plan,now)}

def planner_view(row,source,now,default_zone=None):
    from app.planning.proposals import proposal_blockers
    from app.planning.schedule import is_current_schema
    state=planner_state(row)
    active,candidate=state['active'],state['candidate']
    config=saved_config(state,default_zone)
    capacity=Capacity(config,now,completed_sessions(active))
    current=is_current_schema(active)
    return {'config':config.model_dump(mode='json'),'config_saved':state['config'] is not None,
        'runway':capacity.report(allow_past_start=bool(active)),'inputs':plan_inputs(source),
        'candidate':candidate,'candidate_review':plan_review(candidate,now),'candidate_view':candidate_view(candidate,now) if candidate else None,'candidate_blockers':candidate_blockers(state,source,now),
        'active':active,'active_review':plan_review(active,now),'active_view':active_view(row,active,now,model_available=source.get('model_available',True)) if current else None,
        'proposal':state['proposal'],'proposal_blockers':proposal_blockers(state,now),'archived':state['archived'],'confirmations':state['confirmations'],
        'signals':revision_signals(state,source,now),'retry_generate':retry_body(row,'generate'),'retry_checkin':retry_body(row,'checkin')}
