from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Annotated[int, Field(strict=True, ge=0)]
    occupational_status: OccupationalStatus
    school_category: SchoolCategory | None = None

    @model_validator(mode="after")
    def validate_education(self):
        if self.occupational_status == OccupationalStatus.STUDENT and self.school_category is None:
            raise ValueError("Choose a school category for a student profile.")
        return self


class ProfileView(BaseModel):
    version: int
    occupational_status: OccupationalStatus | None = None
    school_category: SchoolCategory | None = None
    education_context: Literal["current", "last"] | None = None
    education_review_required: bool = False
    education: dict = Field(default_factory=dict)
