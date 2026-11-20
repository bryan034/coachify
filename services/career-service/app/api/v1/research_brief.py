"""Version 2 research briefs for the About the role and Interview preparation tabs, scoped to the owner's current goal and research."""
import asyncio

from fastapi import APIRouter,Depends,Request
from app.api.v1.dependencies import owner
from app.api.v1.interview_prep import owned_goal,research_state
from app.repositories.goals import GoalError
from app.schemas.research_brief import BriefCommand,InterviewBriefView,RoleBriefView
from app.workflows import research_brief as briefs

router=APIRouter(prefix='/api/v1/career/goals',tags=['Research briefs (v2)'])


async def generate_once(request,account,goal,record,tab):
    pending=request.app.state.brief_tasks
    key=(account,goal.id,goal.version,briefs.research_key(record),tab)
    task=pending.get(key)
    if task is None:
        task=asyncio.create_task(briefs.generate(request,account,goal,record,tab))
        pending[key]=task

        def finished(completed):
            pending.pop(key)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
    return await asyncio.shield(task)


async def read_view(request,account,goal_id,tab):
    goal=await owned_goal(request,account,goal_id)
    finished,record=await research_state(request,account,goal)
    saved=await briefs.read_saved(request,account,goal,record,tab)
    return {'status':'ready' if saved else 'researching' if not finished else 'missing','brief':saved}


async def generate_view(request,account,goal_id,body,tab):
    goal=await owned_goal(request,account,goal_id)
    if goal.version!=body.expected_version:raise GoalError('The current career goal changed. Reload before generating.')
    finished,record=await research_state(request,account,goal)
    if not finished:raise GoalError('Research is still running. The brief is generated when it finishes.')
    if not body.refresh:
        saved=await briefs.read_saved(request,account,goal,record,tab)
        if saved:return {'status':'ready','brief':saved}
    return {'status':'ready','brief':await generate_once(request,account,goal,record,tab)}


@router.get('/{goal_id}/v2/role-research',response_model=RoleBriefView)
async def read_role(goal_id:str,request:Request,account=Depends(owner)):
    return await read_view(request,account,goal_id,'role')


@router.post('/{goal_id}/v2/role-research',response_model=RoleBriefView)
async def generate_role(goal_id:str,body:BriefCommand,request:Request,account=Depends(owner)):
    return await generate_view(request,account,goal_id,body,'role')


@router.get('/{goal_id}/v2/interview-research',response_model=InterviewBriefView)
async def read_interview(goal_id:str,request:Request,account=Depends(owner)):
    return await read_view(request,account,goal_id,'interview')


@router.post('/{goal_id}/v2/interview-research',response_model=InterviewBriefView)
async def generate_interview(goal_id:str,body:BriefCommand,request:Request,account=Depends(owner)):
    return await generate_view(request,account,goal_id,body,'interview')
