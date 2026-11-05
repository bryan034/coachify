"""Timed-roadmap endpoints. Writes reuse the workspace's version and receipt protection."""
from fastapi import Depends, Request
from uuid import NAMESPACE_URL, uuid5
import copy
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated, begin, launch, operation_view, stamp
from app.planning.capacity import Capacity, normalized
from app.planning.generator import PLANNING_SECONDS
from app.planning.state import candidate_blockers, completed_sessions, planner_state, saved_config
from app.planning.tasks import change_status, ensure_tasks, project_assignments
from app.planning.task_routes import register_task_routes
from app.schemas.roadmap import (AssignmentStatus, ExperienceConfirmation, GeneratePlan, Runway, MilestoneOutcome,
    PlannerConfig, RunwayRequest, SaveConfig)
from app.schemas.planner import Mutation, Workspace

def register_planner(app,context,mutate,worker):
    prefix='/api/v1/roadmaps/planner'
    register_task_routes(app,context,mutate)
    @app.post(prefix+'/runway',response_model=Runway)
    async def runway(body:RunwayRequest,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id']);state=planner_state(row)
        capacity=Capacity(body.config,app.state.clock(),completed_sessions(state['active']))
        return capacity.report(allow_past_start=bool(state['active']))

    @app.post(prefix+'/config',response_model=Workspace)
    async def save_config(body:SaveConfig,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            today=Capacity(body.config,app.state.clock()).today
            planner_state(row)['config']=normalized(body.config,today).model_dump(mode='json')
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/generate',status_code=202)
    async def generate(body:GeneratePlan,request:Request,account=Depends(authenticated)):
        row=await thread(app.state.store.load,account['id']);state=planner_state(row)
        repeated=any(r['id']==str(body.mutation_id) for r in row['receipts']) or (row.get('pending') or {}).get('id')==str(body.mutation_id)
        if not repeated:
            source=await context(account)
            if not source['ready']:raise Problem('Complete your selected CV and extracted Career goal first.',409,'inputs_missing')
            config=saved_config(state)
            report=Capacity(config,app.state.clock(),completed_sessions(state['active'])).report(allow_past_start=bool(state['active']))
            if not report['can_generate']:raise Problem(' '.join(i['message'] for i in report['issues']),409,'generation_blocked')
        row=await thread(begin,app.state.store,account['id'],body,'generate',PLANNING_SECONDS)
        if row.get('pending'):launch(app,account['id'],account['token'],worker)
        return {'version':row['version'],'operation':operation_view(row)}

    @app.post(prefix+'/accept',response_model=Workspace)
    async def accept(body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row)
            if not state['candidate']:raise Problem('There is no previewed roadmap to accept.')
            blockers=candidate_blockers(state,source,app.state.clock())
            if blockers:raise Problem(blockers[0]['message'],409,blockers[0]['code'])
            state['active']=state['candidate'];state['candidate']=None
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/discard',response_model=Workspace)
    async def discard(body:Mutation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            planner_state(row)['candidate']=None
            return row
        return await mutate(body,account,apply)

    def active_plan(row):
        plan=planner_state(row)['active']
        if not plan:raise Problem('Accept a roadmap before recording progress.')
        return plan

    @app.post(prefix+'/assignments/status',response_model=Workspace)
    async def assignment_status(body:AssignmentStatus,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=active_plan(row)
            tasks=ensure_tasks(copy.deepcopy(plan))
            task=next((t for t in tasks if not t.get('removed') and (t['id']==body.assignment_id or any(str(uuid5(NAMESPACE_URL,t['id']+':slot:'+str(i)))==body.assignment_id for i in range(1,len(t['schedule']))))),None)
            if not task:raise Problem('This session was not found.',404,'not_found')
            if len(task['schedule'])!=1:raise Problem('This task has multiple sessions. Update its status using the task endpoint.',409,'task_status_required')
            desired='completed' if body.status=='completed' else 'not_started'
            note=(body.evidence_note or '').strip() or None
            if task['status']==desired and (desired!='completed' or task.get('evidence_note')==note) and not task.get('definition_review_required'):return row
            task=next(t for t in ensure_tasks(plan) if t['id']==task['id'])
            change_status(task,desired,body.evidence_note)
            project_assignments(plan)
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/milestones/outcome',response_model=Workspace)
    async def milestone_outcome(body:MilestoneOutcome,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            milestone=next((m for m in active_plan(row)['milestones'] if m['id']==body.milestone_id),None)
            if not milestone:raise Problem('This milestone was not found.',404,'not_found')
            note=(body.note or '').strip()
            if body.demonstrated and not note:raise Problem('Describe how you demonstrated this outcome.',422,'validation')
            milestone['outcome']={'demonstrated':body.demonstrated,'note':note or None,'recorded_at':stamp(),'source':'self_reported'}
            return row
        return await mutate(body,account,apply)

    @app.post(prefix+'/confirmations',response_model=Workspace)
    async def confirmation(body:ExperienceConfirmation,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            state=planner_state(row)
            plan=state['candidate'] or state['active']
            gap=next((g for g in (plan or {}).get('gaps',[]) if g['id']==body.gap_id),None)
            if not gap:raise Problem('This question was not found in your plan.',404,'not_found')
            state['confirmations'][body.gap_id]={'name':gap['name'],'question':gap.get('confirmation_question'),'answer':body.answer,
                'note':(body.note or '').strip() or None,'source':'self_reported','recorded_at':stamp()}
            return row
        return await mutate(body,account,apply)
