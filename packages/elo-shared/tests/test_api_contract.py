"""Published response descriptions do not depend on Python's HTTPStatus phrases."""
from http import HTTPStatus
from elo_shared.runtime import application


def test_error_descriptions_remain_stable_with_python_312_status_phrases(monkeypatch):
    monkeypatch.setattr(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, 'phrase', 'Request Entity Too Large')
    monkeypatch.setattr(HTTPStatus.UNPROCESSABLE_ENTITY, 'phrase', 'Unprocessable Entity')
    app = application('Synthetic contract API', 'ASSESSMENT')

    @app.get('/example')
    def example():
        return {'ok': True}

    responses = app.openapi()['paths']['/example']['get']['responses']
    assert responses['413']['description'] == 'Content Too Large'
    assert responses['422']['description'] == 'Unprocessable Content'
    assert responses['401']['description'] == 'Unauthorized'
