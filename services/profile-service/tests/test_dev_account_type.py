from fastapi.testclient import TestClient
from app.main import create_app
from tests.test_capabilities import SessionAccounts, client, database, repo


def test_development_switches_only_the_callers_plan(client, repo):
    for plan in ("premium", "free"):
        response = client.put("/api/v1/profile/dev/account-type", json={"account_type": plan},
                              headers={"Authorization": "Bearer alice"})
        assert response.status_code == 200, response.text
        assert response.json() == {"account_type": plan}
        assert repo.account("alice")["account_type"] == plan
    assert "account_type" not in repo.account("bob")


class OrphanSession(SessionAccounts):
    def session(self, token, _settings):
        return {"owner": "carol", "id": "carol-id"}


def test_plan_switch_rejects_a_session_without_an_account(repo):
    with TestClient(create_app(repository=object(), accounts=OrphanSession(), capabilities=repo)) as client:
        response = client.put("/api/v1/profile/dev/account-type", json={"account_type": "premium"},
                              headers={"Authorization": "Bearer carol"})
    assert response.status_code == 401
    assert repo.accounts.find_one({"owner": "carol"}) is None


def test_plan_switch_rejects_unknown_plans_and_anonymous_callers(client, repo):
    assert client.put("/api/v1/profile/dev/account-type", json={"account_type": "enterprise"},
                      headers={"Authorization": "Bearer alice"}).status_code == 422
    assert client.put("/api/v1/profile/dev/account-type", json={"account_type": "premium"}).status_code == 401
    assert "account_type" not in repo.account("alice")


def test_plan_switch_is_absent_outside_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    app = create_app(repository=object(), accounts=SessionAccounts())
    assert not [route for route in app.routes if "/dev/" in getattr(route, "path", "")]
