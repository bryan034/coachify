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
