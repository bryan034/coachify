from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Request
from elo_shared.skills_profile import SkillsProfile, SkillsProfileWrite
from app.core.auth import current_owner
from app.domain.capabilities import CapabilityConflict
from app.repositories.skills_profile import SkillsProfileRepository

router = APIRouter(prefix='/api/v1/profile/skills-profile', tags=['Skills profile'])


def repository(request: Request):
    capabilities = getattr(request.app.state, 'capabilities', None)
    if capabilities is None:
        raise HTTPException(503, 'Skills profile storage is unavailable. Keep your draft and retry.')
    return SkillsProfileRepository(capabilities)


@router.get('', response_model=SkillsProfile)
def read(owner: Annotated[str, Depends(current_owner)], repo=Depends(repository)):
    return repo.current(owner)


@router.put('', response_model=SkillsProfile)
def save(data: SkillsProfileWrite, owner: Annotated[str, Depends(current_owner)], repo=Depends(repository)):
    try:
        return repo.save(owner, data)
    except CapabilityConflict as exc:
        raise HTTPException(409, exc.message) from exc
