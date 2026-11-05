import json
from pathlib import Path

from app.main import app


def test_published_contract_matches_the_running_service():
    contract = Path(__file__).resolve().parents[3] / 'contracts/api/jobs.yaml'
    assert json.loads(contract.read_text()) == app.openapi()
