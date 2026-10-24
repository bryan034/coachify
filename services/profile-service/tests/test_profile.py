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


def test_google_claim_verification_requires_audience_issuer_subject_and_attempt_nonce(monkeypatch):
    from app.core.auth import verify_google
    from fastapi import HTTPException
    for claims in ({"iss": "evil", "sub": "alice", "nonce": "nonce"},
                   {"iss": "accounts.google.com", "nonce": "nonce"},
                   {"iss": "accounts.google.com", "sub": "alice", "nonce": "wrong"}):
        with patch("app.core.auth.id_token.verify_oauth2_token", return_value=claims):
            with pytest.raises(HTTPException) as error:
                verify_google("token", "client", "nonce")
            assert error.value.status_code == 401
    with patch("app.core.auth.id_token.verify_oauth2_token", return_value={"iss": "https://accounts.google.com", "sub": "alice", "nonce": "nonce"}) as verify:
        assert verify_google("token", "client", "nonce")["sub"] == "alice"
        assert verify.call_args.args[2] == "client"
    with patch("app.core.auth.id_token.verify_oauth2_token", side_effect=TransportError("offline")):
        with pytest.raises(HTTPException) as error:
            verify_google("token", "client", "nonce")
        assert error.value.status_code == 503


def test_local_mode_no_longer_auto_authenticates_or_accepts_caller_owner(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "local_test")
    monkeypatch.setenv("LOCAL_TEST_USER_ID", "ignored-old-setting")
    with TestClient(create_app(MemoryRepository())) as client:
        assert client.get("/api/v1/profile?user_id=alice", headers={"X-User-Id": "alice"}).status_code == 401


@pytest.mark.parametrize("environment", [None, "production", "staging", "test", "Development"])
def test_local_identity_refuses_non_development_startup(monkeypatch, environment):
    monkeypatch.setenv("AUTH_MODE", "local_test")
    if environment is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", environment)
    with pytest.raises(RuntimeError, match="APP_ENV"):
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


@pytest.mark.parametrize("category", ["secondary", "ite", "polytechnic", "junior_college", "university"])
def test_custom_education_roundtrip_for_every_category(client, category):
    body = payload(school_category=category, education={
        "institution": {"kind": "custom", "name": "  École Test — International  ", "country_code": "FR"},
        "course": "  Computing & Design (Double Programme)  ", "study_year": 5,
    })
    response = client.patch("/api/v1/profile", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["education"]["institution"]["name"] == "École Test — International"
    assert saved["education"]["institution"]["id"] is None
    assert saved["education"]["course"] == "Computing & Design (Double Programme)"
    assert saved["education"]["study_year"] == 5
    assert saved["education"]["study_year_label"] == ({"secondary": "Secondary", "junior_college": "JC"}.get(category, "Year") + " 5")
    assert saved["current_study_year"] == 5
    assert client.get("/api/v1/profile").json() == saved


def test_catalogue_identity_is_resolved_by_server(client):
    from app.domain.schools import snapshot
    row = next(r for r in snapshot()["institutions"] if "university" in r["categories"])
    body = payload(education={"institution": {"kind": "catalogue", "id": row["id"]}})
    response = client.patch("/api/v1/profile", json=body)
    assert response.status_code == 200
    school = response.json()["education"]["institution"]
    assert school["name"] == row["name"] and school["id"] == row["id"]
    assert school["snapshot_date"] == snapshot()["snapshot_date"]
    forged = payload(expected_version=1, education={"institution": {"kind": "catalogue", "id": row["id"], "name": "Forged"}})
    assert client.patch("/api/v1/profile", json=forged).status_code == 422


@pytest.mark.parametrize("education", [
    {"institution": {"kind": "catalogue", "id": "missing"}},
    {"institution": {"kind": "custom", "name": "   "}},
    {"institution": {"kind": "custom", "name": "School\u0000"}},
    {"institution": {"kind": "custom", "name": "Valid", "country_code": "invalid"}},
    {"institution": None}, {"course": False}, {"course": "   "}, {"course": "bad\nname"},
    {"study_year": 0}, {"study_year": -1}, {"study_year": 1.5},
    {"study_year": "2"}, {"study_year": None}, {"study_year": True},
    {"owner": "bob"},
])
def test_bad_education_does_not_change_saved_profile(client, education):
    original = client.patch("/api/v1/profile", json=payload()).json()
    response = client.patch("/api/v1/profile", json={"expected_version": 1, "education": education})
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], list)
    assert client.get("/api/v1/profile").json() == original


