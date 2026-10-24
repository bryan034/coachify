from copy import deepcopy
from datetime import datetime, timezone
from app.domain.errors import ProfileValidationError
from app.domain.planning import revise_planning
from app.domain.schools import institution_by_id, snapshot
from app.schemas.profile import ProfilePatch, ProfileView


def year_label(category, year):
    prefix = {"secondary": "Secondary", "junior_college": "JC"}.get(category, "Year")
    return f"{prefix} {year}"


def present_profile(profile: dict | None) -> dict:
    result = deepcopy(profile or ProfileView(version=0).model_dump(mode="json"))
    result["onboarding_state"] = ("missing" if profile is None else "complete" if profile.get("onboarding_complete") is True
                                  else "incomplete" if "onboarding_complete" in profile else "legacy_unconfirmed")
    education = result.get("education", {})
    active = (result.get("occupational_status") == "student"
              and not result.get("education_review_required")
              and education.get("context") == "current"
              and education.get("study_year_category") == result.get("school_category"))
    result["current_study_year"] = education.get("study_year") if active else None
    return result


def revise_profile(previous: dict | None, patch: ProfilePatch) -> dict:
    current = deepcopy(previous or ProfileView(version=0).model_dump(mode="json"))
    original = deepcopy(current)
    fields = patch.model_fields_set
    for name in ("occupational_status", "school_category"):
        if name in fields:
            value = getattr(patch, name)
            current[name] = value.value if value is not None else None
    status, category = current.get("occupational_status"), current.get("school_category")
    if not status:
        raise ProfileValidationError("occupational_status", "Choose your occupational status before saving education.")
    if status == "student" and category is None:
        raise ProfileValidationError("school_category", "Choose a school category for a student profile.")
    if "no_previous_education" in fields:
        if patch.no_previous_education is None:
            raise ProfileValidationError("no_previous_education", "Confirm whether previous education applies.")
        if patch.no_previous_education and (status == "student" or category is not None):
            raise ProfileValidationError("no_previous_education", "No previous education applies only to non-students without a school category.")
        current["no_previous_education"] = patch.no_previous_education
    elif status == "student" or category is not None:
        current["no_previous_education"] = False
    context = "current" if status == "student" else "last"
    context_changed = (status != original.get("occupational_status") or category != original.get("school_category"))
    current["education_context"] = context
    education = deepcopy(current.get("education", {}))
    had_education = any(education.get(k) is not None for k in ("institution", "course", "study_year"))
    review = bool(current.get("education_review_required")) or (context_changed and original.get("occupational_status") is not None)
    update = patch.education
    supplied = update.model_fields_set if update else set()
    if supplied and review and had_education and not patch.confirm_education_context:
        raise ProfileValidationError("confirm_education_context", "Review and confirm education for the selected status and category before editing it.")
    if "institution" in supplied:
        institution = update.institution
        if institution is None:
            if status == "student":
                raise ProfileValidationError("education.institution", "Enter or select your current institution.")
            education["institution"] = None
        elif institution.kind == "catalogue":
            row = institution_by_id(institution.id)
            if row is None or category not in row["categories"]:
                raise ProfileValidationError("education.institution", "Select an institution from the chosen school category, or enter a custom name.")
            education["institution"] = {"kind": "catalogue", "id": row["id"], "name": row["name"],
                "country_code": row["country_code"], "snapshot_date": snapshot()["snapshot_date"]}
        else:
            if category is None:
                raise ProfileValidationError("school_category", "Choose a category before adding an institution.")
            education["institution"] = {"kind": "custom", "id": None, "name": institution.name,
                "country_code": institution.country_code, "snapshot_date": None}
    if "course" in supplied:
        education["course"] = update.course
    if "study_year" in supplied:
        if status != "student":
            raise ProfileValidationError("education.study_year", "Only students can set a current study year; previous study information is retained.")
        education.update(study_year=update.study_year, study_year_label=year_label(category, update.study_year), study_year_category=category)
    institution_changed = ("institution" in supplied and education.get("institution") != original.get("education", {}).get("institution"))
    dependent_values_retained = institution_changed and any(
        education.get(key) is not None and key not in supplied for key in ("course", "study_year"))
    if supplied or patch.confirm_education_context:
        if had_education and review and patch.confirm_education_context:
            institution = education.get("institution")
            if institution and institution.get("kind") == "catalogue":
                row = institution_by_id(institution["id"])
                if category != original.get("school_category") and (not row or category not in row["categories"]):
                    raise ProfileValidationError("education.institution", "Choose a matching institution before confirming the new category.")
            if status == "student" and education.get("study_year") is not None and education.get("study_year_category") != category:
                raise ProfileValidationError("education.study_year", "Review and enter the study year for the new school category.")
        education.update(category=category, context=context)
        review = bool(dependent_values_retained and not patch.confirm_education_context)
    current.update(education=education, education_review_required=bool(review))
    current = revise_planning(current, patch)
    # A derived response field is not persisted as a stale second source of truth.
    current.pop("current_study_year", None)
    original.pop("current_study_year", None)
    current.pop("onboarding_state", None)
    original.pop("onboarding_state", None)
    if current == original:
        return previous or current
    current["version"] = patch.expected_version + 1
    return current


def complete_onboarding(previous: dict | None, patch: ProfilePatch) -> dict:
    # Completion is an explicit atomic field in the same immutable profile snapshot.
    if previous and previous.get("onboarding_complete") is True:
        return previous
    current = deepcopy(revise_profile(previous, patch))
    status, category = current.get("occupational_status"), current.get("school_category")
    education = current.get("education", {})
    no_education = status != "student" and category is None and current.get("no_previous_education") is True
    if not no_education:
        if category is None:
            raise ProfileValidationError("school_category", "Choose your school category or explicitly select no previous education.")
        if not education.get("institution"):
            raise ProfileValidationError("education.institution", "Enter or select your institution before finishing setup.")
        if current.get("education_review_required"):
            raise ProfileValidationError("confirm_education_context", "Review the education details before finishing setup.")
        if status == "student" and (not education.get("study_year") or education.get("study_year_category") != category):
            raise ProfileValidationError("education.study_year", "Enter your current study level/year for this school category.")
    if no_education:
        current["education_review_required"] = False
    current.update(onboarding_complete=True, onboarding_completed_at=datetime.now(timezone.utc).isoformat())
    return current
