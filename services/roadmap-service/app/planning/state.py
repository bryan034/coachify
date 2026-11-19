"""Read projections and change detection for the timed roadmap. No model calls happen here."""
import copy
from uuid import NAMESPACE_URL, uuid5
from elo_shared.runtime import digest
from elo_shared.milestone_review import removal_needs_review
from elo_shared.skill_groups import skill_groups
from app.planning.capacity import Capacity, to_minute
from app.schemas.roadmap import DISPLAY_FIELDS, SHAPE_FIELDS, PlannerConfig

ASSESSMENT_FIELDS=('id','input_hash','role','target_type','job_skill_gaps','interview_prep_gaps','constraints','groups','priorities','research_coverage','evidence','skill_profile')

def planner_state(row):
    state=row.setdefault('planner',{})
    for key,value in (('config',None),('active',None),('outline_candidate',None),('outline_active',None),('week_candidate',None)):state.setdefault(key,value)
    state.setdefault('confirmations',{})
    state.setdefault('week_blocks',[])
    state.setdefault('month_blocks',[])
    return state
def reduced_periods(periods):
    """Profile availability periods as planner minutes. A malformed period is skipped, never guessed."""
    result=[]
    for period in periods or []:
        try:result.append({'start_date':str(period['start_date']),'end_date':str(period['end_date']),'weekly_minutes':round(float(period['weekly_hours'])*60)})
        except (KeyError,TypeError,ValueError):continue
    return result
def with_periods(config,periods):
    """Reduced periods belong to Profile; the service copies the current ones over anything a client sent."""
    if periods is None:return config
    try:return PlannerConfig.model_validate({**config.model_dump(mode='json'),'reduced_periods':reduced_periods(periods)})
    except ValueError:return config.model_copy(update={'reduced_periods':[]})
def saved_config(state,default_zone=None,periods=None):
    if state['config'] is None and default_zone:
        try:return with_periods(PlannerConfig(time_zone=default_zone,allow_overflow=True),periods)
        except ValueError:pass
    return with_periods(PlannerConfig.model_validate(state['config']) if state['config'] is not None else PlannerConfig(allow_overflow=True),periods)
def planning_source_changed(before,after):
    """Fence publication against owner evidence, evaluation and current availability changes."""
    def capture(source):
        return {'input_hash':source.get('input_hash'),'ready':source.get('ready'),
            'freshness':(source.get('evaluation') or {}).get('freshness','current'),
            'periods':(source.get('planning_defaults') or {}).get('availability_periods',[])}
    return digest(capture(before))!=digest(capture(after))
def config_digest(config):
    return digest(config.model_dump(mode='json',exclude=set(DISPLAY_FIELDS)))
def shape_digest(config):
    """Settings that decide what the outline covers. A change here needs the outline reviewed."""
    return digest(config.model_dump(mode='json',include=set(SHAPE_FIELDS)))
def schedule_digest(config):
    """Settings that decide when sessions can be placed. A change here applies from the next week planned."""
    return digest(config.model_dump(mode='json',exclude={*SHAPE_FIELDS,*DISPLAY_FIELDS}))
def settings_differ(plan,state):
    """Compares current settings forms."""
    return shape_digest(PlannerConfig.model_validate(plan['config']))!=shape_digest(saved_config(state))
def completed_sessions(plan):
    if not plan:return []
    if isinstance(plan.get('editable_tasks'),list):
        # Rebuild assignments from canonical tasks in memory without mutating the snapshot.
        from app.planning.tasks import project_assignments
        projection={'editable_tasks':plan['editable_tasks'],'milestones':plan.get('milestones',[])}
        assignments=project_assignments(projection)
    else:
        assignments=plan.get('assignments',[])
    return [a for a in assignments if a['status']=='completed']
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
            'review_needed':not current or (milestone.get('outcome') or {}).get('definition_review_required',False) or (milestone.get('outcome') or {}).get('membership_review_required',False) or any(t.get('definition_review_required') for t in current) or any(removal_needs_review(t,milestone.get('outcome'),bool(current)) for t in tasks)}
    return {'next_assignment_id':upcoming[0]['id'] if upcoming else None,'missed_assignment_ids':missed,
        'remaining':capacity.report(allow_past_start=True),'milestones':milestones}