def test_category_mismatch_rejects_catalogue_institution(client):
    from app.domain.schools import snapshot
    row = next(r for r in snapshot()["institutions"] if r["categories"] == ["polytechnic"])
    response = client.patch("/api/v1/profile", json=payload(education={"institution": {"kind": "catalogue", "id": row["id"]}}))
    assert response.status_code == 422


def test_independent_field_updates_history_and_context_review(client):
    first = client.patch("/api/v1/profile", json=payload(education={
        "institution": {"kind": "custom", "name": "School A"}, "course": "Computer Science", "study_year": 6,
    })).json()
    changed = client.patch("/api/v1/profile", json={"expected_version": 1, "education": {"course": "Arts & Computing"}})
    assert changed.status_code == 200, changed.text
    second = changed.json()
    assert second["education"]["institution"] == first["education"]["institution"]
    assert second["education"]["study_year"] == 6
    assert second["occupational_status"] == "student"
    assert second["school_category"] == "university"
    assert client.get("/api/v1/profile/versions/1").json() == first
    assert client.patch("/api/v1/profile", json={"expected_version": 1, "education": {"course": "Stale"}}).status_code == 409
    third = client.patch("/api/v1/profile", json={"expected_version": 2, "occupational_status": "employed"}).json()
    assert third["education"] == second["education"]
    assert third["current_study_year"] is None
    assert third["education_review_required"]
    fourth = client.patch("/api/v1/profile", json={"expected_version": 3, "occupational_status": "student"}).json()
    assert fourth["current_study_year"] is None  # Not silently reactivated.
    rejected = client.patch("/api/v1/profile", json={"expected_version": 4, "education": {"course": "New course"}})
    assert rejected.status_code == 422
    confirmed = client.patch("/api/v1/profile", json={"expected_version": 4, "confirm_education_context": True}).json()
    assert confirmed["current_study_year"] == 6
    assert not confirmed["education_review_required"]


def test_changed_institution_prompts_review_of_retained_course_and_year(client):
    client.patch("/api/v1/profile", json=payload(education={"institution": {"kind": "custom", "name": "Old school"}, "course": "Design", "study_year": 2}))
    response = client.patch("/api/v1/profile", json={"expected_version": 1, "education": {"institution": {"kind": "custom", "name": "New school"}}}).json()
    assert response["education"]["course"] == "Design"
    assert response["education_review_required"]
    assert response["current_study_year"] is None


def test_category_switch_cannot_silently_relabel_year(client):
    client.patch("/api/v1/profile", json=payload(education={"institution": {"kind": "custom", "name": "School"}, "study_year": 5}))
    changed = client.patch("/api/v1/profile", json={"expected_version": 1, "school_category": "junior_college"}).json()
    assert changed["education"]["study_year_label"] == "Year 5"
    assert changed["education"]["category"] == "university"
    assert client.patch("/api/v1/profile", json={"expected_version": 2, "confirm_education_context": True}).status_code == 422
    reviewed = client.patch("/api/v1/profile", json={"expected_version": 2, "confirm_education_context": True, "education": {"study_year": 2}}).json()
    assert reviewed["education"]["study_year_label"] == "JC 2"
    assert reviewed["education"]["category"] == "junior_college"


