import json
from pathlib import Path

from app.main import app


def test_published_dashboard_contract_matches_service():
    contract = Path(__file__).resolve().parents[3] / 'contracts/api/dashboard.yaml'
    assert json.loads(contract.read_text()) == app.openapi()
