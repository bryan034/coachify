"""C07 repository invariants run against memory and disposable real MongoDB."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
from threading import RLock
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, DuplicateKeyError
from app.domain.capabilities import CapabilityConflict, CapabilityLimit, revise_declarations, skill_id
from app.main import create_app
from app.repositories.capabilities import CapabilityRepository
from app.schemas.capabilities import CapabilityAttachment, CapabilityCreate


def matches(document, query):
    for field, value in query.items():
        if field == "$or":
            if not any(matches(document, part) for part in value):
                return False
        elif isinstance(value, dict) and "$exists" in value:
            if (field in document) != value["$exists"]:
                return False
        elif document.get(field) != value:
            return False
    return True


class MemoryCollection:
    def __init__(self):
        self.rows, self.lock = [], RLock()

    def create_index(self, *_args, **_kwargs):
        pass

    def find_one(self, query):
        with self.lock:
            return next((deepcopy(row) for row in self.rows if matches(row, query)), None)

    def insert_one(self, document):
        with self.lock:
            key = {k: document[k] for k in ("user_id", "mutation_id") if k in document}
            if key and any(matches(row, key) for row in self.rows):
                raise DuplicateKeyError("duplicate mutation")
            self.rows.append(deepcopy(document))

    def update_one(self, query, update):
        with self.lock:
            for row in self.rows:
                if matches(row, query):
                    before = deepcopy(row)
                    row.update(deepcopy(update["$set"]))
                    return SimpleNamespace(modified_count=int(row != before))
            return SimpleNamespace(modified_count=0)


@pytest.fixture(params=["memory", "mongo"])
def database(request):
    if request.param == "memory":
        yield SimpleNamespace(accounts=MemoryCollection(), capability_mutations=MemoryCollection())
    else:
        if not os.getenv("MONGODB_TEST_URI"):
            pytest.skip("Set MONGODB_TEST_URI for real MongoDB C07 coverage")
        client = MongoClient(os.environ["MONGODB_TEST_URI"], serverSelectionTimeoutMS=5000)
        database = client["elo_capability_test_" + uuid4().hex]
        try:
            yield database
        finally:
            client.drop_database(database.name)
            client.close()


@pytest.fixture
def repo(database):
    database.accounts.insert_one({"id": "alice-id", "owner": "alice", "identity": "synthetic:alice",
        "password_hash": "preserve-synthetic-hash", "email_verified": True,
        "onboarding_complete": True, "planning_preferences": {"hours": 12}})
    database.accounts.insert_one({"id": "bob-id", "owner": "bob", "identity": "synthetic:bob"})
    return CapabilityRepository(database)


def payload(**updates):
    return CapabilityCreate(expected_version=updates.pop("expected_version", 0),
        mutation_id=updates.pop("mutation_id", "add-one"), name=updates.pop("name", "Python"),
        description=updates.pop("description", "I cleaned synthetic tabular data using pandas."),
        mode=updates.pop("mode", "new"), **updates)


class SessionAccounts:
    def session(self, token, _settings):
        if token not in {"alice", "bob"}:
            raise HTTPException(401, "Session expired")
        return {"owner": token, "id": token + "-id"}


@pytest.fixture
def client(repo):
    with TestClient(create_app(repository=object(), accounts=SessionAccounts(), capabilities=repo)) as client:
        yield client


def test_before_cv_fields_versions_and_account_preservation(repo):
    before = repo.account("alice")
    saved = repo.create("alice", payload())
    assert saved["user_id"] == "alice-id" and saved["version"] == 1
    row = saved["declarations"][0]
    assert row["provenance"] == "user_declared" and row["attached_to"] is None
    assert row["proficiency"] is row["experience_months"] is row["independence"] is None
    assert row["skill_id"] == "skill:python"
    assert len(row["contributions"]) == 1
    assert all(repo.account("alice")[key] == value for key, value in before.items())
    assert repo.current("bob") == {"user_id": "bob-id", "version": 0, "declarations": []}
    restored = CapabilityRepository(SimpleNamespace(accounts=repo.accounts, capability_mutations=repo.receipts))
    assert restored.current("alice") == saved


def test_cv_attachment_waits_leave_auth_and_reads_available(client):
    """CV calls Profile back for authentication; attachment waits need own capacity."""
    from anyio import to_thread
    async def shrink_shared_pool():
        limiter = to_thread.current_default_thread_limiter()
        old = limiter.total_tokens
        limiter.total_tokens = 2
        return old
    async def restore_shared_pool(value):
        to_thread.current_default_thread_limiter().total_tokens = value

    release, first, second = Event(), Event(), Event()
    lock, calls = RLock(), 0
    def waiting_validation(*_args):
        nonlocal calls
        with lock:
            calls += 1
            (first if calls == 1 else second).set()
        assert release.wait(5)
        return {"id": "item-one", "skill_ids": ["skill:python"]}
    old = client.portal.call(shrink_shared_pool)
    try:
        with patch("app.api.v1.capabilities.validate_cv_match", waiting_validation), ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(client.post, "/api/v1/profile/capabilities",
                headers={"Authorization": "Bearer alice"}, json=payload(mutation_id="wait-" + str(index),
                    mode="attach", cv_match={"cv_id": "cv-one", "item_id": "item-one", "cv_version": 1}).model_dump())
                for index in range(2)]
            try:
                assert first.wait(2) and second.wait(2)
                response = pool.submit(client.get, "/api/v1/profile/capabilities",
                    headers={"Authorization": "Bearer alice"}).result(timeout=2)
                assert response.status_code == 200
            finally:
                release.set()
            assert all(future.result(timeout=2).status_code in (200, 409) for future in futures)
    finally:
        client.portal.call(restore_shared_pool, old)


def test_matching_requires_explicit_choice_and_preserves_source_identity(repo):
    first = repo.create("alice", payload())
    original = deepcopy(first["declarations"][0])
    with pytest.raises(CapabilityConflict) as error:
        repo.create("alice", payload(expected_version=1, mutation_id="match", name=" PYTHON "))
    assert error.value.code == "matching_capability"
    assert error.value.matches == [original]
    attached = repo.create("alice", payload(expected_version=1, mutation_id="attach", name="python",
        description="I also wrote my own plotting scripts.", mode="attach", attach_to_id=original["id"]))
    row = attached["declarations"][0]
    assert row["description"] == original["description"]
    assert row["contributions"][0] == original["contributions"][0]
    assert row["id"] == original["id"] and len(row["contributions"]) == 2
    distinct = repo.create("alice", payload(expected_version=2, mutation_id="distinct", mode="distinct"))
    assert len(distinct["declarations"]) == 2
    assert len({item["id"] for item in distinct["declarations"]}) == 2
    assert len({item["skill_id"] for item in distinct["declarations"]}) == 1
    with pytest.raises(CapabilityConflict) as error:
        repo.create("alice", payload(expected_version=3, mutation_id="wrong-match", name="SQL", mode="attach", attach_to_id=original["id"]))
    assert error.value.code == "match_changed"


def test_duplicate_noop_stale_and_old_replay_do_not_change_versions(repo):
    request = payload()
    saved = repo.create("alice", request)
    assert repo.create("alice", request) == saved
    with pytest.raises(CapabilityConflict) as error:
        repo.create("alice", payload(description="Changed uncertain retry"))
    assert error.value.code == "mutation_conflict"
    noop = payload(expected_version=1, mutation_id="noop", mode="attach", attach_to_id=saved["declarations"][0]["id"])
    assert repo.create("alice", noop) == saved
    latest = repo.create("alice", payload(expected_version=1, mutation_id="second", name="SQL"))
    assert latest["version"] == 2
    assert repo.create("alice", request) == latest
    assert repo.create("alice", noop) == latest
    with pytest.raises(CapabilityConflict):
        repo.create("alice", payload(expected_version=1, mutation_id="stale", name="Java"))


def test_atomic_races_duplicate_and_different_keys(repo):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repo.create("alice", payload()), range(2)))
    assert [r["version"] for r in results] == [1, 1]
    assert len(repo.current("alice")["declarations"]) == 1
    def save(index):
        try:
            return repo.create("alice", payload(expected_version=1, mutation_id=f"race-{index}", name=f"Skill {index}"))["version"]
        except CapabilityConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert sorted(map(str, results)) == ["2", "conflict"]


def test_same_key_different_payload_race_cannot_publish_both(repo):
    def save(index):
        try:
            return repo.create("alice", payload(description=f"Distinct input {index}"))["version"]
        except CapabilityConflict as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert sorted(map(str, results)) == ["1", "mutation_conflict"]
    assert len(repo.current("alice")["declarations"]) == 1


def test_crash_after_account_publication_replays_and_seals_prior_receipt(repo):
    original = repo.seal
    count = 0
    def fail_after_publish(account):
        nonlocal count
        count += 1
        if count == 2:
            raise AutoReconnect("synthetic lost response")
        return original(account)
    with patch.object(repo, "seal", side_effect=fail_after_publish):
        with pytest.raises(AutoReconnect):
            repo.create("alice", payload())
    assert repo.current("alice")["version"] == 1
    assert repo.receipts.find_one({"user_id": "alice-id", "mutation_id": "add-one"})["completed"] is False
    newer = repo.create("alice", payload(expected_version=1, mutation_id="next", name="SQL"))
    assert repo.create("alice", payload()) == newer
    assert repo.receipts.find_one({"user_id": "alice-id", "mutation_id": "add-one"})["completed"] is True


def test_storage_failure_before_publication_retries_without_duplicate(repo):
    with patch.object(repo.accounts, "update_one", side_effect=AutoReconnect("synthetic unavailable")):
        with pytest.raises(AutoReconnect):
            repo.create("alice", payload())
    assert repo.current("alice")["version"] == 0
    assert len(repo.create("alice", payload())["declarations"]) == 1


def test_explicit_cv_attachment_records_version_without_copying_or_claiming_cv_text(repo):
    reference = {"cv_id": "source-one", "item_id": "skill-one", "cv_version": 8}
    request = payload(mode="attach", cv_match=reference)
    item = {"id": "skill-one", "kind": "skill", "skill_ids": ["skill:python"]}
    saved = repo.create("alice", request, lambda: item)
    row = saved["declarations"][0]
    assert row["attached_to"] == reference and row["provenance"] == "user_declared"
    assert "evidence" not in row and row["proficiency"] is None
    # Retry remains safe if that CV has since changed or become unavailable.
    def unavailable():
        raise AssertionError("Committed retries must not revalidate changed foreign state")
    assert repo.create("alice", request, unavailable) == saved
    repeated = repo.create("alice", payload(expected_version=1, mutation_id="reattach", mode="attach", cv_match=reference), lambda: item)
    assert repeated == saved
    extended = repo.create("alice", payload(expected_version=1, mutation_id="extend", mode="attach", cv_match=reference,
        description="I also wrote unit tests for the cleaning functions."), lambda: item)
    assert extended["version"] == 2 and len(extended["declarations"]) == 1
    assert len(extended["declarations"][0]["contributions"]) == 2


def test_api_auth_owner_input_rejection_limits_and_no_cv_dependency(client):
    path = "/api/v1/profile/capabilities"
    headers = {"Authorization": "Bearer alice"}
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer expired"}).status_code == 401
    with patch("app.api.v1.capabilities.validate_cv_match", side_effect=AssertionError("No CV requested")):
        response = client.post(path, headers=headers, json=payload().model_dump())
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["limits"] == {"max_declarations": 100, "name": 120, "description": 2000, "max_contributions": 10}
    assert client.get(path, headers={"Authorization": "Bearer bob"}).json()["declarations"] == []
    body = payload(expected_version=1, mutation_id="next").model_dump()
    assert client.post(path, headers=headers, json={**body, "user_id": "bob-id"}).status_code == 422
    assert client.post(path, headers=headers, json=body).json()["code"] == "matching_capability"
    assert client.get(path, headers=headers).json()["version"] == 1


@pytest.mark.parametrize("changes", [
    {"name": " "}, {"description": "\n "}, {"name": "x" * 121}, {"description": "x" * 2001},
    {"name": "bad\x00"}, {"expected_version": True}, {"expected_version": -1},
    {"mutation_id": "bad key"}, {"proficiency": "expert"}, {"mode": "attach"},
    {"cv_match": {"cv_id": "../other", "item_id": "x", "cv_version": 1}},
])
def test_invalid_requests_do_not_create_declarations(changes):
    with pytest.raises(ValueError):
        CapabilityCreate(**(payload().model_dump() | changes))


def test_exact_text_limits_and_unknown_attributes():
    value = payload(name="x" * 120, description="y" * 2000)
    assert len(value.name) == 120 and len(value.description) == 2000
    assert skill_id(" Ｃ++  ") == "skill:c++"
    assert skill_id("C++") != skill_id("C#")
    assert skill_id("Machine   Learning") == "skill:machine learning"
    row = revise_declarations([], payload(), "user")[0]
    with pytest.raises(CapabilityLimit):
        revise_declarations([row] * 100, payload(name="Other"), "user")
    row["contributions"] *= 10
    with pytest.raises(CapabilityLimit):
        revise_declarations([row], payload(mode="attach", attach_to_id=row["id"], description="More text"), "user")


def attachment(declaration_id, **updates):
    return CapabilityAttachment(expected_version=updates.pop("expected_version", 1),
        mutation_id=updates.pop("mutation_id", "link-one"), declaration_id=declaration_id,
        cv_match=updates.pop("cv_match", {"cv_id": "source-one", "item_id": "project-one", "cv_version": 8}), **updates)


def source_item(fingerprint="a" * 64):
    return {"id": "project-one", "kind": "project", "skill_ids": ["skill:python"],
        "_matched_skill_id": "skill:python", "_attachment_fingerprint": fingerprint}


def test_attachment_reconciliation_preserves_manual_content_and_history(repo):
    saved = repo.create("alice", payload())
    original = deepcopy(saved["declarations"][0])
    requested_names = []
    def verify(name):
        requested_names.append(name)
        return source_item()
    request = attachment(original["id"])
    linked = repo.attachment("alice", request, verify)
    row = linked["declarations"][0]
    assert requested_names == ["Python"]
    assert linked["version"] == 2 and row["attached_source_fingerprint"] == "a" * 64
    assert row["description"] == original["description"] and row["contributions"] == original["contributions"]
    assert row["provenance"] == "user_declared" and row["proficiency"] is row["experience_months"] is row["independence"] is None
    assert row["attachment_history"][0]["previous"] is None
    assert row["attachment_history"][0]["attached_to"] == request.cv_match.model_dump()
    changed = repo.attachment("alice", attachment(original["id"], expected_version=2, mutation_id="changed-source",
        cv_match={"cv_id": "source-one", "item_id": "project-one", "cv_version": 9}), lambda _: source_item("b" * 64))
    assert changed["version"] == 3
    assert changed["declarations"][0]["attachment_history"][-1]["previous_source_fingerprint"] == "a" * 64
    detached = repo.attachment("alice", attachment(original["id"], expected_version=3, mutation_id="detach", cv_match=None),
        lambda _: pytest.fail("Detach must not require CV service"))
    assert detached["version"] == 4
    assert detached["declarations"][0]["attached_to"] is None
    assert detached["declarations"][0]["attached_source_fingerprint"] is None
    assert len(detached["declarations"][0]["attachment_history"]) == 3
    assert detached["declarations"][0]["description"] == original["description"]
    assert repo.current("bob")["declarations"] == []


def test_same_item_fingerprint_and_repeated_detach_are_semantic_noops(repo):
    saved = repo.create("alice", payload(mode="attach", cv_match={"cv_id": "source-one", "item_id": "project-one", "cv_version": 8}), source_item)
    original = saved["declarations"][0]
    request = attachment(original["id"], cv_match={"cv_id": "source-one", "item_id": "project-one", "cv_version": 12})
    noop = repo.attachment("alice", request, lambda _: source_item())
    assert noop == saved
    detached = repo.attachment("alice", attachment(original["id"], mutation_id="detach", cv_match=None), lambda _: pytest.fail())
    assert detached["version"] == 2
    assert repo.attachment("alice", attachment(original["id"], expected_version=2, mutation_id="detach-again", cv_match=None)) == detached
    assert repo.attachment("alice", request, lambda _: pytest.fail("Committed replay cannot revalidate CV")) == detached


def test_unknown_attachment_fingerprint_remains_unverified_until_explicit_refresh(repo):
    saved = repo.create("alice", payload(mode="attach", cv_match={"cv_id": "source-one", "item_id": "project-one", "cv_version": 8}), lambda: source_item(None))
    row = saved["declarations"][0]
    assert row["attached_source_fingerprint"] is None
    refreshed = repo.attachment("alice", attachment(row["id"]), lambda _: source_item())
    assert refreshed["version"] == 2 and refreshed["declarations"][0]["attached_source_fingerprint"] == "a" * 64


def test_attachment_failures_stale_replay_and_foreign_declaration_preserve_inputs(repo):
    saved = repo.create("alice", payload())
    identifier = saved["declarations"][0]["id"]
    request = attachment(identifier)
    def changed(_): raise CapabilityConflict("Source changed", "match_changed")
    with pytest.raises(CapabilityConflict): repo.attachment("alice", request, changed)
    assert repo.current("alice") == saved
    with pytest.raises(CapabilityConflict):
        repo.attachment("bob", attachment(identifier, expected_version=0), lambda _: pytest.fail("Foreign declaration must not fetch CV"))
    with pytest.raises(CapabilityConflict):
        repo.attachment("alice", attachment(identifier, expected_version=0), lambda _: pytest.fail("Stale input must not fetch CV"))
    linked = repo.attachment("alice", request, lambda _: source_item())
    with pytest.raises(CapabilityConflict) as exc:
        repo.attachment("alice", attachment(identifier, cv_match=None))
    assert exc.value.code == "mutation_conflict"
    assert repo.current("alice") == linked


def test_attachment_same_key_race_and_lost_response_recover_once(repo):
    saved = repo.create("alice", payload())
    request = attachment(saved["declarations"][0]["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: repo.attachment("alice", request, lambda _name: source_item()), range(2)))
    assert all(result["version"] == 2 for result in outcomes)
    assert len(repo.current("alice")["declarations"][0]["attachment_history"]) == 1
    detach = attachment(request.declaration_id, expected_version=2, mutation_id="detach", cv_match=None)
    original = repo.seal
    calls = 0
    def interrupted(account):
        nonlocal calls
        calls += 1
        if calls == 2: raise AutoReconnect("synthetic lost response")
        return original(account)
    with patch.object(repo, "seal", side_effect=interrupted):
        with pytest.raises(AutoReconnect): repo.attachment("alice", detach)
    assert repo.attachment("alice", detach)["version"] == 3
    assert len(repo.current("alice")["declarations"][0]["attachment_history"]) == 2


def test_attachment_api_uses_owner_declaration_name_and_rejects_override(client):
    headers = {"Authorization": "Bearer alice"}
    saved = client.post("/api/v1/profile/capabilities", headers=headers, json=payload().model_dump()).json()
    request = attachment(saved["declarations"][0]["id"])
    with patch("app.api.v1.capabilities.validate_cv_match", return_value=source_item()) as verify:
        response = client.post("/api/v1/profile/capabilities/attachment", headers=headers, json=request.model_dump())
    assert response.status_code == 200 and response.json()["version"] == 2
    assert response.headers["Cache-Control"] == "no-store"
    assert verify.call_args.args[1:] == ("Python", "Bearer alice")
    assert client.post("/api/v1/profile/capabilities/attachment", json=request.model_dump()).status_code == 401
    assert client.post("/api/v1/profile/capabilities/attachment", headers=headers, json={**request.model_dump(), "name": "Forged"}).status_code == 422
    assert client.post("/api/v1/profile/capabilities/attachment", headers={"Authorization": "Bearer bob"}, json={**request.model_dump(), "expected_version": 0}).status_code == 409


def test_attachment_history_limit_preserves_existing_source():
    from app.domain.capabilities import revise_attachment
    original = revise_declarations([], payload(), "user")
    original[0]["attachment_history"] = [{"synthetic": True}] * 100
    with pytest.raises(CapabilityLimit): revise_attachment(original, attachment(original[0]["id"]), source_item())
    assert original[0]["attached_to"] is None


def test_public_manual_declaration_uses_same_canonical_identity_as_cv_and_goal():
    from datetime import datetime,timezone
    from app.schemas.capabilities import Declaration
    value=Declaration(id='synthetic',name='SQL',description='I have used SQL.',skill_id='skill:sql',provenance='user_declared',
        contributions=[],created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc))
    assert value.canonical_skill_id=='language.sql'
    assert value.skill_id=='skill:sql'