def test_nonstudent_optional_course_and_institution_without_current_year(client):
    response = client.patch("/api/v1/profile", json=payload(occupational_status="unemployed", school_category=None, education={"institution": None, "course": None}))
    assert response.status_code == 200
    assert response.json()["education"]["context"] == "last"
    assert client.patch("/api/v1/profile", json={"expected_version": 1, "education": {"study_year": 1}}).status_code == 422


def test_education_noop_retry_and_owner_isolation(client):
    body = payload(education={"course": "Design", "study_year": 1})
    first = client.patch("/api/v1/profile", json=body).json()
    noop = client.patch("/api/v1/profile", json={"expected_version": 1, "education": {"course": "Design"}}).json()
    assert noop == first
    client.app.dependency_overrides[current_owner] = lambda: "google:bob"
    assert client.get("/api/v1/profile").json()["education"]["course"] is None
    assert client.get("/api/v1/profile/versions/1").status_code == 404


def test_text_normalisation_precedes_length_validation(client):
    text = "A" * 300
    response = client.patch("/api/v1/profile", json=payload(education={
        "institution": {"kind": "custom", "name": "  " + text + "  "}, "course": "  " + text + "  ",
    }))
    assert response.status_code == 200, response.text
    assert response.json()["education"]["course"] == text