def learning_view(plan,now):
    """Each skill the active roadmap works on, most important first, with its own progress and next session."""
    if not plan:return {'has_roadmap':False,'roadmap_id':None,'skills_total':0,'skills_started':0,'skills_done':0,'steps':[]}
    # Rebuild the session view on a copy.
    canonical=isinstance(plan.get('editable_tasks'),list)
    if canonical:
        from app.planning.tasks import legacy_inference_source_is_safe, project_assignments, task_link_source_is_current
        plan=copy.deepcopy(plan)
        project_assignments(plan)
    review=plan_review(plan,now);missed=set(review['missed_assignment_ids'])
    milestones={m['key']:m for m in plan['milestones']}
    steps=[]
    for gap in sorted(plan['gaps'],key=lambda g:(g['priority'],g['name'].casefold())):
        if canonical:
            def task_belongs(task):
                source=task.get('source_assignment') or {}
                refs=task.get('requirement_refs') or []
                explicitly_linked=bool(refs and task_link_source_is_current(plan,task) and gap.get('requirement_ref') and gap['requirement_ref'] in refs)
                # An explicit relink or unlink replaces the source assignment's old gap association.
                if 'requirement_refs' in (task.get('overrides') or []):return explicitly_linked
                # A manually created task's chosen requirements are explicit; a personal task does not inherit a skill from its milestone.
                if task.get('origin')=='user':return explicitly_linked
                if refs:return explicitly_linked
                if not legacy_inference_source_is_safe(plan,task):return False
                if source.get('gap_id'):
                    return source['gap_id']==gap['id'] or explicitly_linked
                milestone_gaps=set((milestones.get(task.get('milestone_key')) or {}).get('gap_ids',[]))
                matched=[item['id'] for item in plan['gaps'] if item['id'] in milestone_gaps]
                return len(matched)==1 and matched[0]==gap['id']
            related=[task for task in plan['editable_tasks'] if task_belongs(task)]
            active=[task for task in related if not task.get('removed')]
            # Match every projected session to its authoritative task.
            session_ids={task['id'] if i==0 else str(uuid5(NAMESPACE_URL,task['id']+':slot:'+str(i)))
                         for task in active for i,_ in enumerate(task.get('schedule') or [])}
            sessions=sorted((a for a in plan['assignments'] if a['id'] in session_ids),key=lambda a:(str(a['date']),a['start_time']))
        else:
            def belongs(session):
                # A session names one skill, or else it serves every skill of its milestone.
                if session.get('gap_id'):return session['gap_id']==gap['id']
                return gap['id'] in (milestones.get(session['milestone_key']) or {}).get('gap_ids',[])
            sessions=sorted((a for a in plan['assignments'] if belongs(a)),key=lambda a:(str(a['date']),a['start_time']))
        done=[a for a in sessions if a['status']=='completed'];open_sessions=[a for a in sessions if a['status']=='scheduled']
        upcoming=next((a for a in open_sessions if a['id'] not in missed),None)
        state='not_scheduled' if not sessions else 'done' if len(done)==len(sessions) else 'in_progress' if done else 'not_started'
        if canonical:
            def still_needs_review(task):
                # Requirement-only work has no milestone outcome to review.
                if not task.get('milestone_key'):return False
                milestone=milestones.get(task.get('milestone_key'))
                has_active_members=any(not member.get('removed') and member.get('milestone_key')==task.get('milestone_key') for member in plan['editable_tasks'])
                return removal_needs_review(task,(milestone or {}).get('outcome'),has_active_members)
            removed=any(still_needs_review(task) for task in related)
            finished=bool(active) and all(task['status']=='completed' and not task.get('definition_review_required') for task in active)
            # A "not demonstrated" self-report acknowledges removed work without completing its outcome.
            reviewed_as_not_demonstrated=any(
                task.get('removed') and task.get('milestone_key') and not still_needs_review(task)
                and not ((milestones.get(task.get('milestone_key')) or {}).get('outcome') or {}).get('demonstrated')
                for task in related)
            started=any(task['status'] in ('in_progress','completed') for task in active)
            if finished and not removed and not reviewed_as_not_demonstrated:state='done'
            elif started:state='in_progress'
            else:state='not_started' if sessions else 'not_scheduled'
        steps.append({'gap_id':gap['id'],'name':gap['name'],'status':gap['status'],'state':state,'priority':gap['priority'],'rationale':gap['rationale'],
            'milestones':[m['title'] for m in plan['milestones'] if gap['id'] in m['gap_ids']],
            'sessions_total':len(sessions),'sessions_completed':len(done),'sessions_missed':sum(a['id'] in missed for a in open_sessions),
            'completed_minutes':sum(a['duration_minutes'] for a in done),'remaining_minutes':sum(a['duration_minutes'] for a in open_sessions),
            'next_session':upcoming and {'id':upcoming['id'],'date':str(upcoming['date']),'start_time':upcoming['start_time'],'duration_minutes':upcoming['duration_minutes'],
                'task':upcoming['task'],'completion_criterion':upcoming['completion_criterion']}})
    return {'has_roadmap':True,'roadmap_id':plan['id'],'skills_total':len(steps),'skills_started':sum(s['state'] in ('in_progress','done') for s in steps),
        'skills_done':sum(s['state']=='done' for s in steps),'steps':steps}

def revision_signals(state,source,now):
    """Changes since the outline was accepted that the user may want a revised outline for."""
    outline=state['outline_active'];active=state['active'];signals=[]
    add=lambda kind,message:signals.append({'kind':kind,'message':message})
    basis=state['outline_candidate'] or outline or active
    if not basis:return signals
    if digest(state['confirmations'])!=basis['confirmations_hash']:
        add('evidence','You answered experience questions after this roadmap was prepared.')
    if state['outline_candidate']:return signals
    if settings_differ(basis,state):
        add('settings','Your timeline, weekly hours or learning focus changed since this roadmap was prepared.')
    if source.get('input_hash') and basis['assessment_hash']!=source['input_hash']:
        add('evidence','Your CV, skills or Career goal changed since this roadmap was prepared.')
    if active and not outline:
        add('progress','This roadmap was made before weekly planning. Generate an updated roadmap to plan week by week; your progress is kept.')
    return signals

