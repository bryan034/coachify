"""Read projections of the planner workspace for the roadmap page. Reads never save an upgrade."""
import copy
from datetime import timedelta
from app.planning.capacity import Capacity
from app.planning.sessions import session_views
from app.planning.state import completed_sessions, outline_generated, plan_inputs, plan_review, planner_state, retry_body, revision_signals, saved_config
from app.planning.tasks import ensure_tasks, project_assignments, schedule_warnings
from app.planning.weeks import day_of, planning, publish_outline, week_is_planned

def week_overview(state,config,now):
    """Every week of the outline with its objective and whether its tasks exist yet."""
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
        'signals':revision_signals(state,source),'outline_generated':outline_generated(state),
        'retry_outline':retry_body(row,'outline_generate'),'retry_week':retry_body(row,'week_generate')}
