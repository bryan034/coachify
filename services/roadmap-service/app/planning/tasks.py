"""Canonical editable work and legacy scheduled-session projection."""
import copy
from datetime import date
from uuid import NAMESPACE_URL, uuid5
from elo_shared.runtime import Problem, stamp
from app.planning.capacity import Capacity, to_minute, week_of
from app.schemas.roadmap import PlannerConfig


def ensure_tasks(plan):
    """Upgrade an old snapshot in memory; persistence happens only on a mutation."""
    if 'editable_tasks' not in plan:
        gaps={g['id']:g for g in plan.get('gaps',[])}
        result=[]
        for a in plan.get('assignments',[]):
            gap=gaps.get(a.get('gap_id'),{})
            result.append({'id':a['id'],'title':a['task'],'instructions':a['task'],
                'completion_outcome':a['completion_criterion'],'estimated_minutes':a['duration_minutes'],
                'requirement_refs':[gap['requirement_ref']] if gap.get('requirement_ref') else [],
                'requirement_source_hash':plan.get('assessment_hash'),
                'requirement_source_id':plan.get('assessment_id'),
                'prerequisites':[],'milestone_key':a['milestone_key'],
                'schedule':[{'date':str(a['date']),'start_time':a['start_time'],'duration_minutes':a['duration_minutes']}],
                'status':'completed' if a['status']=='completed' else 'not_started',
                'completed_at':a.get('completed_at'),'evidence_note':a.get('evidence_note'),
                'history':copy.deepcopy(a.get('history',[])),'removed':False,'removal':None,'definition_review_required':False,
                'generated_key':a['key'],'origin':'generated','overrides':[], 'source_assignment':copy.deepcopy(a)})
        plan['editable_tasks']=result
    return plan['editable_tasks']


def project_assignments(plan):
    """Build old-format sessions with unique keys and stable session IDs.

    The model can choose any valid key, including strings that look like a
    generated split key. Reserve all first-session keys before allocating split
    keys so a newly generated key cannot hide a different assignment.
    """
    milestones={m['key'] for m in plan.get('milestones',[])}
    tasks=[task for task in ensure_tasks(plan) if not task.get('removed') and
        task.get('milestone_key') in milestones and task.get('schedule')]
    reserved={task.get('generated_key') or task['id'] for task in tasks}
    used=set();primary={}

    def allocate(task,slot,kind):
        attempt=0
        while True:
            key='slot-'+str(uuid5(NAMESPACE_URL,f"roadmap:{kind}:{task['id']}:{slot}:{attempt}"))
            if key not in reserved and key not in used:
                used.add(key)
                return key
            attempt+=1

    # A malformed or older snapshot may already contain repeated primary keys.
    # Resolve them deterministically rather than hiding a session in key maps.
    for task in sorted(tasks,key=lambda item:item['id']):
        key=task.get('generated_key') or task['id']
        if key in used:key=allocate(task,0,'primary')
        else:used.add(key)
        primary[task['id']]=key

    # Preallocate in task-id order; output remains in the user's original order.
    split={}
    for task in sorted(tasks,key=lambda item:item['id']):
        for i in range(1,len(task['schedule'])):
            split[(task['id'],i)]=allocate(task,i,'split')

    output=[]
    for task in tasks:
        source=task.get('source_assignment') or {}
        for i,slot in enumerate(task.get('schedule',[])):
            ident=task['id'] if i==0 else str(uuid5(NAMESPACE_URL,task['id']+':slot:'+str(i)))
            key=primary[task['id']] if i==0 else split[(task['id'],i)]
            output.append({'id':ident,'key':key,'milestone_key':task['milestone_key'],
                'gap_id':source.get('gap_id'),'kind':source.get('kind','study'),**slot,
                'task':task['instructions'],'completion_criterion':task['completion_outcome'],
                'status':'completed' if task['status']=='completed' else 'scheduled',
                'completed_at':task.get('completed_at'),'evidence_note':task.get('evidence_note'),
                'history':copy.deepcopy(task.get('history',[]))})
    plan['assignments']=output
    return output


def find_task(plan,task_id):
    found=next((t for t in ensure_tasks(plan) if t['id']==task_id and not t.get('removed')),None)
    if not found:raise Problem('This task was not found in your active roadmap.',404,'not_found')
    return found


def requirement_ids(plan):
    assessment=plan.get('assessment') or {}
    known=set()
    for section in ('job_skill_gaps','interview_prep_gaps','constraints','groups'):
        for item in assessment.get(section) or []:
            for name in ('ref','id','group_id'):
                if item.get(name):known.add(item[name])
    return known

