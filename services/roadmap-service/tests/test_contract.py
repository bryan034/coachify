import json
from pathlib import Path
from app.main import app
from app.schemas import Plan

def test_published_contracts_match_the_running_service_models():
    root=Path(__file__).resolve().parents[3]/'contracts/api'
    assert json.loads((root/'roadmap.yaml').read_text())==app.openapi()
    assert json.loads((root/'models/roadmap.schema.json').read_text())==Plan.model_json_schema()
