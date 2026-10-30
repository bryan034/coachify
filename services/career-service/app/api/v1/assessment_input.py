"""Read-only producer snapshot for the independently deployed Assessment service."""
from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.api.v1.goals import owner, store
from app.repositories.goals import GoalError
from elo_shared.skills import identity, MAPPING_VERSION

router=APIRouter(prefix='/api/v1/career',tags=['Assessment handoff'])

@router.get('/assessment-input')
async def assessment_input(request:Request,account=Depends(owner)):
    goals=store(request)
    first=await thread(goals.current,account); goal=first['goal']
    if not goal:
        return {'ready':False,'reason':'Save and extract your Career goal first.','goal':None,'selection_version':first['selection_version'],'research':None,'registry_version':MAPPING_VERSION}
    research_store=request.app.state.research_store
    record=await thread(research_store.read,account,goal.id,current=True,goal_version=goal.version) if research_store else None
    latest=await thread(goals.current,account)
    if latest['selection_version']!=first['selection_version'] or latest['goal'].version!=goal.version:
        raise GoalError('The selected goal changed during input assembly. Reload and retry.')
    data=goal.model_dump(mode='json',by_alias=True)
    for skill in data['skills']: skill.update(identity(skill['name'],skill['category']))
    # Mapping/importance uncertainty is an assessment outcome, not an empty goal.
    ready=bool(goal.skills or goal.non_skill_requirements) and goal.generation is not None and not goal.requirements_need_review
    return jsonable_encoder({'ready':ready,'reason':None if ready else 'Finish extracting and reviewing the goal requirements.',
        'goal':data,'selection_version':first['selection_version'],
        'research':record.model_dump(mode='json',by_alias=True) if record else None,'registry_version':MAPPING_VERSION})
