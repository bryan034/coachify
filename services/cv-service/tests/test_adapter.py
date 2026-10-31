import json
import httpx
import pytest
from app.clients.extractor import Extractor
from app.clients.conversation import ConversationRouter
from app.clients.interpretation import Interpreter


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


@pytest.mark.parametrize('provider_class',[Extractor,ConversationRouter,Interpreter])
@pytest.mark.parametrize('key',['','preserved-cloud-key'])
def test_local_ollama_is_keyless_and_never_forwards_cloud_credentials(monkeypatch,provider_class,key):
    monkeypatch.setenv('APP_ENV','development')
    monkeypatch.setenv('CV_LLM_BASE_URL','http://host.docker.internal:11434/v1')
    monkeypatch.setenv('CV_LLM_ALLOW_HTTP','true')
    monkeypatch.setenv('CV_LLM_MODEL','elo-deepseek-r1:1.5b')
    monkeypatch.setenv('CV_LLM_API_KEY',key)
    provider=provider_class()
    assert provider.configured and provider._provider_headers()=={}
    assert provider._provider_options()=={}
    assert provider._request_timeout(60)==120 and provider._request_timeout(20)==60


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


@pytest.mark.parametrize('base_url,deepseek', [
    ('https://api.deepseek.com', True),
    ('https://api.deepseek.com/v1/', True),
    ('https://API.DEEPSEEK.COM', True),
    ('https://api.groq.com/openai/v1', False),
    ('https://api.openai.com/v1', False),
    ('https://api.deepseek.com.example/v1', False),
    ('https://proxy.example/api.deepseek.com', False),
    ('https://deepseek.com', False),
])
@pytest.mark.parametrize('operation', ['extract', 'route', 'interpret'])
def test_deepseek_thinking_option_is_host_scoped_for_all_cv_requests(monkeypatch, base_url, deepseek, operation):
    configure(monkeypatch)
    monkeypatch.setenv('CV_LLM_BASE_URL', base_url)
    # A model name alone must not send DeepSeek options to another provider.
    monkeypatch.setenv('CV_LLM_MODEL', 'deepseek-flash')
    outputs = {
        'extract': {'items': []},
        'route': {'reply': 'Please describe your contribution.', 'actions': []},
        'interpret': {'item_id': 'item-1', 'answer_revision': 1, 'resolution': 'unanswerable',
                      'claims': [], 'resolved_uncertainties': [], 'remaining_uncertainties': ['proficiency']},
    }
    captured = []
    def transport(request):
        captured.append(request)
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps(outputs[operation])}}]})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    if operation == 'extract':
        output, metadata = Extractor().extract([{'id': 'b1', 'location': 'Page 1', 'text': 'Synthetic CV'}])
    elif operation == 'route':
        output, metadata = ConversationRouter().route({'message': 'What should I explain?'})
        output = output.model_dump()
    else:
        output, metadata = Interpreter().interpret({'id': 'item-1'},
            {'id': 'question-1', 'uncertainty': 'proficiency', 'question': 'What did you do?'}, 'I do not know.', 1)
    assert output == outputs[operation]
    assert metadata['model'] == 'deepseek-flash'
    assert len(captured) == 1
    request = captured[0]
    payload = json.loads(request.content)
    assert request.method == 'POST'
    assert request.url.path.endswith('/chat/completions')
    assert request.headers['Authorization'] == 'Bearer synthetic-test-key'
    assert payload['model'] == 'deepseek-flash'
    assert payload['temperature'] == 0
    assert payload['response_format'] == {'type': 'json_object'}
    assert payload['max_tokens'] == (12000 if operation == 'extract' else 5000)
    if deepseek:
        assert payload['thinking'] == {'type': 'disabled'}
    else:
        assert 'thinking' not in payload
    assert 'reasoning_effort' not in payload