def test_auth_config_reports_only_server_mode_and_cannot_enable_local_mode(monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    with TestClient(create_app(MemoryRepository())) as client:
        assert client.get("/api/v1/profile/auth-config?mode=local_test").json() == {"mode": "email", "email_password_enabled": True, "google_enabled": False, "email_verification_required": True, "development_tools_enabled": True}
        assert client.get("/api/v1/profile").status_code == 401
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_MODE", "local_test")
    with TestClient(create_app(MemoryRepository())) as client:
        assert client.get("/api/v1/profile/auth-config").json() == {"mode": "local_test", "email_password_enabled": True, "google_enabled": False, "email_verification_required": True, "development_tools_enabled": True}
        assert client.get("/api/v1/profile").status_code == 401


def test_employment_round_trip_partial_updates_history_and_inactive_status(client):
    first = client.patch('/api/v1/profile', json=payload(occupational_status='employed', employment={'employer':'  Synthetic company  ','role':'Synthetic analyst'}))
    assert first.status_code == 200
    assert first.json()['employment'] == {'employer':'Synthetic company','role':'Synthetic analyst','industry':None}
    second = client.patch('/api/v1/profile', json={'expected_version':1,'employment':{'role':'Senior analyst'}})
    assert second.json()['employment'] == {'employer':'Synthetic company','role':'Senior analyst','industry':None}
    assert client.get('/api/v1/profile/versions/1').json()['employment']['role'] == 'Synthetic analyst'
    inactive = client.patch('/api/v1/profile', json={'expected_version':2,'occupational_status':'unemployed'})
    assert inactive.json()['employment'] == second.json()['employment']
    assert client.patch('/api/v1/profile', json={'expected_version':3,'employment':{'employer':'Another company'}}).status_code == 422
    assert client.get('/api/v1/profile').json()['version'] == 3


@pytest.mark.parametrize('employment',[None,{'employer':' '},{'role':'bad\nrole'},{'employer':True},{'role':'x'*301},{'owner':'someone'}])
def test_invalid_employment_is_not_saved(client, employment):
    assert client.patch('/api/v1/profile', json=payload(occupational_status='employed', employment=employment)).status_code == 422
    assert client.get('/api/v1/profile').json()['version'] == 0


def test_employed_completion_requires_both_work_fields_and_does_not_reset_old_completion():
    from app.domain.profile import complete_onboarding
    from app.domain.errors import ProfileValidationError
    base = {'expected_version':0,'occupational_status':'employed','school_category':None,'no_previous_education':True}
    for employment in ({},{'employer':'Synthetic company'},{'role':'Synthetic role'}):
        with pytest.raises(ProfileValidationError):
            complete_onboarding(None, ProfilePatch(**base,employment=employment))
    completed = complete_onboarding(None, ProfilePatch(**base, employment={'employer':'Synthetic company','role':'Synthetic role','industry':'Synthetic industry'}))
    assert completed['onboarding_complete']
    # Earlier completed accounts stay completed and can add details voluntarily.
    old = {**completed}; old.pop('employment')
    assert complete_onboarding(old, ProfilePatch(expected_version=1,occupational_status='employed')) == old


def test_preview_capability_is_server_environment_controlled():
    from dataclasses import replace
    with TestClient(create_app(MemoryRepository())) as client:
        client.app.state.auth_settings = replace(client.app.state.auth_settings, environment='production', mode='email')
        result = client.get('/api/v1/profile/auth-config?development_tools_enabled=true').json()
        assert result['development_tools_enabled'] is False
        client.app.state.auth_settings = replace(client.app.state.auth_settings, environment='development')
        assert client.get('/api/v1/profile/auth-config').json()['development_tools_enabled'] is True


@pytest.mark.parametrize('answer', [True, False])
def test_unemployed_onboarding_requires_explicit_work_history_and_complete_details(answer):
    from app.domain.profile import complete_onboarding
    from app.domain.errors import ProfileValidationError
    base = dict(expected_version=0, occupational_status='unemployed', no_previous_education=True)
    with pytest.raises(ProfileValidationError, match='previously employed'):
        complete_onboarding(None, ProfilePatch(**base))
    work = {'employer': 'An unlisted synthetic organisation', 'role': 'Synthetic role', 'industry': 'A custom industry'}
    if answer:
        for missing in work:
            with pytest.raises(ProfileValidationError):
                complete_onboarding(None, ProfilePatch(**base, previously_employed=True, employment={k:v for k,v in work.items() if k != missing}))
    saved = complete_onboarding(None, ProfilePatch(**base, previously_employed=answer, **({'employment':work} if answer else {})))
    assert saved['onboarding_complete'] and saved['previously_employed'] is answer
    if answer:
        assert saved['employment'] == work


def test_work_history_is_confirmed_not_inferred_and_false_retains_but_disables_work_edits(client):
    current = client.patch('/api/v1/profile', json=payload(occupational_status='employed', employment={'employer':'Unlisted company','role':'Analyst','industry':'Custom industry'})).json()
    previous = client.patch('/api/v1/profile', json={'expected_version':1,'occupational_status':'unemployed'}).json()
    assert previous['previously_employed'] is None
    assert previous['employment'] == current['employment']
    confirmed = client.patch('/api/v1/profile', json={'expected_version':2,'previously_employed':True,'employment':{'industry':'  Different industry  '}}).json()
    assert confirmed['employment']['industry'] == 'Different industry'
    declined = client.patch('/api/v1/profile', json={'expected_version':3,'previously_employed':False}).json()
    assert declined['employment'] == confirmed['employment']
    assert client.patch('/api/v1/profile', json={'expected_version':4,'employment':{'role':'Another role'}}).status_code == 422
    client.patch('/api/v1/profile', json={'expected_version':4,'occupational_status':'employed'})
    returned = client.patch('/api/v1/profile', json={'expected_version':5,'occupational_status':'unemployed'}).json()
    assert returned['previously_employed'] is None


@pytest.mark.parametrize('answer',[None,'true',1])
def test_work_history_answer_must_be_a_boolean(client, answer):
    assert client.patch('/api/v1/profile', json=payload(occupational_status='unemployed', previously_employed=answer)).status_code == 422


@pytest.mark.parametrize('value',[' ', 'invalid\nindustry', 'x'*301, True])
def test_industry_validation(client, value):
    assert client.patch('/api/v1/profile', json=payload(occupational_status='employed',employment={'industry':value})).status_code == 422


def test_employment_reference_directory_search_and_bounds(client):
    assert client.get('/api/v1/profile/companies',params={'q':'dbs'}).json()[0]['name'] == 'DBS Bank'
    assert client.get('/api/v1/profile/companies',params={'q':'microsoft'}).json()[0]['name'] == 'Microsoft'
    assert client.get('/api/v1/profile/industries',params={'q':'technology'}).json()[0]['name'] == 'Technology and software'
    assert client.get('/api/v1/profile/companies',params={'q':'nonexistent synthetic company'}).json() == []
    assert len(client.get('/api/v1/profile/companies',params={'limit':3}).json()) == 3
    for params in ({'limit':0},{'limit':101},{'q':'x'*151}):
        assert client.get('/api/v1/profile/companies',params=params).status_code == 422


def test_graduation_year_round_trip_version_history_and_completion():
    from app.domain.profile import complete_onboarding
    from app.domain.errors import ProfileValidationError
    base = dict(expected_version=0, occupational_status='unemployed', previously_employed=False,
                school_category='university', education={'institution':{'kind':'custom','name':'Synthetic graduate school'}})
    with pytest.raises(ProfileValidationError, match='graduation year'):
        complete_onboarding(None, ProfilePatch(**base))
    base['education']['graduation_year'] = 2024
    finished = complete_onboarding(None, ProfilePatch(**base))
    assert finished['education']['graduation_year'] == 2024
    assert finished['education']['course'] is None
    assert finished['onboarding_complete']
    # Other branches and explicit no-education do not require a graduation year.
    assert complete_onboarding(None, ProfilePatch(expected_version=0, occupational_status='unemployed', previously_employed=False,
                                                school_category=None, no_previous_education=True))['onboarding_complete']


def test_graduation_year_saved_and_editable_in_profile_history(client):
    body=payload(occupational_status='unemployed',previously_employed=False,education={
        'institution':{'kind':'custom','name':'Synthetic graduate school'},'graduation_year':2024})
    first=client.patch('/api/v1/profile',json=body)
    assert first.status_code == 200, first.text
    assert client.get('/api/v1/profile').json()['education']['graduation_year'] == 2024
    changed=client.patch('/api/v1/profile',json={'expected_version':1,'education':{'graduation_year':2023}})
    assert changed.json()['education']['graduation_year'] == 2023
    assert client.get('/api/v1/profile/versions/1').json()['education']['graduation_year'] == 2024
    retained=client.patch('/api/v1/profile',json={'expected_version':2,'occupational_status':'employed'}).json()
    assert retained['education']['graduation_year'] == 2023


@pytest.mark.parametrize('year',[1899,9999,2024.5,True,'2024'])
def test_invalid_graduation_year_never_saves(client,year):
    response=client.patch('/api/v1/profile',json=payload(occupational_status='unemployed',previously_employed=False,
        education={'institution':{'kind':'custom','name':'Synthetic school'},'graduation_year':year}))
    assert response.status_code == 422
    assert client.get('/api/v1/profile').json()['version'] == 0


@pytest.mark.parametrize('changes',[{'occupational_status':'student'}, {'occupational_status':'employed'},
    {'occupational_status':'unemployed','previously_employed':True}])
def test_graduation_year_is_only_changed_for_never_employed_users(client,changes):
    assert client.patch('/api/v1/profile',json=payload(**changes,education={
        'institution':{'kind':'custom','name':'Synthetic school'},'graduation_year':2024})).status_code == 422


def test_graduation_year_requires_school_and_new_school_reviews_retained_year(client):
    assert client.patch('/api/v1/profile',json=payload(occupational_status='unemployed',previously_employed=False,
        education={'graduation_year':2024})).status_code == 422
    client.patch('/api/v1/profile',json=payload(occupational_status='unemployed',previously_employed=False,
        education={'institution':{'kind':'custom','name':'Synthetic old school'},'graduation_year':2024}))
    changed=client.patch('/api/v1/profile',json={'expected_version':1,'education':{'institution':{'kind':'custom','name':'Synthetic new school'}}}).json()
    assert changed['education_review_required'] is True
    assert changed['education']['graduation_year'] == 2024
