"""Atomic embedded account declarations, with recoverable mutation receipts.

The account document is the authority. Receipts hold immutable input/result
snapshots and are operational history, never an alternative capability store.
The last receipt is sealed before another mutation can publish, so a process
failure after account publication remains an idempotent replay.
"""
import hashlib
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError
from app.domain.capabilities import CapabilityConflict, revise_attachment, revise_declarations


class CapabilityRepository:
    def __init__(self, database):
        self.accounts = database.accounts
        self.receipts = database.capability_mutations
        self.receipts.create_index([("user_id", 1), ("mutation_id", 1)], unique=True)
        self.receipts.create_index([("user_id", 1), ("created_at", -1)])

    def account(self, owner):
        account = self.accounts.find_one({"owner": owner})
        if not account:
            raise HTTPException(401, "Your account is unavailable. Sign in again.")
        return account

    @staticmethod
    def present(account):
        return {"user_id": account["id"], "version": account.get("declarations_version", 0),
                "declarations": account.get("capability_declarations", [])}

    def current(self, owner):
        return self.present(self.account(owner))

    def seal(self, account):
        last = account.get("capability_last_mutation")
        if last:
            self.receipts.update_one({"user_id": account["id"], "mutation_id": last},
                                     {"$set": {"completed": True}})

    def create(self, owner, request, validate_cv=lambda: None):
        def revise(account):
            cv_item = validate_cv() if request.cv_match else None
            return revise_declarations(account.get("capability_declarations", []), request, account["id"], cv_item)
        return self.mutate(owner, request, revise)

    def attachment(self, owner, request, validate_cv=lambda _name: None):
        def revise(account):
            previous = account.get("capability_declarations", [])
            target = next((row for row in previous if row["id"] == request.declaration_id), None)
            if target is None:
                raise CapabilityConflict("This capability is unavailable. Reload before changing its attachment.", "match_changed")
            cv_item = validate_cv(target["name"]) if request.cv_match else None
            return revise_attachment(previous, request, cv_item)
        return self.mutate(owner, request, revise, operation="attachment")

    def mutate(self, owner, request, revise, operation=None):
        body = request.model_dump(mode="json")
        if operation is not None: body = {"operation": operation, "data": body}
        fingerprint = hashlib.sha256(json.dumps(body,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        account = self.account(owner)
        query = {"user_id": account["id"], "mutation_id": request.mutation_id}
        receipt = self.receipts.find_one(query)
        if receipt and receipt["fingerprint"] != fingerprint:
            raise CapabilityConflict("This request key was already used for different changes. Use a new key.", "mutation_conflict")
        self.seal(account)
        if receipt and (receipt.get("completed") or account.get("capability_last_mutation") == request.mutation_id):
            return self.current(owner)
        if account.get("declarations_version", 0) != request.expected_version:
            # A same-key concurrent request may have committed after the first read.
            latest = self.account(owner)
            replay = self.receipts.find_one(query)
            if replay and replay["fingerprint"] != fingerprint:
                raise CapabilityConflict("This request key was already used for different changes. Use a new key.", "mutation_conflict")
            if replay and (replay.get("completed") or latest.get("capability_last_mutation") == request.mutation_id):
                return self.present(latest)
            raise CapabilityConflict("Your capabilities changed elsewhere. Reload and reconcile your draft.")
        previous = account.get("capability_declarations", [])
        revised = revise(account)
        changed = revised != previous
        candidate = {**query, "fingerprint": fingerprint, "completed": False,
                     "base_version": request.expected_version,
                     "version": request.expected_version + int(changed),
                     "declarations": revised, "created_at": datetime.now(timezone.utc)}
        try:
            self.receipts.insert_one(candidate)
        except DuplicateKeyError:
            candidate = self.receipts.find_one(query)
            if candidate["fingerprint"] != fingerprint:
                raise CapabilityConflict("This request key was already used for different changes. Use a new key.", "mutation_conflict")
        if candidate.get("completed"):
            return self.current(owner)
        # Even no-ops publish their receipt under the expected-version boundary.
        # They never increment the version used by downstream consumers.
        version_filter = ({"$or": [{"declarations_version": 0}, {"declarations_version": {"$exists": False}}]}
                          if request.expected_version == 0 else {"declarations_version": request.expected_version})
        result = self.accounts.update_one({"id": account["id"], **version_filter,
                                           "capability_last_mutation": account.get("capability_last_mutation")},
            {"$set": {"capability_declarations": candidate["declarations"], "declarations_version": candidate["version"],
                      "capability_last_mutation": request.mutation_id}})
        latest = self.account(owner)
        if not result.modified_count:
            replay = self.receipts.find_one(query)
            if replay and replay["fingerprint"] != fingerprint:
                raise CapabilityConflict("This request key was already used for different changes. Use a new key.", "mutation_conflict")
            if latest.get("capability_last_mutation") != request.mutation_id and not replay.get("completed"):
                raise CapabilityConflict("Your capabilities changed elsewhere. Reload and reconcile your draft.")
        self.seal(latest)
        return self.present(latest)
