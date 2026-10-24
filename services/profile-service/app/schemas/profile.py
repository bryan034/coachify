from app.schemas.planning import CalendarDate, DeviceZone, BaseHours, AvailabilityPeriod
from datetime import datetime
from zoneinfo import ZoneInfo
from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator


class OccupationalStatus(StrEnum):
    STUDENT = "student"
    NATIONAL_SERVICE = "national_service"
    UNEMPLOYED = "unemployed"
    EMPLOYED = "employed"


class SchoolCategory(StrEnum):
    SECONDARY = "secondary"
    ITE = "ite"
    POLYTECHNIC = "polytechnic"
    JUNIOR_COLLEGE = "junior_college"
    UNIVERSITY = "university"


CATEGORY_LABELS = {
    SchoolCategory.SECONDARY: "Secondary School",
    SchoolCategory.ITE: "Institute of Technical Education",
    SchoolCategory.POLYTECHNIC: "Polytechnic / Diploma",
    SchoolCategory.JUNIOR_COLLEGE: "Junior College",
    SchoolCategory.UNIVERSITY: "University",
}


def clean_text(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Enter a text name or description.")
    value = value.strip()
    if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Enter a nonblank name or description without control characters.")
    return value


class CatalogueInstitution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["catalogue"]
    id: Annotated[str, Field(min_length=1, max_length=80)]


class CustomInstitution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["custom"]
    name: Annotated[str, Field(max_length=300)]
    country_code: Annotated[str, Field(pattern="^[A-Z]{2}$")] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def name_is_valid(cls, value):
        return clean_text(value)


InstitutionInput = Annotated[CatalogueInstitution | CustomInstitution, Field(discriminator="kind")]


class EducationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    institution: InstitutionInput | None = None
    course: Annotated[str, Field(max_length=300)] | None = None
    study_year: Annotated[int, Field(strict=True, gt=0)] | None = None

    graduation_year: Annotated[int, Field(strict=True, ge=1900, le=9999)] | None = None

    @field_validator("graduation_year")
    @classmethod
    def graduation_is_past_or_current(cls, value):
        if value is not None and value > datetime.now(ZoneInfo("Asia/Singapore")).year:
            raise ValueError("Graduation year cannot be in the future.")
        return value

    @field_validator("course", mode="before")
    @classmethod
    def course_is_valid(cls, value):
        return clean_text(value) if value is not None else None

    @model_validator(mode="after")
    def validate_year(self):
        if "study_year" in self.model_fields_set and self.study_year is None:
            raise ValueError("Study year must be a positive whole number, not null.")
        return self


class SavedInstitution(BaseModel):
    kind: Literal["catalogue", "custom"]
    id: str | None = None
    name: str
    country_code: str | None = None
    snapshot_date: str | None = None


class EducationView(BaseModel):
    model_config = ConfigDict(extra="allow")
    institution: SavedInstitution | None = None
    course: str | None = None
    study_year: int | None = None
    graduation_year: int | None = None
    study_year_label: str | None = None
    study_year_category: SchoolCategory | None = None
    category: SchoolCategory | None = None
    context: Literal["current", "last"] | None = None


class EmploymentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employer: Annotated[str, Field(max_length=300)] | None = None
    role: Annotated[str, Field(max_length=300)] | None = None

    industry: Annotated[str, Field(max_length=300)] | None = None

    @field_validator("employer", "role", "industry", mode="before")
    @classmethod
    def text_is_valid(cls, value):
        return clean_text(value) if value is not None else None


class EmploymentView(BaseModel):
    employer: str | None = None
    role: str | None = None
    industry: str | None = None


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Annotated[int, Field(strict=True, ge=0)]
    application_date: CalendarDate | None = None
    time_zone: DeviceZone | None = None
    weekly_hours: BaseHours | None = None
    occupational_status: OccupationalStatus | None = None
    school_category: SchoolCategory | None = None
    education: EducationPatch | None = None
    employment: EmploymentPatch | None = None
    previously_employed: Annotated[bool, Field(strict=True)] | None = None
    no_previous_education: Annotated[bool, Field(strict=True)] | None = None
    confirm_education_context: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def validate_supplied_fields(self):
        for name in ("application_date", "time_zone", "weekly_hours"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null.")
        if "occupational_status" in self.model_fields_set and self.occupational_status is None:
            raise ValueError("Occupational status cannot be null.")
        if "education" in self.model_fields_set and self.education is None:
            raise ValueError("Update individual education fields instead of clearing all education.")
        if "employment" in self.model_fields_set and self.employment is None:
            raise ValueError("Update individual employment fields instead of clearing all employment.")
        if self.model_fields_set <= {"expected_version"}:
            raise ValueError("Supply at least one profile field to update.")
        return self


class ProfileView(BaseModel):
    version: int
    onboarding_complete: bool = False
    onboarding_completed_at: str | None = None
    onboarding_state: Literal["missing", "incomplete", "legacy_unconfirmed", "complete"] = "missing"
    no_previous_education: bool = False
    previously_employed: bool | None = None
    application_date: CalendarDate | None = None
    application_time_zone: str | None = None
    weekly_hours: float | None = None
    availability_periods: list[AvailabilityPeriod] = Field(default_factory=list)
    planning_revision: int = 0
    occupational_status: OccupationalStatus | None = None
    school_category: SchoolCategory | None = None
    education_context: Literal["current", "last"] | None = None
    education_review_required: bool = False
    education: EducationView = Field(default_factory=EducationView)
    employment: EmploymentView = Field(default_factory=EmploymentView)
    current_study_year: int | None = None
