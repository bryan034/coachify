from copy import deepcopy
from datetime import datetime, timezone
import unicodedata
from uuid import NAMESPACE_URL, uuid5

from app.schemas.capabilities import CapabilityCreate


class CapabilityConflict(Exception):
    def __init__(self, message, code="version_conflict", matches=None):
        self.message, self.code, self.matches = message, code, matches


class CapabilityLimit(Exception):
    pass


def normalized_name(name):
    return name.strip().casefold()


def skill_id(name):
    # Shared normalization v1; source IDs remain separate from a skill identity.
    return "skill:" + " ".join(unicodedata.normalize("NFKC", name).split()).casefold()


def same_source(first, second):
    return bool(first and second and all(first.get(key) == second.get(key) for key in ("cv_id", "item_id")))


def update_attachment(target, attached, fingerprint, timestamp):
    previous = target.get("attached_to")
    previous_fingerprint = target.get("attached_source_fingerprint")
    if previous == attached and previous_fingerprint == fingerprint:
        return False
    if same_source(previous, attached) and fingerprint is not None and previous_fingerprint == fingerprint:
        # An unrelated CV write changes its document version, not this relationship.
        return False
    history = target.setdefault("attachment_history", [])
    if len(history) >= 100:
        raise CapabilityLimit("This capability has reached its limit of 100 attachment changes. Its current declaration and history are preserved.")
    history.append({"at": timestamp, "previous": deepcopy(previous),
        "previous_source_fingerprint": previous_fingerprint, "attached_to": deepcopy(attached),
        "attached_source_fingerprint": fingerprint})
    target.update(attached_to=attached, attached_source_fingerprint=fingerprint, updated_at=timestamp)
    return True


def revise_attachment(previous, request, cv_item=None):
    declarations = deepcopy(previous)
    target = next((row for row in declarations if row["id"] == request.declaration_id), None)
    if target is None:
        raise CapabilityConflict("This capability is unavailable. Reload before changing its attachment.", "match_changed")
    attached = request.cv_match.model_dump() if request.cv_match else None
    fingerprint = (cv_item or {}).get("_attachment_fingerprint") if attached else None
    if update_attachment(target, attached, fingerprint, datetime.now(timezone.utc).isoformat()):
        return declarations
    return previous


def revise_declarations(previous, request: CapabilityCreate, user_id, cv_item=None):
    declarations = deepcopy(previous)
    matches = [row for row in declarations if normalized_name(row["name"]) == normalized_name(request.name)]
    if matches and request.mode == "new":
        raise CapabilityConflict("A capability with this name is already saved. Attach your description or keep a distinct claim.",
                                 "matching_capability", matches)
    timestamp = datetime.now(timezone.utc).isoformat()
    identifier = str(uuid5(NAMESPACE_URL, user_id + ":capability:" + request.mutation_id))
    contribution = {"id": identifier, "description": request.description, "created_at": timestamp}
    attached = request.cv_match.model_dump() if request.mode == "attach" and request.cv_match else None
    target = None
    if request.mode == "attach":
        target = next((row for row in matches if row["id"] == request.attach_to_id), None) if request.attach_to_id else next(
            (row for row in matches if same_source(row.get("attached_to"), attached)), None)
        if request.attach_to_id and target is None:
            raise CapabilityConflict("The matching capability changed or was removed. Reload and review your draft.", "match_changed")
    if target is not None:
        link_changed = update_attachment(target, attached, (cv_item or {}).get("_attachment_fingerprint"), timestamp) if attached else False
        if any(part["description"] == request.description for part in target["contributions"]):
            return declarations if link_changed else previous
        if len(target["contributions"]) >= 10:
            raise CapabilityLimit("This capability already has the maximum of ten descriptions.")
        target["contributions"].append(contribution)
        target["updated_at"] = timestamp
        return declarations
    if len(declarations) >= 100:
        raise CapabilityLimit("You can save at most 100 capability declarations.")
    declarations.append({
        "id": identifier, "name": request.name, "description": request.description,
        "skill_id": (cv_item or {}).get("_matched_skill_id", skill_id(request.name)),
        "provenance": "user_declared", "proficiency": None, "experience_months": None,
        "independence": None, "contributions": [contribution], "attached_to": attached,
        "attached_source_fingerprint": (cv_item or {}).get("_attachment_fingerprint") if attached else None,
        "attachment_history": [],
        "created_at": timestamp, "updated_at": timestamp,
    })
    return declarations
