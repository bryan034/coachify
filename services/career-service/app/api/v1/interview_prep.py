"""Keyword-only interview preparation guide; only for a specific job, never for career exploration."""
from fastapi import APIRouter,Depends,Request
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.api.v1.goals import owner,identifier,selected_cv
from app.repositories.goals import GoalError
from app.schemas.interview_prep import PrepCommand
from app.workflows import interview_prep as prep

router=APIRouter(prefix='/api/v1/career/goals',tags=['Interview preparation guide'])


async def owned_goal(request,account,goal_id):
    state=await thread(request.app.state.goal_store.current,account)
    goal=state['goal']
    if not goal or goal.id!=identifier(goal_id):raise GoalError('This career goal was not found.',404)
    prep.require_specific_job(goal)
    return goal


async def research_record(request,account,goal):
    service=getattr(request.app.state,'opportunities',None)
    if service is None:return None
    job=await thread(service.store.latest,account,goal.id,goal.version)
    if not job or not job.get('research_id'):return None
    return await thread(service.store.research.records.get_research,job['research_id'])


async def cv_snapshot(request,account,goal):
    if not goal.source_cv_id:return None
    try:return await selected_cv(request,goal.source_cv_id,account)
    except Exception:return None  # The guide still works without a resume map.


@router.get('/{goal_id}/interview-prep')
async def read(goal_id:str,request:Request,account=Depends(owner)):
    goal=await owned_goal(request,account,goal_id)
    guide=await prep.read_saved(request,account,goal)
    return jsonable_encoder({'status':'ready' if guide else 'missing','guide':guide})


@router.post('/{goal_id}/interview-prep')
async def generate(goal_id:str,body:PrepCommand,request:Request,account=Depends(owner)):
    goal=await owned_goal(request,account,goal_id)
    if goal.version!=body.expected_version:raise GoalError('The current career goal changed. Reload before generating.')
    if not body.refresh:
        saved=await prep.read_saved(request,account,goal)
        if saved and saved.interview_date==body.interview_date:return jsonable_encoder({'status':'ready','guide':saved})
    guide=await prep.generate(request,account,goal,await research_record(request,account,goal),
        await cv_snapshot(request,account,goal),body.interview_date)
    return jsonable_encoder({'status':'ready','guide':guide})
