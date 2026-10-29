"""Authenticate asynchronously before bounded database worker execution."""
from uuid import UUID
from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pymongo.errors import PyMongoError
from app.core.auth import bearer, current_account
from app.domain import targets
from app.schemas.targets import ConfirmTarget, ConfirmedContext, SelectTarget, Selection, Target, TargetCreate, Targets
from app.schemas.preview import ImportErrorView
from app.repositories.targets import TargetRepository

router = APIRouter(prefix='/api/v1/career/targets', tags=['J09 reviewed target context'],
    responses={status: {'model': ImportErrorView} for status in (401, 403, 404, 409, 413, 422, 503)})


async def authenticated(request: Request, credentials=Depends(bearer)):
    return await current_account(request, credentials)


async def run(request, function, *args):
    def execute():
        repository = request.app.state.target_repository
        if repository is None:
            database = request.app.state.target_database
            if database is None: raise HTTPException(503, 'Saved career targets are unavailable. Please retry later.')
            repository = TargetRepository(database)
            request.app.state.target_repository = repository
        return function(repository, *args)
    try:
        return await to_thread.run_sync(execute, limiter=request.app.state.target_limiter)
    except PyMongoError as exc:
        raise HTTPException(503, 'Saved career targets are unavailable. Your changes were not confirmed; retry with the same request.') from exc


@router.get('', response_model=Targets)
async def list_targets(request: Request, cursor: str | None = Query(default=None, min_length=1, max_length=512), owner=Depends(authenticated)):
    return await run(request, targets.list_targets, owner, cursor)


@router.post('', response_model=Target, status_code=201)
async def create_target(data: TargetCreate, request: Request, owner=Depends(authenticated)):
    return await run(request, targets.create, owner, data)


@router.put('/selection', response_model=Selection)
async def select_target(data: SelectTarget, request: Request, owner=Depends(authenticated)):
    return await run(request, targets.select, owner, data)


@router.get('/selected-context', response_model=ConfirmedContext | None)
async def current_context(request: Request, owner=Depends(authenticated)):
    return await run(request, targets.selected_context, owner)


@router.get('/{identifier}', response_model=Target)
async def read_target(identifier: UUID, request: Request, owner=Depends(authenticated)):
    return await run(request, lambda repository, owner, identifier: targets.present(targets.get_target(repository, owner, identifier)), owner, str(identifier))


@router.post('/{identifier}/confirm', response_model=Target)
async def confirm_target(identifier: UUID, data: ConfirmTarget, request: Request, owner=Depends(authenticated)):
    return await run(request, targets.confirm, owner, str(identifier), data)


@router.get('/{identifier}/confirmed-context', response_model=ConfirmedContext)
async def confirmed_context(identifier: UUID, request: Request, expected_version: int = Query(ge=1), owner=Depends(authenticated)):
    return await run(request, targets.selected_context, owner, str(identifier), expected_version)