def retry_body(row,kind):
    last=row.get('last_operation') or {}
    if last.get('status')=='failed' and last.get('kind','message')==kind:return last.get('body')
    return None

def week_overview(state,config,now):
    """Every week of the outline with its objective and whether its tasks exist yet."""
    from app.planning.tasks import ensure_tasks
    from app.planning.weeks import day_of, week_is_planned
    from datetime import timedelta
    outline=state['outline_candidate'] or state['outline_active']
    if not outline or not outline.get('weeks'):return []
    capacity=Capacity(config,now);current=capacity.week(capacity.today)
    tasks=[t for t in ensure_tasks(copy.deepcopy(state['active'])) if not t.get('removed')] if state['active'] else []
    result=[]
    for item in sorted(outline['weeks'],key=lambda w:w['week_start']):
        week=day_of(item['week_start']);last=week+timedelta(days=6)
        members=[t for t in tasks if any(week<=day_of(s['date'])<=last for s in t.get('schedule',[]))]
        planned=bool(members) or (bool(state['active']) and week_is_planned(state,week,config,now) and week>=current)
        status='past' if last<capacity.today else 'planned' if planned else 'open' if week<=current else 'projected'
        result.append({**item,'start_date':max(week,capacity.start_date).isoformat(),'end_date':min(last,capacity.target or last).isoformat(),'status':status,
            'tasks_total':len(members),'tasks_completed':sum(t['status']=='completed' for t in members),
            'planned_minutes':sum(s['duration_minutes'] for t in members for s in t.get('schedule',[]) if week<=day_of(s['date'])<=last)})
    return result

def preview_sessions(state,now):
    """The week preview as to-do rows, built on a copy: new tasks and carried work at their proposed times."""
    from app.planning.tasks import ensure_tasks, project_assignments
    from app.planning.sessions import session_views
    from app.planning.weeks import publish_outline
    candidate=state['week_candidate'];outline=state['outline_candidate'] or state['outline_active']
    if not candidate or not outline:return []
    plan=publish_outline(outline,state['active']);tasks={t['id']:t for t in ensure_tasks(plan)}
    shown=set()
    for entry in candidate['carryover']:
        if entry['action'] in ('carry','split') and entry['task_id'] in tasks:
            tasks[entry['task_id']]['schedule']=copy.deepcopy(entry['schedule']);shown.add(entry['task_id'])
    plan['editable_tasks'].extend(copy.deepcopy(candidate['tasks']));shown.update(t['id'] for t in candidate['tasks'])
    project_assignments(plan)
    return [row for row in session_views(plan,now) if row['task_id'] in shown and candidate['start_date']<=row['date']<candidate['end_exclusive']]

def planner_view(row,source,now,default_zone=None):
    state=planner_state(row)
    operation=row.get('pending') or row.get('last_operation') or {}
    if operation.get('kind')=='outline_generate' and operation.get('body',{}).get('auto_accept'):
        # Only published tasks belong in this response.
        state=copy.deepcopy(state)
        state['outline_candidate']=None;state['week_candidate']=None
    # Legacy snapshots are converted only in the response; a read never saves an upgrade.
    from app.planning.tasks import ensure_tasks, project_assignments, schedule_warnings
    from app.planning.sessions import session_views
    from app.planning.weeks import planning
    active=copy.deepcopy(state['active'])
    if active is not None:
        ensure_tasks(active)
        project_assignments(active)
    config=saved_config(state,default_zone,(source.get('planning_defaults') or {}).get('availability_periods'))
    capacity=Capacity(config,now,completed_sessions(active))
    return {'config':config.model_dump(mode='json'),'config_saved':state['config'] is not None,
        'runway':capacity.report(allow_past_start=bool(active or state['outline_active'])),'inputs':plan_inputs(source),
        'active':active,'active_review':plan_review(active,now),
        'outline_candidate':copy.deepcopy(state['outline_candidate']),'outline_active':copy.deepcopy(state['outline_active']),
        'week_candidate':copy.deepcopy(state['week_candidate']),'week_blocks':copy.deepcopy(state['week_blocks']),'month_blocks':copy.deepcopy(state['month_blocks']),
        'weeks':week_overview(state,config,now),'week_planning':planning(state,now,config),'preview_sessions':preview_sessions(state,now),
        'task_warnings':schedule_warnings(active,now) if active else [],
        'active_sessions':session_views(active,now) if active else [],'confirmations':state['confirmations'],
        'signals':revision_signals(state,source,now),
        'retry_outline':retry_body(row,'outline_generate'),'retry_week':retry_body(row,'week_generate')}
