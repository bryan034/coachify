import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from pymongo import MongoClient
from app.repositories.profile import ProfileRepository, VersionConflict
from app.schemas.profile import ProfilePatch

pytestmark = pytest.mark.skipif(not os.getenv("MONGODB_TEST_URI"), reason="Set MONGODB_TEST_URI for real MongoDB integration tests")


def test_real_mongodb_roundtrip_concurrency_and_restart():
    client = MongoClient(os.environ["MONGODB_TEST_URI"], serverSelectionTimeoutMS=5000)
    name = "coachify_test_" + uuid4().hex
    try:
        repo = ProfileRepository(client[name])
        patch = ProfilePatch(expected_version=0, occupational_status="student", school_category="university")
        def save(_):
            try:
                return repo.update("alice", patch)["version"]
            except VersionConflict:
                return "conflict"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save, range(2)))
        assert sorted(map(str, results)) == ["1", "conflict"]
        restored = ProfileRepository(client[name])
        assert restored.current("alice")["school_category"] == "university"
        assert restored.current("bob") is None
        restored.update("alice", ProfilePatch(expected_version=1, occupational_status="employed", school_category=None))
        assert restored.version("alice", 1)["education_context"] == "current"
        assert restored.current("alice")["education_context"] == "last"
        assert restored.current("alice")["education_review_required"]
    finally:
        client.drop_database(name)
        client.close()
