"""To-do session endpoints. Writes reuse the workspace's version and receipt protection."""
import copy
from uuid import NAMESPACE_URL, uuid5
from fastapi import Depends, Request
from starlette.concurrency import run_in_threadpool as thread
from elo_shared.runtime import Problem, authenticated, stamp
from app.planning.sessions import locate, check_time, place, record_edit, task_day, backlog_plan, calendar, free_times, new_task, save_session, skip_session
from app.planning.state import planner_state
from app.planning.tasks import ensure_tasks, project_assignments
from app.schemas.planner import Workspace
from app.schemas.roadmap import AddSession, BacklogPlan, BacklogPlanRequest, FreeTimes, FreeTimesRequest, MoveSessions, SaveSession, SkipSession


def register_session_routes(app,mutate):
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
        def apply(row,_source):
            plan=active(row);capacity=calendar(plan,app.state.clock())
            if len({item.session_id for item in body.moves})!=len(body.moves):raise Problem('Move each task only once.',422,'validation')
            # Release all moving slots before validating the final schedule.
            prepared=[]
            for item in body.moves:
                task,index=locate(plan,item.session_id)
                if task['status']=='completed':raise Problem('A finished task cannot be moved. Untick it first.',409,'session_completed')
                minutes=task['estimated_minutes'] if index is None else task['schedule'][index]['duration_minutes']
                prepared.append((item,task,index,minutes,task_day(task,index),copy.deepcopy(task.get('schedule') or [])))
            moving={(task['id'],index) for _,task,index,_,_,_ in prepared}
            final=copy.deepcopy(plan)
            for task in ensure_tasks(final):
                task['schedule']=[slot for index,slot in enumerate(task.get('schedule') or []) if (task['id'],index) not in moving]
                if (task['id'],None) in moving:task['anytime_date']=None
            placed=[]
            for item,task,index,minutes,old_day,previous in prepared:
                check_time(final,capacity,None,item.date,item.start_time,minutes,strict=True,extra=placed)
                placed.append((task['title'],{'date':item.date.isoformat(),'start_time':item.start_time,'duration_minutes':minutes}))
            for item,task,index,minutes,old_day,previous in prepared:
                place(task,index,item.date,item.start_time,minutes,update_estimate=False)
                if old_day<capacity.today.isoformat():
                    task['backlog_moved_at']=stamp()
                record_edit(task,{'schedule':previous,**({'anytime_date':old_day} if index is None else {})})
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
        def apply(row,_source):
            plan=active(row);skip_session(plan,calendar(plan,app.state.clock()),body.session_id)
            project_assignments(plan);return row
        return await mutate(body,account,apply,operation='sessions.skip')
