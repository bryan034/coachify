from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from app.core.auth import current_owner
from app.domain import schools
from app.repositories.profile import VersionConflict
from app.schemas.profile import ProfilePatch, ProfileView, SchoolCategory

from app.schemas.schools import CategoryView, CountryView, InstitutionResults

router = APIRouter(prefix="/api/v1/profile")


def repository(request: Request):
    return request.app.state.repository


@router.get("/school-categories", response_model=list[CategoryView])
def school_categories():
    return schools.categories()


@router.get("/school-countries", response_model=list[CountryView])
def school_countries():
    return schools.countries()


@router.get("/institutions", response_model=InstitutionResults)
def institutions(category: SchoolCategory, q: str = Query("", max_length=150),
                 country: str | None = Query(None, pattern="^[A-Z]{2}$"),
                 offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return schools.search(category, q.strip(), country, offset, limit)


@router.get("", response_model=ProfileView)
def get_profile(owner: Annotated[str, Depends(current_owner)], repo=Depends(repository)):
    return repo.current(owner) or ProfileView(version=0)


@router.patch("", response_model=ProfileView)
def patch_profile(patch: ProfilePatch, owner: Annotated[str, Depends(current_owner)], repo=Depends(repository)):
    try:
        return repo.update(owner, patch)
    except VersionConflict as exc:
        raise HTTPException(409, "Your profile changed elsewhere. Reload before saving again.") from exc


@router.get("/versions/{version}", response_model=ProfileView)
def get_version(version: int, owner: Annotated[str, Depends(current_owner)], repo=Depends(repository)):
    profile = repo.version(owner, version)
    if profile is None:
        raise HTTPException(404, "Profile version not found.")
    return profile
