"""To-do session endpoints. Writes reuse the workspace's version and receipt protection."""
import copy
from uuid import NAMESPACE_URL, uuid5
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated
from app.planning.sessions import backlog_plan, calendar, free_times, move_session, new_task, save_session, skip_session
from app.planning.state import planner_state
from app.planning.tasks import ensure_tasks, project_assignments
from app.schemas.planner import Workspace
from app.schemas.roadmap import AddSession, BacklogPlan, BacklogPlanRequest, FreeTimes, FreeTimesRequest, MoveSessions, SaveSession, SkipSession


def register_session_routes(app,context,mutate):
    prefix='/api/v1/roadmaps/planner/sessions'
    def active(row):
        plan=planner_state(row)['active']
        if not plan:raise Problem('There is no active roadmap yet.',404,'not_found')
        return plan
    async def snapshot(account):
        """A projected copy for read-only calculations; nothing is saved."""
        row=await thread(app.state.store.load,account['id']);plan=copy.deepcopy(active(row))
        ensure_tasks(plan);project_assignments(plan)
        return row,plan

    @app.post(prefix+'/free-times',response_model=FreeTimes)
    async def times(body:FreeTimesRequest,request:Request,account=Depends(authenticated)):
        """Free start times for one task from today to the end of next week."""
        row,plan=await snapshot(account)
        return {'version':row['version'],**free_times(plan,app.state.clock(),body.duration_minutes,body.session_id)}

    @app.post(prefix+'/backlog-plan',response_model=BacklogPlan)
    async def propose(body:BacklogPlanRequest,request:Request,account=Depends(authenticated)):
        """Suggested times for missed sessions. Nothing moves until they are sent to /move."""
        row,plan=await snapshot(account)
        return {'version':row['version'],'moves':backlog_plan(plan,app.state.clock(),body.session_ids)}

    @app.post(prefix+'/move',response_model=Workspace)
    async def move(body:MoveSessions,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=active(row);capacity=calendar(plan,app.state.clock())
            if len({item.session_id for item in body.moves})!=len(body.moves):raise Problem('Move each task only once.',422,'validation')
            # Each move is checked against the ones before it, so a batch cannot overlap itself.
            for item in body.moves:move_session(plan,capacity,item.session_id,item.date,item.start_time)
            project_assignments(plan);return row
        return await mutate(body,account,apply,operation='sessions.move')

    @app.post(prefix+'/save',response_model=Workspace)
    async def save(body:SaveSession,request:Request,account=Depends(authenticated)):
        """Save a task's details in one step. Notes and ratings never change status or assessed skills."""
        def apply(row,source):
            plan=active(row);ensure_tasks(plan);project_assignments(plan)
            save_session(plan,calendar(plan,app.state.clock()),source,body.session_id,
                body.changes.model_dump(mode='json',exclude_unset=True),body.allow_overlap)
            project_assignments(plan);return row
        return await mutate(body,account,apply,operation='sessions.save')

    @app.post(prefix+'/add',response_model=Workspace)
    async def add(body:AddSession,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=active(row)
            if len(ensure_tasks(plan))>=1000:raise Problem('This roadmap reached its task capacity.',413,'workspace_capacity')
            identifier=str(uuid5(NAMESPACE_URL,account['id']+':task:'+str(body.mutation_id)))
            new_task(plan,calendar(plan,app.state.clock()),source,identifier,body.session.model_dump(mode='json'),body.allow_overlap)
            project_assignments(plan);return row
        return await mutate(body,account,apply,operation='sessions.add')

    @app.post(prefix+'/skip',response_model=Workspace)
    async def skip(body:SkipSession,request:Request,account=Depends(authenticated)):
        def apply(row,source):
            plan=active(row);skip_session(plan,calendar(plan,app.state.clock()),body.session_id)
            project_assignments(plan);return row
        return await mutate(body,account,apply,operation='sessions.skip')
