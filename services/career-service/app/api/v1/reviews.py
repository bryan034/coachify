"""J02–J04 structured review readback and atomic corrections."""
from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from app.api.v1.goals import identifier, owner, request_key
from app.repositories.goals import GoalError
from app.schemas.jd import SaveReview, JDExtractionResult

router=APIRouter(prefix='/api/v1/career/goals', tags=['J02–J04 requirement review'])


def store(request):
    if request.app.state.review_store is None:
        raise GoalError('Career storage is not configured. Check the setup guide.',503)
    return request.app.state.review_store


def view(draft):
    return {'review_id':draft.id,'version':draft.version,'target_type':draft.target_type,
            'extraction':draft.content,'baseline':draft.baseline,'generation':draft.generation,
            'metadata_origins':draft.metadata_origins,'requirements_need_review':draft.requirements_need_review,
            'is_confirmed':draft.base_goal_id == draft.id}


@router.get('/{goal_id}',response_model=JDExtractionResult)
async def read(goal_id:str, request:Request, account=Depends(owner)):
    return view(await run_in_threadpool(store(request).get,identifier(goal_id),account))


@router.patch('/{goal_id}/review',response_model=JDExtractionResult)
async def save(goal_id:str,body:SaveReview,request:Request,account=Depends(owner),key=Depends(request_key)):
    return view(await run_in_threadpool(store(request).save,identifier(goal_id),account,key,body))
