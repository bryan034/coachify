"""About the role digest, scoped to the owner's current goal version and latest research."""
from fastapi import APIRouter,Depends,Request
from fastapi.encoders import jsonable_encoder
from app.api.v1.goals import owner
from app.api.v1.interview_prep import owned_goal,research_state
from app.repositories.goals import GoalError
from app.schemas.role_summary import SummaryCommand
from app.workflows import role_summary as digest

router=APIRouter(prefix='/api/v1/career/goals',tags=['About the role summary'])


@router.get('/{goal_id}/role-summary')
async def read(goal_id:str,request:Request,account=Depends(owner)):
    goal=await owned_goal(request,account,goal_id)
    finished,record=await research_state(request,account,goal)
    saved=await digest.read_saved(request,account,goal,record)
    return jsonable_encoder({'status':'ready' if saved else 'researching' if not finished else 'missing','summary':saved})


@router.post('/{goal_id}/role-summary')
async def generate(goal_id:str,body:SummaryCommand,request:Request,account=Depends(owner)):
    goal=await owned_goal(request,account,goal_id)
    if goal.version!=body.expected_version:raise GoalError('The current career goal changed. Reload before generating.')
    finished,record=await research_state(request,account,goal)
    # Cards change while research adds findings; summarise once it settles.
    if not finished:raise GoalError('Role research is still running. The summary is generated when it finishes.')
    if not body.refresh:
        saved=await digest.read_saved(request,account,goal,record)
        if saved:return jsonable_encoder({'status':'ready','summary':saved})
    return jsonable_encoder({'status':'ready','summary':await digest.generate(request,account,goal,record)})
