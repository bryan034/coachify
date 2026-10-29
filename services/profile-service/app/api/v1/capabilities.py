from typing import Annotated
from functools import partial
from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from app.clients.cv import validate_cv_match
from app.core.auth import current_owner
from app.domain.capabilities import CapabilityConflict, CapabilityLimit
from app.schemas.capabilities import CapabilityAttachment, CapabilityCreate, CapabilityView, CapabilityError

router = APIRouter(prefix="/api/v1/profile/capabilities", tags=["C07 manual capabilities"])


def repository(request: Request):
    result = getattr(request.app.state, "capabilities", None)
    if result is None:
        raise HTTPException(503, "Capability storage is unavailable. Keep your draft and retry.")
    return result


@router.get("", response_model=CapabilityView, responses={401: {"model": CapabilityError}, 503: {"model": CapabilityError}})
def get_capabilities(owner: Annotated[str, Depends(current_owner)], repo=Depends(repository)):
    return repo.current(owner)


@router.post("", response_model=CapabilityView, responses={401: {"model": CapabilityError},
    409: {"model": CapabilityError}, 503: {"model": CapabilityError}})
async def add_capability(data: CapabilityCreate, request: Request,
                   owner: Annotated[str, Depends(current_owner)], repo=Depends(repository)):
    try:
        operation = partial(repo.create, owner, data, lambda: validate_cv_match(data.cv_match, data.name,
                                                               request.headers.get("Authorization", "")))
        return await to_thread.run_sync(operation, limiter=request.app.state.capability_limiter)
    except CapabilityConflict as exc:
        content = {"detail": exc.message, "code": exc.code}
        if exc.matches is not None:
            content["matches"] = exc.matches
        return JSONResponse(status_code=409, content=content)
    except CapabilityLimit as exc:
        raise HTTPException(422, [{"loc": ["body"], "msg": str(exc), "type": "value_error"}]) from exc


@router.post("/attachment", response_model=CapabilityView, responses={401: {"model": CapabilityError},
    409: {"model": CapabilityError}, 503: {"model": CapabilityError}})
async def reconcile_attachment(data: CapabilityAttachment, request: Request,
                   owner: Annotated[str, Depends(current_owner)], repo=Depends(repository)):
    try:
        operation = partial(repo.attachment, owner, data, lambda name: validate_cv_match(data.cv_match, name,
                                                               request.headers.get("Authorization", "")))
        return await to_thread.run_sync(operation, limiter=request.app.state.capability_limiter)
    except CapabilityConflict as exc:
        return JSONResponse(status_code=409, content={"detail": exc.message, "code": exc.code})
    except CapabilityLimit as exc:
        raise HTTPException(422, [{"loc": ["body"], "msg": str(exc), "type": "value_error"}]) from exc
