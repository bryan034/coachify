import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app, create_app


def test_published_contract_matches_the_running_service():
    contract = Path(__file__).resolve().parents[3] / 'contracts/api/socials.yaml'
    assert json.loads(contract.read_text()) == app.openapi()


def test_socials_requires_an_authenticated_session():
    with TestClient(create_app(recover=False)) as client:
        for path in ('workspace', 'agenda', 'expert/requests', 'operator/reports'):
            response = client.get(f'/api/v1/socials/{path}')
            assert response.status_code == 401
            assert response.headers['Cache-Control'] == 'no-store'