def validate_links(plan,task,previous_refs=()):
    tasks=ensure_tasks(plan); ids={t['id'] for t in tasks}
    prereqs=task['prerequisites']
    if len(prereqs)!=len(set(prereqs)) or any(p not in ids for p in prereqs) or task['id'] in prereqs:
        raise Problem('Choose existing, distinct prerequisite tasks.',422,'validation')
    edges={t['id']:t.get('prerequisites',[]) for t in tasks};edges[task['id']]=prereqs
    # Only edges of this task changed. A cycle exists if any proposed prerequisite
    # can already reach this task; iterative traversal also handles long chains.
    pending=list(prereqs);visited=set()
    while pending:
        node=pending.pop()
        if node==task['id']:raise Problem('Prerequisites cannot form a cycle.',422,'validation')
        if node in visited:continue
        visited.add(node);pending.extend(edges.get(node,[]))
    if task.get('milestone_key') and task['milestone_key'] not in {m['key'] for m in plan.get('milestones',[])}:
        raise Problem('Choose a milestone in this roadmap.',422,'validation')
    known=requirement_ids(plan)
    refs=task['requirement_refs']
    if len(refs)!=len(set(refs)) or any(ref not in known and ref not in previous_refs for ref in refs):
        raise Problem('Choose requirement references from this roadmap’s assessment.',422,'validation')


def change_status(task,status,note=None):
    note=(note or '').strip() or None
    before=task['status']
    if before==status and (status!='completed' or note==task.get('evidence_note')) and not task.get('definition_review_required'):return
    now=stamp()
    event={'at':now,'from':before,'to':status,
        'evidence_note':task.get('evidence_note'),'new_evidence_note':note if status=='completed' else None,'completion_definition':task['completion_outcome'] if status=='completed' else None}
    if status=='completed':event['estimated_minutes_at_completion']=task['estimated_minutes']
    task.setdefault('history',[]).append(event)
    task['status']=status
    task['definition_review_required']=False
    task['completed_at']=now if status=='completed' else None
    task['evidence_note']=note if status=='completed' else None


def task_readiness(task,tasks,plan):
    by_id={t['id']:t for t in tasks};reasons=[]
    def add(code,message):reasons.append({'code':code,'message':message})
    for ident in task.get('prerequisites',[]):
        other=by_id.get(ident)
        if not other or other.get('removed'):add('prerequisite_removed',f'Prerequisite {ident} was removed or is unavailable.')
        elif other['status']!='completed' or other.get('definition_review_required'):add('prerequisite_incomplete',f'Complete or review prerequisite {other["title"]}.')
    milestone=next((m for m in plan.get('milestones',[]) if m['key']==task.get('milestone_key')),None)
    for key in (milestone or {}).get('prerequisite_keys',[]):
        members=[t for t in tasks if t.get('milestone_key')==key]
        prerequisite=next((m for m in plan.get('milestones',[]) if m['key']==key),None)
        valid=[t for t in members if not t.get('removed') and t['status']=='completed' and not t.get('definition_review_required')]
        # Generated milestone estimates are remaining effort, not a stable total;
        # completed work from earlier revisions cannot be compared against them.
        outcome=(prerequisite or {}).get('outcome') or {}
        enough=bool(outcome.get('demonstrated') and not outcome.get('definition_review_required'))
        if not members or len(valid)!=len(members) or not enough:
            add('milestone_prerequisite_incomplete',f'Prerequisite milestone {key} is not complete.')
    return {'actionable':task['status']!='completed' and not reasons,'reasons':reasons}


