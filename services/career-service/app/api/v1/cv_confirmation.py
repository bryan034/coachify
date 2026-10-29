"""Career-owned acknowledgement endpoints for the CV clarification boundary."""
from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool
from app.api.v1.goals import owner, store, identifier
from app.confirmation.service import CvConfirmationService
from app.schemas.cv_confirmation import ConfirmCvGoal, CvConfirmationView, CvConfirmedContext

router=APIRouter(prefix='/api/v1/career/goals',tags=['Canonical goal CV confirmation'])


def service(request): return CvConfirmationService(store(request))


@router.get('/current/cv-confirmation',response_model=CvConfirmationView)
async def read(request:Request, account=Depends(owner)):
    return await run_in_threadpool(service(request).view,account)


@router.post('/current/cv-confirmation',response_model=CvConfirmationView)
async def confirm(data:ConfirmCvGoal,request:Request,account=Depends(owner)):
    return await run_in_threadpool(service(request).confirm,account,data)


@router.get('/current/confirmed-context',response_model=CvConfirmedContext|None)
async def selected_context(request:Request,account=Depends(owner)):
    return await run_in_threadpool(service(request).context,account)


@router.get('/{goal_id}/confirmed-context',response_model=CvConfirmedContext)
async def confirmed_context(goal_id:str,request:Request,expected_version:int=Query(ge=1),account=Depends(owner)):
    return await run_in_threadpool(service(request).context,account,identifier(goal_id),expected_version)
