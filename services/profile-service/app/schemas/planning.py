from datetime import date
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import re
from pydantic import BaseModel, ConfigDict, Field, AfterValidator, model_validator


def calendar_date(value: str) -> str:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use a calendar date in YYYY-MM-DD format.")
    date.fromisoformat(value)
    return value


def time_zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Provide a valid device IANA time-zone identifier.")
    return value


CalendarDate = Annotated[str, Field(strict=True), AfterValidator(calendar_date)]
DeviceZone = Annotated[str, Field(strict=True, min_length=1, max_length=100), AfterValidator(time_zone)]
Hours = Annotated[float, Field(strict=True, ge=0, le=168, allow_inf_nan=False)]
BaseHours = Annotated[float, Field(strict=True, gt=0, le=168, allow_inf_nan=False)]
Version = Annotated[int, Field(strict=True, ge=0)]


class AvailabilityPeriod(BaseModel):
    id: str
    start_date: CalendarDate
    end_date: CalendarDate
    weekly_hours: Hours


class PeriodCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Version
    start_date: CalendarDate
    end_date: CalendarDate
    weekly_hours: Hours


class PeriodEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: Version
    start_date: CalendarDate | None = None
    end_date: CalendarDate | None = None
    weekly_hours: Hours | None = None

    @model_validator(mode="after")
    def supplied(self):
        fields = self.model_fields_set - {"expected_version"}
        if not fields or any(getattr(self, field) is None for field in fields):
            raise ValueError("Supply at least one non-null period field to edit.")
        return self


class PlanningIssue(BaseModel):
    field: str
    message: str
    period_ids: list[str] = Field(default_factory=list)


class CapacityWindow(BaseModel):
    start_date: CalendarDate
    end_date: CalendarDate
    available_hours: float | None


class PlanningInputs(BaseModel):
    profile_version: int
    planning_revision: int
    application_date: CalendarDate | None
    application_time_zone: str | None
    validation_time_zone: str
    validation_date: CalendarDate
    capacity_as_of_date: CalendarDate
    weekly_hours: float | None
    hours_unit: str = "hours_per_week"
    availability_periods: list[AvailabilityPeriod]
    capacity_time_zone: str = "Asia/Singapore"
    week_start: str = "Monday"
    week_end: str = "Sunday"
    period_boundaries: str = "inclusive"
    proration: str = "weekly_hours / 7 per covered calendar date; period rate replaces base rate"
    ready: bool
    issues: list[PlanningIssue]
    capacity_window: CapacityWindow | None = None
