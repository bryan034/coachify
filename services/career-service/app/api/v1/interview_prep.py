"""AI-generated fills for empty interview-preparation slots, scoped to the owner's current goal and research."""
from fastapi import APIRouter,Depends,Request
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.api.v1.goals import owner,identifier
from app.repositories.goals import GoalError
from app.schemas.interview_prep import SuggestCommand
from app.workflows import interview_prep as prep

router=APIRouter(prefix='/api/v1/career/goals',tags=['Interview preparation suggestions'])


async def owned_goal(request,account,goal_id):
    state=await thread(request.app.state.goal_store.current,account)
    goal=state['goal']
    if not goal or goal.id!=identifier(goal_id):raise GoalError('This career goal was not found.',404)
    return goal


async def research_state(request,account,goal):
    """(finished, record) for the latest research of this goal version; no research counts as finished."""
    service=getattr(request.app.state,'opportunities',None)
    if service is None:return True,None
    job=await thread(service.store.latest,account,goal.id,goal.version)
    if not job:return True,None
    record=await thread(service.store.research.records.get_research,job['research_id']) if job.get('research_id') else None
    return bool(job.get('finished',True)),record


@router.get('/{goal_id}/interview-prep')
async def read(goal_id:str,request:Request,account=Depends(owner)):
    goal=await owned_goal(request,account,goal_id)
    finished,record=await research_state(request,account,goal)
    saved=await prep.read_saved(request,account,goal,record)
    return jsonable_encoder({'status':'ready' if saved else 'researching' if not finished else 'missing','suggestions':saved})


@router.post('/{goal_id}/interview-prep')
async def generate(goal_id:str,body:SuggestCommand,request:Request,account=Depends(owner)):
    goal=await owned_goal(request,account,goal_id)
    if goal.version!=body.expected_version:raise GoalError('The current career goal changed. Reload before generating.')
    finished,record=await research_state(request,account,goal)
    # Gaps are only known once research stops adding findings.
    if not finished:raise GoalError('Interview research is still running. Suggestions are generated when it finishes.')
    if not body.refresh:
        saved=await prep.read_saved(request,account,goal,record)
        if saved:return jsonable_encoder({'status':'ready','suggestions':saved})
    suggestions=await prep.generate(request,account,goal,record)
    return jsonable_encoder({'status':'ready','suggestions':suggestions})
