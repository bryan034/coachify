from unittest.mock import Mock, patch
import pytest
import requests
from fastapi import HTTPException
from app.clients.cv import validate_cv_match
from app.domain.capabilities import CapabilityConflict
from app.schemas.capabilities import CvMatch


def response(body, status=200):
    import json
    value = Mock(status_code=status)
    value.iter_content.return_value = [json.dumps(body).encode()]
    value.__enter__ = Mock(return_value=value)
    value.__exit__ = Mock(return_value=False)
    return value


def invoke(body, status=200):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.return_value = response(body, status)
    with patch("app.clients.cv.requests.Session", return_value=session):
        result = validate_cv_match(CvMatch(cv_id="cv-one", item_id="item-one", cv_version=3), " Python ", "Bearer synthetic-session")
    return result, session


def cv(**changes):
    return {"id": "cv-one", "version": 3, "status": "ready", "items": [
        {"id": "item-one", "title": "PYTHON", "removed": False, "kind": "skill", "skill_ids": ["skill:python"]}
    ], **changes}


def test_cv_match_forwards_only_owner_bearer_and_disables_redirects(monkeypatch):
    monkeypatch.setenv("CV_SERVICE_URL", "http://synthetic-cv:8000/")
    item, session = invoke(cv())
    assert item["id"] == "item-one"
    assert session.trust_env is False
    session.get.assert_called_once_with("http://synthetic-cv:8000/api/v1/cv/cv-one",
        headers={"Authorization": "Bearer synthetic-session"}, timeout=5, allow_redirects=False, stream=True)


def effective_cv(attribution="personal", **changes):
    item = {"id": "item-one", "title": "Weather station project", "removed": False,
        "kind": "project", "skill_ids": ["skill:python"], "source_fingerprint": "a" * 64}
    skill = {"skill_id": "skill:python", "item_ids": ["item-one", "independent"],
        "sources": [{"item_id": "item-one", "attribution": attribution},
            {"item_id": "independent", "attribution": "personal"}]}
    return cv(items=[item], skills=[skill], **changes)


@pytest.mark.parametrize("kind", ["project", "experience", "education", "skill"])
def test_effective_skill_attachment_uses_source_identity_not_item_title(kind):
    value = effective_cv()
    value["items"][0]["kind"] = kind
    item, _ = invoke(value)
    assert item["_matched_skill_id"] == "skill:python"
    assert item["_attachment_fingerprint"] == "a" * 64


@pytest.mark.parametrize("attribution", ["team", "observed", "denied"])
def test_other_independent_evidence_does_not_authorize_a_denied_source_attachment(attribution):
    with pytest.raises(CapabilityConflict) as exc:
        invoke(effective_cv(attribution))
    assert exc.value.code == "match_changed"


def test_effective_source_identity_is_required_and_unknown_fingerprint_is_not_invented():
    value = effective_cv("unknown")
    value["items"][0].pop("source_fingerprint")
    item, _ = invoke(value)
    assert item["_attachment_fingerprint"] is None
    value["skills"][0]["item_ids"] = ["independent"]
    with pytest.raises(CapabilityConflict): invoke(value)
    value = effective_cv()
    value["items"][0]["skill_ids"] = []
    with pytest.raises(CapabilityConflict): invoke(value)


@pytest.mark.parametrize("fingerprint", ["invented", 7, "A" * 64])
def test_invalid_source_fingerprint_is_recoverable_not_persistable(fingerprint):
    value = effective_cv()
    value["items"][0]["source_fingerprint"] = fingerprint
    with pytest.raises(HTTPException) as exc: invoke(value)
    assert exc.value.status_code == 503


@pytest.mark.parametrize("value", [
    cv(version=4), cv(status="failed"), cv(id="different"), cv(items=[]),
    cv(items=[{"id": "item-one", "title": "Python", "removed": True}]),
    cv(items=[{"id": "item-one", "title": "SQL", "removed": False}]),
])
def test_changed_or_removed_source_is_conflict(value):
    with pytest.raises(CapabilityConflict) as error:
        invoke(value)
    assert error.value.code == "match_changed"


@pytest.mark.parametrize("status", [403, 404])
def test_other_owner_or_missing_cv_never_attaches(status):
    with pytest.raises(CapabilityConflict):
        invoke({}, status)


@pytest.mark.parametrize("status,expected", [(401, 401), (302, 503), (500, 503), (503, 503)])
def test_unavailable_cv_is_recoverable(status, expected):
    with pytest.raises(HTTPException) as error:
        invoke({}, status)
    assert error.value.status_code == expected


def test_cv_failure_does_not_expose_connection_details():
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.side_effect = requests.ConnectionError("private connection address")
    with patch("app.clients.cv.requests.Session", return_value=session):
        with pytest.raises(HTTPException) as error:
            validate_cv_match(CvMatch(cv_id="cv-one", item_id="item-one", cv_version=1), "Python", "Bearer synthetic")
    assert error.value.status_code == 503
    assert "private connection" not in error.value.detail
