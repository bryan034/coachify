"""Read projections and change detection for the timed roadmap. No model calls happen here."""
import copy
from elo_shared.runtime import digest
from elo_shared.skill_groups import skill_groups
from app.planning.capacity import Capacity, to_minute
from app.schemas.roadmap import PlannerConfig

ASSESSMENT_FIELDS=('id','input_hash','role','target_type','job_skill_gaps','interview_prep_gaps','constraints','groups','priorities','research_coverage','evidence')

def planner_state(row):
    state=row.setdefault('planner',{})
    for key,value in (('config',None),('candidate',None),('active',None)):state.setdefault(key,value)
    state.setdefault('confirmations',{})
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
    scheduled=sorted((a for a in plan['assignments'] if a['status']=='scheduled'),key=lambda a:(str(a['date']),a['start_time']))
    missed=[a['id'] for a in scheduled if session_has_passed(a,capacity)]
    upcoming=[a for a in scheduled if a['id'] not in missed]
    milestones={}
    for milestone in plan['milestones']:
        members=[a for a in plan['assignments'] if a['milestone_key']==milestone['key']]
        done=[a for a in members if a['status']=='completed']
        tasks=[t for t in plan.get('editable_tasks',[]) if t.get('milestone_key')==milestone['key']]
        current=[t for t in tasks if not t.get('removed')]
        milestones[milestone['id']]={'sessions_total':len(members),'sessions_completed':len(done),'completed_minutes':sum(a['duration_minutes'] for a in done),
            'tasks_total':len(current),'tasks_completed':sum(t['status']=='completed' and not t.get('definition_review_required') for t in current),
            'review_needed':not current or (milestone.get('outcome') or {}).get('definition_review_required',False) or any(t.get('removed') or t.get('definition_review_required') for t in tasks)}
    return {'next_assignment_id':upcoming[0]['id'] if upcoming else None,'missed_assignment_ids':missed,
        'remaining':capacity.report(allow_past_start=True),'milestones':milestones}

def candidate_blockers(state,source,now):
    """Reasons the current preview can no longer be applied as shown."""
    candidate=state['candidate'];active=state['active'];blockers=[]
    if not candidate:return blockers
    add=lambda code,message:blockers.append({'code':code,'message':message})
    if candidate.get('base_active_id')!=(active or {}).get('id'):
        add('active_changed','Your active roadmap changed after this preview was prepared. Prepare a fresh preview.')
    if source.get('availability')=='unavailable':
        add('sources_unavailable','Your CV and Career goal cannot be checked right now. Retry before accepting.')
    elif not source.get('ready') or candidate['assessment_hash']!=source.get('input_hash'):
        add('inputs_changed','Your CV or Career goal changed after this preview was prepared. Generate a fresh plan.')
    if settings_differ(candidate,state):
        add('settings_changed','Your settings changed after this preview was prepared. Generate a fresh plan.')
    if candidate.get('revision_review'):
        add('revision_review_required','Review proposed tasks that may duplicate saved or removed work before accepting this roadmap.')
    capacity=Capacity(PlannerConfig.model_validate(candidate['config']),now)
    # Student-retained sessions may already be in the past; their timing is an
    # explicit saved choice. Only newly proposed sessions can expire the preview.
    prior_ids={a['id'] for a in (active or {}).get('assignments',[])}
    if any(a['status']=='scheduled' and a['id'] not in prior_ids and session_has_passed(a,capacity) for a in candidate['assignments']):
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
        add('settings','Your study settings changed since this roadmap was accepted.')
    if source.get('input_hash') and active['assessment_hash']!=source['input_hash']:
        add('evidence','Your CV, skills or Career goal changed since this roadmap was prepared.')
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

def planner_view(row,source,now,default_zone=None):
    state=planner_state(row)
    # Legacy snapshots are converted only in the response. A read never saves an
    # upgrade; the next explicit task mutation persists the canonical task data.
    from app.planning.tasks import ensure_tasks, project_assignments, schedule_warnings
    active,candidate=copy.deepcopy(state['active']),copy.deepcopy(state['candidate'])
    for plan in (active,candidate):
        if plan is not None and 'editable_tasks' in plan:
            ensure_tasks(plan)
            project_assignments(plan)
    config=saved_config(state,default_zone)
    capacity=Capacity(config,now,completed_sessions(active))
    return {'config':config.model_dump(mode='json'),'config_saved':state['config'] is not None,
        'runway':capacity.report(allow_past_start=bool(active)),'inputs':plan_inputs(source),
        'candidate':candidate,'candidate_review':plan_review(candidate,now),'candidate_blockers':candidate_blockers(state,source,now),
        'active':active,'active_review':plan_review(active,now),
        'task_warnings':schedule_warnings(active,now) if active else [],'confirmations':state['confirmations'],
        'signals':revision_signals(state,source,now),'retry_generate':retry_body(row,'generate')}
