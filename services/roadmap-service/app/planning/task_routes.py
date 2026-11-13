"""Editable task operations use the existing owner-scoped workspace mutation path."""
import copy
from datetime import date
from uuid import NAMESPACE_URL, uuid5
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated, stamp
from app.planning.state import planner_state
from app.planning.milestone_membership import mark_membership_review, mark_plan_membership_changes
from app.planning.tasks import change_status, ensure_tasks, find_task, project_assignments, requirement_ids, schedule_warnings, task_readiness, validate_links
from app.schemas.planner import Workspace
from app.schemas.tasks import AddTask, EditTask, RemoveTask, ChangeTaskStatus, ReconcileTasks, SaveTaskNotes, TaskList


def register_task_routes(app,context,mutate):
    prefix='/api/v1/roadmaps/planner/tasks'
    def active(row):
        plan=planner_state(row)['active']
        if not plan:raise Problem('There is no active roadmap yet.',404,'not_found')
        return plan

    @app.get(prefix,response_model=TaskList)
    async def tasks(request:Request,start_date:date|None=None,end_date:date|None=None,account=Depends(authenticated)):
        if (start_date is None)!=(end_date is None) or (start_date and end_date<start_date):
            raise Problem('Choose a valid start and end date.',422,'validation')
        row=await thread(app.state.store.load,account['id']);plan=copy.deepcopy(active(row))
        all_tasks=ensure_tasks(plan); result=[]
        for task in all_tasks:
            if task.get('removed'):continue
            slots=task['schedule']
            if start_date and not any(start_date<=date.fromisoformat(str(s['date']))<=end_date for s in slots) and sum(s['duration_minutes'] for s in slots)>=task['estimated_minutes']:continue
            view=copy.deepcopy(task)
            view['readiness']=task_readiness(task,all_tasks,plan)
            snapshot_changed=(task.get('requirement_source_hash',plan.get('assessment_hash'))!=plan.get('assessment_hash') or
                task.get('requirement_source_id',plan.get('assessment_id'))!=plan.get('assessment_id'))
            view['stale_requirement_refs']=[ref for ref in task['requirement_refs'] if snapshot_changed or ref not in requirement_ids(plan)]
            view['unscheduled_minutes']=max(0,task['estimated_minutes']-sum(s['duration_minutes'] for s in slots))
            result.append(view)
        source=await context(account,tolerate_unavailable=True)
        # Keep the existing booleans for compatibility, while distinguishing a
        # missing/incomplete input snapshot from a verified matching snapshot.
        if source.get('availability')=='unavailable':freshness='unavailable'
        elif source.get('ready') is not True or not source.get('input_hash'):freshness='not_ready'
        elif not plan.get('assessment_hash'):freshness='unavailable'
        else:freshness='current' if source['input_hash']==plan['assessment_hash'] else 'stale'
        return {'version':row['version'],'plan_id':plan['id'],
            'stale':bool(source.get('input_hash') and source['input_hash']!=plan['assessment_hash']),
            'source_unavailable':source.get('availability')=='unavailable','freshness':freshness,
            'tasks':result,'warnings':schedule_warnings(plan,app.state.clock())}

    @app.post(prefix+'/add',response_model=Workspace)
    async def add(body:AddTask,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=active(row);tasks=ensure_tasks(plan)
            if len(tasks)>=1000:raise Problem('This roadmap reached its task capacity.',413,'workspace_capacity')
            task={**body.task.model_dump(mode='json'),'id':str(uuid5(NAMESPACE_URL,account['id']+':task:'+str(body.mutation_id))),
                'requirement_source_hash':plan.get('assessment_hash'),
                'requirement_source_id':plan.get('assessment_id'),
                'status':'not_started','completed_at':None,'evidence_note':None,'history':[],
                'removed':False,'removal':None,'definition_review_required':False,'origin':'user','generated_key':None,'overrides':[], 'source_assignment':None}
            validate_links(plan,task);tasks.append(task)
            mark_membership_review(plan,[task.get('milestone_key')]);project_assignments(plan)
            return row
        return await mutate(body,account,apply,operation='tasks.add')

    @app.post(prefix+'/edit',response_model=Workspace)
    async def edit(body:EditTask,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=active(row);task=find_task(copy.deepcopy(plan),body.task_id)
            changes=body.changes.model_dump(mode='json',exclude_unset=True)
            if any(v is None and k!='milestone_key' for k,v in changes.items()):raise Problem('Task fields cannot be empty.',422,'validation')
            updated={**task,**changes};validate_links(copy.deepcopy(plan),updated,() if 'requirement_refs' in changes else task.get('requirement_refs',[]))
            changed=[k for k,v in changes.items() if task.get(k)!=v]
            if 'requirement_refs' in changes and (task.get('requirement_source_hash')!=plan.get('assessment_hash') or task.get('requirement_source_id')!=plan.get('assessment_id')) and 'requirement_refs' not in changed:
                changed.append('requirement_refs')
            if changed:
                task=find_task(plan,body.task_id)
                old_milestone=task.get('milestone_key')
                task.setdefault('history',[]).append({'at':stamp(),'event':'edited','fields':changed,
                    'previous':{k:copy.deepcopy(task.get(k)) for k in changed}})
                if 'completion_outcome' in changed and task['status']=='completed':task['definition_review_required']=True
                if 'requirement_refs' in changed:
                    task['requirement_source_hash']=plan.get('assessment_hash');task['requirement_source_id']=plan.get('assessment_id')
                if changes.get('schedule'):task['anytime_date']=None
                task.update(changes);task['overrides']=sorted(set(task.get('overrides',[]))|set(changed))
                if old_milestone!=task.get('milestone_key'):
                    mark_membership_review(plan,[old_milestone,task.get('milestone_key')])
                project_assignments(plan)
            return row
        return await mutate(body,account,apply,operation='tasks.edit')

    @app.post(prefix+'/remove',response_model=Workspace)
    async def remove(body:RemoveTask,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=active(row);task=find_task(plan,body.task_id);now=stamp()
            task['removed']=True;task['removal']={'at':now,'reason':(body.reason or '').strip() or None}
            task.setdefault('history',[]).append({'at':now,'event':'removed','reason':task['removal']['reason']})
            mark_membership_review(plan,[task.get('milestone_key')])
            project_assignments(plan);return row
        return await mutate(body,account,apply,operation='tasks.remove')

    @app.post(prefix+'/notes',response_model=Workspace)
    async def notes(body:SaveTaskNotes,request:Request,account=Depends(authenticated)):
        """Save the task's notes document. Notes never change status, evidence or the schedule."""
        def apply(row,source):
            plan=active(row);task=find_task(plan,body.task_id)
            document=body.notes.model_dump(mode='json')
            if task.get('notes')==document:return row
            task['notes']=document;task['notes_updated_at']=stamp()
            return row
        return await mutate(body,account,apply,operation='tasks.notes')

    @app.post(prefix+'/status',response_model=Workspace)
    async def status(body:ChangeTaskStatus,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=active(row);task=find_task(copy.deepcopy(plan),body.task_id)
            note=(body.evidence_note or '').strip() or None
            if task['status']==body.status and (body.status!='completed' or task.get('evidence_note')==note) and not task.get('definition_review_required'):return row
            task=find_task(plan,body.task_id)
            change_status(task,body.status,body.evidence_note);project_assignments(plan);return row
        return await mutate(body,account,apply,operation='tasks.status')

    @app.post(prefix+'/reconcile',response_model=Workspace)
    async def reconcile(body:ReconcileTasks,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            candidate=planner_state(row)['candidate']
            if not candidate or candidate['id']!=body.candidate_id:raise Problem('This revision preview changed. Reload before reviewing it.',409,'candidate_changed')
            pending={r['task_id']:r for r in candidate.get('revision_review',[])}
            if len({d.task_id for d in body.decisions})!=len(body.decisions) or any(d.task_id not in pending for d in body.decisions):
                raise Problem('Choose each unresolved task only once.',422,'validation')
            for decision in body.decisions:
                task=find_task(candidate,decision.task_id)
                if decision.decision=='discard':
                    now=stamp();task['removed']=True;task['removal']={'at':now,'reason':'Discarded during revision review.'}
                    task.setdefault('history',[]).append({'at':now,'event':'removed','reason':task['removal']['reason']})
                pending.pop(decision.task_id)
            mark_plan_membership_changes(planner_state(row)['active'],candidate,reset_unchanged=True)
            candidate['revision_review']=list(pending.values());project_assignments(candidate);return row
        return await mutate(body,account,apply,operation='tasks.reconcile')
