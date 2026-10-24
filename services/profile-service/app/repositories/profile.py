import hashlib
import json
from pymongo import DESCENDING
from app.domain.planning import revise_period
from app.domain.errors import ProfileValidationError
from pymongo.errors import DuplicateKeyError
from app.domain.profile import revise_profile, complete_onboarding
from app.schemas.profile import ProfilePatch


class VersionConflict(Exception):
    pass


class MutationConflict(Exception):
    pass


class ProfileRepository:
    """Append-only version documents; unique owner/version enforces concurrent writes.

    Every insert is an atomic full snapshot. No cross-collection transaction or
    mutable history is required, so standalone local MongoDB is supported.
    """
    def __init__(self, database):
        self.collection = database.profile_versions
        self.receipts = database.profile_mutations
        self.receipts.create_index([("owner", 1), ("mutation_id", 1)], unique=True)
        self.collection.create_index([("owner", 1), ("mutation_id", 1)], unique=True,
                                     partialFilterExpression={"mutation_id": {"$type": "string"}})
        self.collection.create_index([("owner", 1), ("version", DESCENDING)], unique=True)

    @staticmethod
    def unpack(doc):
        return doc["profile"] if doc else None

    def current(self, owner: str):
        return self.unpack(self.collection.find_one({"owner": owner}, sort=[("version", DESCENDING)]))

    def version(self, owner: str, version: int):
        return self.unpack(self.collection.find_one({"owner": owner, "version": version}))

    @staticmethod
    def fingerprint(operation, data):
        return hashlib.sha256(json.dumps({"operation": operation, "data": data}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def claim(self, owner, mutation_id, fingerprint):
        if not mutation_id:
            return
        try:
            self.receipts.insert_one({"owner": owner, "mutation_id": mutation_id,
                                      "fingerprint": fingerprint, "completed_noop": False})
        except DuplicateKeyError:
            receipt = self.receipts.find_one({"owner": owner, "mutation_id": mutation_id})
            if receipt["fingerprint"] != fingerprint:
                raise MutationConflict

    def replay(self, owner, mutation_id, fingerprint):
        if mutation_id is None:
            return None
        committed = self.collection.find_one({"owner": owner, "mutation_id": mutation_id})
        receipt = self.receipts.find_one({"owner": owner, "mutation_id": mutation_id})
        if any(record and record["fingerprint"] != fingerprint for record in (committed, receipt)):
            raise MutationConflict
        if committed or (receipt and receipt.get("completed_noop")):
            # Changed-write receipts commit atomically inside profile snapshots.
            # An incomplete claim is retryable after a process/network failure.
            return self.current(owner)
        return None

    def mutate(self, owner, expected_version, transform, mutation_id=None, fingerprint=None):
        replayed = self.replay(owner, mutation_id, fingerprint)
        if replayed is not None:
            return replayed
        previous = self.current(owner)
        if (previous or {}).get("version", 0) != expected_version:
            # A simultaneous duplicate may have committed between replay lookup
            # and the current-version read. Check its receipt before rejecting it.
            replayed = self.replay(owner, mutation_id, fingerprint)
            if replayed is not None:
                return replayed
            raise VersionConflict
        profile = transform(previous)
        self.claim(owner, mutation_id, fingerprint)
        if previous == profile:
            if mutation_id:
                self.receipts.update_one({"owner": owner, "mutation_id": mutation_id},
                                         {"$set": {"completed_noop": True}})
            return profile
        profile["version"] = expected_version + 1
        document = {"owner": owner, "version": profile["version"], "profile": profile}
        if mutation_id:
            document.update(mutation_id=mutation_id, fingerprint=fingerprint)
        try:
            self.collection.insert_one(document)
        except DuplicateKeyError as exc:
            replayed = self.replay(owner, mutation_id, fingerprint)
            if replayed is not None:
                return replayed
            raise VersionConflict from exc
        return profile

    def update(self, owner: str, patch: ProfilePatch, mutation_id=None):
        fingerprint = self.fingerprint("profile", patch.model_dump(mode="json", exclude_unset=True))
        return self.mutate(owner, patch.expected_version, lambda old: revise_profile(old, patch), mutation_id, fingerprint)

    def change_period(self, owner, operation, identifier, expected_version, changes, mutation_id):
        fingerprint = self.fingerprint(operation, {"period_id": identifier, "expected_version": expected_version, **changes})
        def transform(previous):
            if previous is None:
                raise ProfileValidationError("weekly_hours", "Save your normal weekly availability before managing periods.")
            return revise_period(previous, operation, identifier, changes)
        return self.mutate(owner, expected_version, transform, mutation_id, fingerprint)

    def finish_onboarding(self, owner, patch, mutation_id):
        fingerprint = self.fingerprint("onboarding", patch.model_dump(mode="json", exclude_unset=True))
        return self.mutate(owner, patch.expected_version, lambda previous: complete_onboarding(previous, patch), mutation_id, fingerprint)
