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


@pytest.mark.parametrize('provider_class',[Extractor,ConversationRouter,Interpreter])
@pytest.mark.parametrize('base,override,expected',[
    ('https://openrouter.ai/api/v1','','synthetic-shared'),
    ('https://openrouter.ai/api/v1','synthetic-specific','synthetic-specific'),
    ('https://api.openai.com/v1','',''),
])
def test_cv_adapters_resolve_shared_key_only_for_openrouter(monkeypatch,provider_class,base,override,expected):
    monkeypatch.setenv('CV_LLM_BASE_URL',base)
    monkeypatch.setenv('CV_LLM_MODEL','@preset/synthetic')
    monkeypatch.setenv('CV_LLM_API_KEY',override)
    monkeypatch.setenv('OPENROUTER_API_KEY','synthetic-shared')
    provider=provider_class()
    assert provider.configured is bool(expected)
    assert provider.api_key==expected
    assert provider.model=='@preset/synthetic'
    if not expected:
        return
    responses={Extractor:{'items':[]},ConversationRouter:{'reply':'Please explain.','actions':[]},
        Interpreter:{'item_id':'item-1','answer_revision':1,'resolution':'unanswerable',
                     'claims':[],'resolved_uncertainties':[],'remaining_uncertainties':['proficiency']}}
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop',
            'message':{'content':json.dumps(responses[provider_class])}}]})
    original=httpx.Client
    for module in ('extractor','conversation','interpretation'):
        monkeypatch.setattr('app.clients.'+module+'.Client',lambda **kwargs:original(transport=httpx.MockTransport(handler),**kwargs))
    if provider_class is Extractor:
        provider.extract([])
    elif provider_class is ConversationRouter:
        provider.route({'message':'What should I explain?'})
    else:
        provider.interpret({'id':'item-1'},{'id':'question-1','uncertainty':'proficiency','question':'What did you do?'},'I do not know.',1)
    assert len(calls)==1
    assert calls[0].headers['authorization']=='Bearer '+expected
    assert json.loads(calls[0].content)['model']=='@preset/synthetic'


@pytest.mark.parametrize('finish,content,expected', [('stop', '{"items":[]}', True), ('length', '{"items":[]}', False), ('stop', 'not json', False)])
def test_compatible_provider_contract_and_incomplete_output(monkeypatch, finish, content, expected):
    configure(monkeypatch)
    requests = []
    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': finish, 'message': {'content': content}}]})
    original = httpx.Client
    for module in ('extractor', 'conversation', 'interpretation'):
        monkeypatch.setattr('app.clients.' + module + '.Client', lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    extractor = Extractor()
    if expected:
        output, metadata = extractor.extract([{'id': 'b1', 'location': 'Page 1', 'text': 'Synthetic CV'}])
        assert output == {'items': []}
        assert metadata['model'] == 'synthetic-test-model'
        assert requests[0]['response_format']['type'] == 'json_schema'
        assert requests[0]['response_format']['json_schema']['strict'] is True
        assert json.loads(requests[0]['messages'][-1]['content'])['source_blocks'][0]['id'] == 'b1'
    else:
        with pytest.raises(ValueError): extractor.extract([])


@pytest.mark.parametrize('base_url,deepseek', [
    ('https://api.deepseek.com', True),
    ('https://api.deepseek.com/v1/', True),
    ('https://API.DEEPSEEK.COM', True),
    ('https://api.groq.com/openai/v1', False),
    ('https://generativelanguage.googleapis.com/v1beta/openai', False),
    ('https://generativelanguage.googleapis.com.example/v1', False),
    ('https://api.openai.com/v1', False),
    ('https://api.deepseek.com.example/v1', False),
    ('https://proxy.example/api.deepseek.com', False),
    ('https://deepseek.com', False),
])
@pytest.mark.parametrize('operation', ['extract', 'route', 'interpret'])
def test_vendor_options_are_host_scoped_for_all_cv_requests(monkeypatch, base_url, deepseek, operation):
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
    for module in ('extractor', 'conversation', 'interpretation'):
        monkeypatch.setattr('app.clients.' + module + '.Client', lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
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
    if operation == 'extract':
        assert payload['response_format']['type'] == 'json_schema'
        assert payload['response_format']['json_schema']['strict'] is True
    else:
        assert payload['response_format'] == {'type': 'json_object'}
    assert payload['max_tokens'] == (12000 if operation == 'extract' else 5000)
    if deepseek:
        assert payload['thinking'] == {'type': 'disabled'}
    else:
        assert 'thinking' not in payload
    if httpx.URL(base_url).host == 'generativelanguage.googleapis.com':
        assert payload['reasoning_effort'] == 'minimal'
    else:
        assert 'reasoning_effort' not in payload


@pytest.mark.parametrize('base_url,gemini', [
    ('https://generativelanguage.googleapis.com/v1beta/openai', True),
    ('https://GENERATIVELANGUAGE.GOOGLEAPIS.COM/v1beta/openai', True),
    ('https://api.openai.com/v1', False),
    ('https://generativelanguage.googleapis.com.example/v1', False),
])
@pytest.mark.parametrize('repair', [False, True])
def test_gemini_uses_simple_decoding_schema_with_full_prompt_limits(monkeypatch, base_url, gemini, repair):
    configure(monkeypatch)
    monkeypatch.setenv('CV_LLM_BASE_URL', base_url)
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"items":[]}'}}]})
    original = httpx.Client
    monkeypatch.setattr('app.clients.extractor.Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    extractor = Extractor()
    if repair:
        extractor.repair([], {'items': []}, [{'field': 'items', 'issue': 'too_short'}])
    else:
        extractor.extract([])
    request = captured[0]
    grammar = request['response_format']['json_schema']
    assert grammar['strict'] is True
    schema = grammar['schema']
    assert ('maxItems' not in schema['properties']['items']) is gemini
    item = schema['properties']['items']['items']
    assert ('maxItems' not in item['properties']['evidence']) is gemini
    assert ('maximum' not in item['properties']['experience_months']['anyOf'][0]) is gemini
    assert item['additionalProperties'] is False
    assert set(item['required']) == set(item['properties'])
    assert item['properties']['kind']['enum'] == ['education', 'experience', 'project', 'skill']
    assert {'type': 'null'} in item['properties']['end_date']['anyOf']
    assert 'other_information' in schema['required']
    assert '"maxItems": 160' in request['messages'][0]['content']
    assert '"maxLength": 500' in request['messages'][0]['content']
