"""Date-only planning inputs. Scheduling and roadmap generation remain separate."""
from copy import deepcopy
from datetime import date, datetime
from fractions import Fraction
from zoneinfo import ZoneInfo
from uuid import uuid4
from app.domain.errors import ProfileValidationError, PeriodNotFound

CAPACITY_ZONE = "Asia/Singapore"


def today_in(zone: str) -> date:
    return datetime.now(ZoneInfo(zone)).date()


def revise_planning(current, patch):
    fields = patch.model_fields_set
    before = deepcopy(current)
    if "application_date" in fields:
        if not patch.time_zone:
            raise ProfileValidationError("time_zone", "Provide your device's time zone to validate the application date.")
        if date.fromisoformat(patch.application_date) <= today_in(patch.time_zone):
            raise ProfileValidationError("application_date", "Choose an application date strictly after today in your device's time zone.")
        if patch.application_date != current.get("application_date"):
            current.update(application_date=patch.application_date, application_time_zone=patch.time_zone)
    elif "time_zone" in fields:
        raise ProfileValidationError("application_date", "Supply the application date together with its validation time zone.")
    if "weekly_hours" in fields:
        current["weekly_hours"] = patch.weekly_hours
    if current != before:
        current["planning_revision"] = before.get("planning_revision", 0) + 1
    return current


def revise_period(previous, operation, identifier, changes):
    current = deepcopy(previous)
    rows = current.setdefault("availability_periods", [])
    existing = next((row for row in rows if row["id"] == identifier), None)
    if operation == "delete":
        if existing is not None:
            rows.remove(existing)
        else:
            return previous  # Repeated removal cannot affect another period.
    else:
        if operation == "edit" and existing is None:
            raise PeriodNotFound
        period = {**(existing or {}), **changes, "id": identifier or str(uuid4())}
        if period["end_date"] < period["start_date"]:
            raise ProfileValidationError("end_date", "End date must be on or after the start date (both inclusive).")
        if date.fromisoformat(period["end_date"]) < today_in(CAPACITY_ZONE):
            raise ProfileValidationError("end_date", "New or edited periods cannot end before today in Asia/Singapore.")
        base = current.get("weekly_hours")
        if base is None:
            raise ProfileValidationError("weekly_hours", "Save your normal weekly availability before adding a reduced period.")
        if period["weekly_hours"] >= base:
            raise ProfileValidationError("weekly_hours", "Reduced hours must be at least 0 and strictly below your normal weekly hours.")
        if any(row["id"] != identifier and row["start_date"] <= period["end_date"] and row["end_date"] >= period["start_date"] for row in rows):
            raise ProfileValidationError("start_date", "This inclusive date range overlaps another saved period.")
        if existing == period:
            return previous
        if existing:
            rows.remove(existing)
        rows.append(period)
        rows.sort(key=lambda row: (row["start_date"], row["id"]))
    current["planning_revision"] = previous.get("planning_revision", 0) + 1
    return current


def planning_inputs(profile, zone, start=None, end=None):
    profile = profile or {}
    deadline_today, capacity_today = today_in(zone), today_in(CAPACITY_ZONE)
    deadline, base = profile.get("application_date"), profile.get("weekly_hours")
    rows = deepcopy(profile.get("availability_periods", []))
    issues = []
    if not deadline:
        issues.append({"field": "application_date", "message": "Set an intended application date."})
    elif date.fromisoformat(deadline) <= deadline_today:
        issues.append({"field": "application_date", "message": "The saved application date is today or earlier. Update it before generating a new roadmap."})
    if base is None:
        issues.append({"field": "weekly_hours", "message": "Set your normal weekly availability."})
    # Historical rates retain their original meaning; only applicable dates block planning.
    cutoff = max(capacity_today, start) if start else capacity_today
    conflicts = [row["id"] for row in rows if row["end_date"] >= cutoff.isoformat()
                 and (end is None or row["start_date"] <= end.isoformat())
                 and (base is None or row["weekly_hours"] >= base)]
    if conflicts:
        issues.append({"field": "availability_periods", "message": "Review reduced periods whose hours are no longer below the normal weekly budget.", "period_ids": conflicts})
    window = None
    if start is not None:
        if end is None or end < start:
            raise ProfileValidationError("end_date", "Provide a window end on or after its start.")
        hours = None
        if base is not None and not conflicts:
            # Rational arithmetic avoids rounding each day's fractional allocation.
            total = Fraction(str(base)) * ((end - start).days + 1) / 7
            for row in rows:
                a, b = max(start, date.fromisoformat(row["start_date"])), min(end, date.fromisoformat(row["end_date"]))
                if a <= b:
                    total += (Fraction(str(row["weekly_hours"])) - Fraction(str(base))) * ((b - a).days + 1) / 7
            hours = float(total)
        window = {"start_date": start.isoformat(), "end_date": end.isoformat(), "available_hours": hours}
    return {"profile_version": profile.get("version", 0), "planning_revision": profile.get("planning_revision", 0),
            "application_date": deadline, "application_time_zone": profile.get("application_time_zone"),
            "validation_time_zone": zone, "validation_date": deadline_today.isoformat(),
            "capacity_as_of_date": capacity_today.isoformat(), "weekly_hours": base, "availability_periods": rows,
            "ready": not issues, "issues": issues, "capacity_window": window}
