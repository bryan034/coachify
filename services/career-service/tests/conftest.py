import json
from pathlib import Path
import pytest


@pytest.fixture
def documents():
    return json.loads((Path(__file__).parent / 'fixtures/analysis.json').read_text())
