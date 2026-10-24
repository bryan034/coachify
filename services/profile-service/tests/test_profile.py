from copy import deepcopy
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import TransportError
from app.core.auth import current_owner
from app.domain.profile import revise_profile
from app.main import create_app
from app.repositories.profile import VersionConflict
from app.schemas.profile import ProfilePatch


class MemoryRepository:
    def __init__(self):
        self.records = {}

    def current(self, owner):
        return deepcopy(self.records.get(owner, [None])[-1])

    def version(self, owner, version):
        return next((deepcopy(p) for p in self.records.get(owner, []) if p["version"] == version), None)

    def update(self, owner, patch):
        previous = self.current(owner)
        if (previous or {}).get("version", 0) != patch.expected_version:
            raise VersionConflict
        profile = revise_profile(previous, patch)
        if previous != profile:
            self.records.setdefault(owner, []).append(profile)
        return profile


@pytest.fixture
def client():
    app = create_app(MemoryRepository())
    app.dependency_overrides[current_owner] = lambda: "google:alice"
    with TestClient(app) as client:
        yield client


def payload(**updates):
    return {"expected_version": 0, "occupational_status": "student", "school_category": "university", **updates}


@pytest.mark.parametrize("status", ["student", "national_service", "unemployed", "employed"])
@pytest.mark.parametrize("category", ["secondary", "ite", "polytechnic", "junior_college", "university"])
def test_status_category_round_trip(client, status, category):
    response = client.patch("/api/v1/profile", json=payload(occupational_status=status, school_category=category))
    assert response.status_code == 200
    saved = response.json()
    assert saved["version"] == 1
    assert saved["education_context"] == ("current" if status == "student" else "last")
    assert saved["school_category"] == category
    assert client.get("/api/v1/profile").json() == saved


@pytest.mark.parametrize("updates", [
    {"occupational_status": None}, {"occupational_status": "working"},
    {"school_category": "primary"}, {"school_category": None},
    {"expected_version": -1}, {"expected_version": True}, {"owner": "google:bob"},
])
def test_invalid_write_does_not_persist(client, updates):
    assert client.patch("/api/v1/profile", json=payload(**updates)).status_code == 422
    assert client.get("/api/v1/profile").json()["version"] == 0


def test_status_required(client):
    assert client.patch("/api/v1/profile", json={"expected_version": 0}).status_code == 422


@pytest.mark.parametrize("status", ["national_service", "unemployed", "employed"])
def test_nonstudent_can_omit_education(client, status):
    response = client.patch("/api/v1/profile", json=payload(occupational_status=status, school_category=None))
    assert response.status_code == 200
    assert response.json()["school_category"] is None


def test_versions_conflict_and_owner_isolation(client):
    first = client.patch("/api/v1/profile", json=payload()).json()
    assert client.patch("/api/v1/profile", json=payload(occupational_status="employed")).status_code == 409
    second = client.patch("/api/v1/profile", json=payload(expected_version=1, occupational_status="employed")).json()
    assert second["education_review_required"]
    assert client.get("/api/v1/profile/versions/1").json() == first
    # No-op saves do not invent new history.
    assert client.patch("/api/v1/profile", json=payload(expected_version=2, occupational_status="employed")).json()["version"] == 2
    client.app.dependency_overrides[current_owner] = lambda: "google:bob"
    assert client.get("/api/v1/profile").json()["version"] == 0
    assert client.get("/api/v1/profile/versions/1").status_code == 404


def test_status_switch_preserves_education_and_other_fields():
    old = {"version": 8, "occupational_status": "student", "school_category": "secondary", "education": {"institution": "Test School", "level": 3, "context": "current"}, "availability": 10}
    original = deepcopy(old)
    revised = revise_profile(old, ProfilePatch(**payload(expected_version=8, occupational_status="employed", school_category=None)))
    assert old == original
    assert revised["education"] == original["education"]
    assert revised["availability"] == 10
    assert revised["education_context"] == "last"
    assert revised["education_review_required"]
    # Retained data is awaiting review, not automatically reclassified as past.
    assert revised["education"]["context"] == "current"


