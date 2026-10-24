from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError
from app.domain.profile import revise_profile
from app.schemas.profile import ProfilePatch


class VersionConflict(Exception):
    pass


class ProfileRepository:
    """Append-only version documents; unique owner/version enforces concurrent writes.

    Every insert is an atomic full snapshot. No cross-collection transaction or
    mutable history is required, so standalone local MongoDB is supported.
    """
    def __init__(self, database):
        self.collection = database.profile_versions
        self.collection.create_index([("owner", 1), ("version", DESCENDING)], unique=True)

    @staticmethod
    def unpack(doc):
        return doc["profile"] if doc else None

    def current(self, owner: str):
        return self.unpack(self.collection.find_one({"owner": owner}, sort=[("version", DESCENDING)]))

    def version(self, owner: str, version: int):
        return self.unpack(self.collection.find_one({"owner": owner, "version": version}))

    def update(self, owner: str, patch: ProfilePatch):
        previous = self.current(owner)
        if (previous or {}).get("version", 0) != patch.expected_version:
            raise VersionConflict
        profile = revise_profile(previous, patch)
        if previous == profile:
            return profile
        try:
            self.collection.insert_one({"owner": owner, "version": profile["version"], "profile": profile})
        except DuplicateKeyError as exc:
            raise VersionConflict from exc
        return profile
