from typing import Annotated
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Header
from app.core.auth import current_owner
from app.domain import schools
from app.domain.profile import ProfileValidationError, present_profile
from app.repositories.profile import VersionConflict, MutationConflict
from app.domain.errors import PeriodNotFound
from app.domain.planning import planning_inputs
from app.schemas.planning import PeriodCreate, PeriodEdit, PlanningInputs, CalendarDate, DeviceZone
from app.schemas.profile import ProfilePatch, ProfileView, SchoolCategory

from app.schemas.schools import AuthConfigView, CategoryView, CountryView, InstitutionResults

router = APIRouter(prefix="/api/v1/profile")


def repository(request: Request):
    return request.app.state.repository


@router.get("/auth-config", response_model=AuthConfigView)
def auth_config(request: Request):
    # Describes the validated server mode; this endpoint cannot change authentication.
    return {"mode": request.app.state.auth_settings.mode}


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
    return present_profile(repo.current(owner))


def write_result(action):
    try:
        return present_profile(action())
    except ProfileValidationError as exc:
        raise HTTPException(422, [{"loc": ["body", *exc.field.split(".")], "msg": exc.message, "type": "value_error"}]) from exc
    except MutationConflict as exc:
        raise HTTPException(409, "This request key was already used for different changes. Start a new save after reviewing your draft.") from exc
    except VersionConflict as exc:
        raise HTTPException(409, "Your profile changed elsewhere. Reload the latest values and reconcile your draft before saving again.") from exc
    except PeriodNotFound as exc:
        raise HTTPException(404, "This availability period no longer exists. Reload and review your draft.") from exc


def request_key(value):
    if value is None:
        raise HTTPException(422, [{"loc": ["header", "Idempotency-Key"], "msg": "Supply a unique Idempotency-Key for this save; reuse it only when retrying the same request.", "type": "value_error"}])
    return value


MutationKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


@router.patch("", response_model=ProfileView)
def patch_profile(patch: ProfilePatch, owner: Annotated[str, Depends(current_owner)],
                  idempotency_key: MutationKey = None, repo=Depends(repository)):
    if patch.model_fields_set & {"application_date", "weekly_hours", "time_zone"}:
        key = request_key(idempotency_key)
        return write_result(lambda: repo.update(owner, patch, mutation_id=key))
    return write_result(lambda: repo.update(owner, patch))


@router.post("/availability-periods", response_model=ProfileView, status_code=201)
def add_period(period: PeriodCreate, owner: Annotated[str, Depends(current_owner)],
               idempotency_key: MutationKey = None, repo=Depends(repository)):
    key = request_key(idempotency_key)
    return write_result(lambda: repo.change_period(owner, "add", None, period.expected_version,
                        period.model_dump(exclude={"expected_version"}), key))


@router.patch("/availability-periods/{period_id}", response_model=ProfileView)
def edit_period(period_id: str, period: PeriodEdit, owner: Annotated[str, Depends(current_owner)],
                idempotency_key: MutationKey = None, repo=Depends(repository)):
    key = request_key(idempotency_key)
    return write_result(lambda: repo.change_period(owner, "edit", period_id, period.expected_version,
                        period.model_dump(exclude={"expected_version"}, exclude_unset=True), key))


@router.delete("/availability-periods/{period_id}", response_model=ProfileView)
def delete_period(period_id: str, owner: Annotated[str, Depends(current_owner)], expected_version: int = Query(ge=0),
                  idempotency_key: MutationKey = None, repo=Depends(repository)):
    key = request_key(idempotency_key)
    return write_result(lambda: repo.change_period(owner, "delete", period_id, expected_version, {}, key))


@router.get("/planning-inputs", response_model=PlanningInputs)
def get_planning_inputs(owner: Annotated[str, Depends(current_owner)], time_zone: DeviceZone,
                        start_date: CalendarDate | None = None, end_date: CalendarDate | None = None,
                        repo=Depends(repository)):
    if (start_date is None) != (end_date is None):
        raise HTTPException(422, "Provide both start_date and end_date for a capacity window.")
    try:
        return planning_inputs(repo.current(owner), time_zone,
                               date.fromisoformat(start_date) if start_date else None,
                               date.fromisoformat(end_date) if end_date else None)
    except ProfileValidationError as exc:
        raise HTTPException(422, [{"loc": ["query", exc.field], "msg": exc.message, "type": "value_error"}]) from exc


@router.get("/versions/{version}", response_model=ProfileView)
def get_version(version: int, owner: Annotated[str, Depends(current_owner)], repo=Depends(repository)):
    profile = repo.version(owner, version)
    if profile is None:
        raise HTTPException(404, "Profile version not found.")
    return present_profile(profile)
