from copy import deepcopy
from app.schemas.profile import ProfilePatch, ProfileView


def revise_profile(previous: dict | None, patch: ProfilePatch) -> dict:
    # Preserve all unrelated fields, including future P01–P03 education records.
    current = deepcopy(previous or ProfileView(version=0).model_dump(mode="json"))
    changed = (current.get("occupational_status") != patch.occupational_status.value
               or current.get("school_category") != patch.school_category)
    if not changed:
        return current
    has_previous_context = current.get("occupational_status") is not None
    current.update(
        occupational_status=patch.occupational_status.value,
        school_category=patch.school_category.value if patch.school_category else None,
        education_context="current" if patch.occupational_status == "student" else "last",
        education_review_required=current.get("education_review_required", False) or has_previous_context,
        version=patch.expected_version + 1,
    )
    return current