def test_database_failure_is_retryable(client):
    from pymongo.errors import AutoReconnect
    with patch.object(client.app.state.repository, "update", side_effect=AutoReconnect("private connection detail")):
        response = client.patch("/api/v1/profile", json=payload())
    assert response.status_code == 503
    assert "private connection" not in response.text
    assert client.get("/api/v1/profile").json()["version"] == 0
    assert client.patch("/api/v1/profile", json=payload()).status_code == 200


def test_auth_rejects_missing_and_invalid_token(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client")
    with TestClient(create_app(MemoryRepository())) as client:
        assert client.get("/api/v1/profile").status_code == 401
        with patch("app.core.auth.id_token.verify_oauth2_token", side_effect=ValueError("bad token")):
            assert client.get("/api/v1/profile", headers={"Authorization": "Bearer invalid"}).status_code == 401
        with patch("app.core.auth.id_token.verify_oauth2_token", return_value={"iss": "evil", "sub": "alice"}):
            assert client.get("/api/v1/profile", headers={"Authorization": "Bearer invalid"}).status_code == 401
        with patch("app.core.auth.id_token.verify_oauth2_token", return_value={"iss": "https://accounts.google.com", "sub": "alice"}) as verify:
            assert client.patch("/api/v1/profile", json=payload(), headers={"Authorization": "Bearer verified-by-mock"}).status_code == 200
            assert verify.call_args.args[2] == "test-client"
        with patch("app.core.auth.id_token.verify_oauth2_token", side_effect=TransportError("offline")):
            assert client.get("/api/v1/profile", headers={"Authorization": "Bearer invalid"}).status_code == 503


def test_local_identity_needs_no_google_and_ignores_caller_identity(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "local_test")
    monkeypatch.setenv("LOCAL_TEST_USER_ID", "postman-user")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    repo = MemoryRepository()
    with patch("app.core.auth.id_token.verify_oauth2_token") as verify:
        with TestClient(create_app(repo)) as client:
            assert client.get("/api/v1/profile").status_code == 200
            saved = client.patch("/api/v1/profile", json=payload()).json()
            response = client.get("/api/v1/profile?user_id=google:bob", headers={
                "Authorization": "Bearer ignored-in-local-mode", "X-User-Id": "google:bob",
            })
            assert response.json() == saved
            assert set(repo.records) == {"local_test:postman-user"}
        verify.assert_not_called()


@pytest.mark.parametrize("environment", [None, "production", "staging", "test", "Development"])
def test_local_identity_refuses_non_development_startup(monkeypatch, environment):
    monkeypatch.setenv("AUTH_MODE", "local_test")
    if environment is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", environment)
    with pytest.raises(RuntimeError, match="APP_ENV=development"):
        with TestClient(create_app(MemoryRepository())):
            pass


@pytest.mark.parametrize("identity", ["", "bad:user", "bad user", "x" * 65])
def test_local_identity_rejects_invalid_fixed_id(monkeypatch, identity):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "local_test")
    monkeypatch.setenv("LOCAL_TEST_USER_ID", identity)
    with pytest.raises(RuntimeError, match="LOCAL_TEST_USER_ID"):
        with TestClient(create_app(MemoryRepository())):
            pass


def test_google_remains_default_even_with_local_identity_setting(monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LOCAL_TEST_USER_ID", "postman-user")
    with TestClient(create_app(MemoryRepository())) as client:
        assert client.get("/api/v1/profile", headers={"X-User-Id": "postman-user"}).status_code == 401


def test_unknown_auth_mode_cannot_enable_bypass(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "local")
    with pytest.raises(RuntimeError, match="AUTH_MODE"):
        with TestClient(create_app(MemoryRepository())):
            pass


def test_changing_fixed_identity_uses_separate_profile(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "local_test")
    repo = MemoryRepository()
    monkeypatch.setenv("LOCAL_TEST_USER_ID", "alice")
    with TestClient(create_app(repo)) as client:
        assert client.patch("/api/v1/profile", json=payload()).status_code == 200
    monkeypatch.setenv("LOCAL_TEST_USER_ID", "bob")
    with TestClient(create_app(repo)) as client:
        assert client.get("/api/v1/profile").json()["version"] == 0
        assert client.get("/api/v1/profile/versions/1").status_code == 404