def schedule_warnings(plan,now):
    tasks=[t for t in ensure_tasks(plan) if not t.get('removed')];warnings={};slots=[];weeks={};windows_by_day={};bounds={}
    def add(code,message,ids):
        # One warning per category, with all affected tasks, avoids a response
        # proportional to the number of overlapping pairs or repeated slots.
        warning=warnings.setdefault(code,{'code':code,'message':message,'task_ids':{}})
        warning['task_ids'].update(dict.fromkeys(ids))
    capacity=Capacity(PlannerConfig.model_validate(plan['config']),now)
    for task in tasks:
        scheduled=sum(s['duration_minutes'] for s in task['schedule'])
        if scheduled<task['estimated_minutes']:add('unscheduled_remainder','Some estimated minutes are unscheduled. See each task for the remaining minutes.',[task['id']])
        if scheduled>task['estimated_minutes']:add('effort_exceeded','Scheduled time exceeds the estimate.',[task['id']])
        for slot in task['schedule']:
            day=date.fromisoformat(str(slot['date']));begin=to_minute(slot['start_time']);end=begin+slot['duration_minutes']
            slots.append((day,begin,end,task['id']))
            start_in_calendar=day.toordinal()*1440+begin;end_in_calendar=day.toordinal()*1440+end
            old=bounds.get(task['id'])
            bounds[task['id']]=(min(start_in_calendar,old[0]),max(end_in_calendar,old[1])) if old else (start_in_calendar,end_in_calendar)
            week=weeks.setdefault(week_of(day),{'minutes':0,'task_ids':{}})
            week['minutes']+=slot['duration_minutes'];week['task_ids'][task['id']]=None
            if day<capacity.start_date or (capacity.target and day>capacity.target):add('outside_plan','A session is outside the roadmap dates.',[task['id']])
            if day not in windows_by_day:
                blackouts=capacity.blackout_windows(day)
                try:
                    windows=capacity._windows(day)
                    eligible=windows['preferred']+(windows['backup'] if capacity.config.use_backup else [])
                except OverflowError:
                    # Python cannot represent the next day at its calendar limit.
                    # Preserve accepted dates and report that eligibility is unknown.
                    eligible=None
                windows_by_day[day]=(blackouts,eligible)
            blackouts,eligible=windows_by_day[day]
            if any(begin<high and end>low for low,high in blackouts):add('blackout','A session overlaps a blackout.',[task['id']])
            if eligible is None:add('calendar_unavailable','Study-time eligibility cannot be calculated for this calendar date.',[task['id']])
            elif not any(begin>=low and end<=high for low,high in eligible):add('outside_study_time','A session is outside available study time.',[task['id']])
    # For each date, the previous interval with the latest end is sufficient to
    # identify every task participating in any overlap, without enumerating pairs.
    last_day=None;latest_end=-1;latest_id=None
    for day,start,end,ident in sorted(slots):
        if day!=last_day:last_day=day;latest_end=-1;latest_id=None
        if start<latest_end:add('overlap','Scheduled sessions overlap.',[latest_id,ident])
        if end>latest_end:latest_end=end;latest_id=ident
    by_id={t['id']:t for t in tasks}
    for task in tasks:
        if task['id'] not in bounds:continue
        for prerequisite_id in task.get('prerequisites',[]):
            prerequisite=by_id.get(prerequisite_id)
            if not prerequisite or (prerequisite['status']=='completed' and not prerequisite.get('definition_review_required')):continue
            if prerequisite_id not in bounds:
                add('prerequisite_unscheduled','Scheduled work has an incomplete prerequisite without scheduled time.',[prerequisite_id,task['id']])
            elif bounds[prerequisite_id][1]>bounds[task['id']][0]:
                add('prerequisite_order','Scheduled work begins before its incomplete prerequisite is scheduled to finish.',[prerequisite_id,task['id']])
    # Generated roadmaps also express dependencies between milestones. Summarise
    # each prerequisite milestone once so many dependants do not expand pairs.
    milestone_work={}
    for task in tasks:
        key=task.get('milestone_key')
        if not key or (task['status']=='completed' and not task.get('definition_review_required')):continue
        group=milestone_work.setdefault(key,{'ids':{},'unscheduled':False,'latest_end':-1})
        group['ids'][task['id']]=None
        if task['id'] not in bounds:group['unscheduled']=True
        else:group['latest_end']=max(group['latest_end'],bounds[task['id']][1])
    milestone_prereqs={m['key']:m.get('prerequisite_keys',[]) for m in plan.get('milestones',[])}
    milestone_conflicts={}
    for task in tasks:
        if task['id'] not in bounds:continue
        for key in milestone_prereqs.get(task.get('milestone_key'),[]):
            group=milestone_work.get(key)
            if not group:continue
            if group['unscheduled']:milestone_conflicts.setdefault(('prerequisite_unscheduled',key),{})[task['id']]=None
            if group['latest_end']>bounds[task['id']][0]:milestone_conflicts.setdefault(('prerequisite_order',key),{})[task['id']]=None
    for (code,key),dependants in milestone_conflicts.items():
        message=('Scheduled work has an incomplete prerequisite without scheduled time.' if code=='prerequisite_unscheduled'
            else 'Scheduled work begins before its incomplete prerequisite is scheduled to finish.')
        add(code,message,[*milestone_work[key]['ids'],*dependants])
    for week in weeks.values():
        if week['minutes']>capacity.cap:add('weekly_capacity','Scheduled work exceeds the weekly study budget.',week['task_ids'])
    return [{**warning,'task_ids':list(warning['task_ids'])} for warning in warnings.values()]
