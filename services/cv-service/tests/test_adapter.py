import json
import httpx
import pytest
from app.clients.extractor import Extractor


def configure(monkeypatch):
    monkeypatch.setenv('CV_LLM_API_KEY', 'synthetic-test-key')
    monkeypatch.setenv('CV_LLM_MODEL', 'synthetic-test-model')
    monkeypatch.setenv('CV_LLM_BASE_URL', 'https://provider.example/v1')


def test_unconfigured_is_actionable_failure(monkeypatch):
    monkeypatch.delenv('CV_LLM_API_KEY', raising=False)
    monkeypatch.delenv('CV_LLM_MODEL', raising=False)
    extractor = Extractor()
    assert extractor.configured is False
    with pytest.raises(ValueError, match='not configured'): extractor.extract([])


def test_http_requires_explicit_development_setting(monkeypatch):
    monkeypatch.setenv('CV_LLM_BASE_URL', 'http://fixture:9000/v1')
    monkeypatch.setenv('CV_LLM_ALLOW_HTTP', 'true')
    monkeypatch.setenv('APP_ENV', 'production')
    with pytest.raises(RuntimeError): Extractor()
    monkeypatch.setenv('APP_ENV', 'development')
    assert Extractor().base_url.startswith('http://fixture')


@pytest.mark.parametrize('finish,content,expected', [('stop', '{"items":[]}', True), ('length', '{"items":[]}', False), ('stop', 'not json', False)])
def test_compatible_provider_contract_and_incomplete_output(monkeypatch, finish, content, expected):
    configure(monkeypatch)
    requests = []
    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': {'content': content}}]})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    extractor = Extractor()
    if expected:
        output, metadata = extractor.extract([{'id': 'b1', 'location': 'Page 1', 'text': 'Synthetic CV'}])
        assert output == {'items': []}
        assert metadata['model'] == 'synthetic-test-model'
        assert requests[0]['response_format'] == {'type': 'json_object'}
        assert json.loads(requests[0]['messages'][-1]['content'])['source_blocks'][0]['id'] == 'b1'
    else:
        with pytest.raises(ValueError): extractor.extract([])
