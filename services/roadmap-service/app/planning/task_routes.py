"""Editable task operations use the existing owner-scoped workspace mutation path."""
import copy
from datetime import date
from uuid import NAMESPACE_URL, uuid5
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated, stamp
from app.planning.state import planner_state
from app.planning.tasks import change_status, ensure_tasks, find_task, project_assignments, requirement_ids, schedule_warnings, task_readiness, validate_links
from app.schemas.planner import Workspace
from app.schemas.tasks import AddTask, EditTask, RemoveTask, ChangeTaskStatus, ReconcileTasks, TaskList


def register_task_routes(app,context,mutate):
    prefix='/api/v1/roadmaps/planner/tasks'
    def active(row):
        plan=planner_state(row)['active']
        if not plan:raise Problem('There is no active roadmap yet.',404,'not_found')
        return plan

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
            validate_links(plan,task);tasks.append(task);project_assignments(plan)
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
                task.setdefault('history',[]).append({'at':stamp(),'event':'edited','fields':changed,
                    'previous':{k:copy.deepcopy(task.get(k)) for k in changed}})
                if 'completion_outcome' in changed and task['status']=='completed':task['definition_review_required']=True
                if 'requirement_refs' in changed:
                    task['requirement_source_hash']=plan.get('assessment_hash');task['requirement_source_id']=plan.get('assessment_id')
                task.update(changes);task['overrides']=sorted(set(task.get('overrides',[]))|set(changed))
                project_assignments(plan)
            return row
        return await mutate(body,account,apply,operation='tasks.edit')

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
            candidate['revision_review']=list(pending.values());project_assignments(candidate);return row
        return await mutate(body,account,apply,operation='tasks.reconcile')
