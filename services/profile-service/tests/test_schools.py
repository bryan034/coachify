import json
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.domain.schools import snapshot


def test_categories_order_and_snapshot_search():
    with TestClient(create_app(repository=object())) as client:
        categories = client.get("/api/v1/profile/school-categories").json()
        assert [c["label"] for c in categories] == ["Secondary School", "Institute of Technical Education", "Polytechnic / Diploma", "Junior College", "University"]
        for category in categories:
            result = client.get("/api/v1/profile/institutions", params={"category": category["id"], "limit": 2}).json()
            assert result["total"] > 0
            assert len(result["items"]) <= 2
            assert all(category["id"] in r["categories"] for r in result["items"])
        us = client.get("/api/v1/profile/institutions", params={"category": "university", "q": "harvard", "country": "US"}).json()
        assert us["total"] >= 1
        assert all(r["country_code"] == "US" for r in us["items"])
        countries = client.get("/api/v1/profile/school-countries").json()
        assert len(countries) > 150
        assert client.get("/api/v1/profile/institutions?category=invalid").status_code == 422
        assert client.get("/api/v1/profile/institutions?category=university&limit=1000").status_code == 422
        assert client.get("/api/v1/profile/institutions?category=university&offset=-1").status_code == 422
        empty = client.get("/api/v1/profile/institutions?category=university&q=nonexistent-xyz-123").json()
        assert empty["items"] == []


def test_snapshot_ids_and_provenance():
    data = snapshot()
    assert len(data["institutions"]) > 10000
    assert len({r["id"] for r in data["institutions"]}) == len(data["institutions"])
    assert data["sources"]["hipo"]["revision"]
    assert all(set(r) == {"id", "name", "country_code", "country", "categories", "domains", "source"} for r in data["institutions"])
