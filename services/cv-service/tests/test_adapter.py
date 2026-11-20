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


@pytest.mark.parametrize('base_url', [
    'https://api.groq.com/openai/v1',
    'https://openrouter.ai/api/v1',
    'https://api.openai.com/v1',
])
@pytest.mark.parametrize('operation', ['extract', 'route', 'interpret'])
def test_cv_requests_send_no_vendor_extensions_for_any_host(monkeypatch, base_url, operation):
    configure(monkeypatch)
    monkeypatch.setenv('CV_LLM_BASE_URL', base_url)
    monkeypatch.setenv('CV_LLM_MODEL', 'synthetic-cloud-model')
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
    assert metadata['model'] == 'synthetic-cloud-model'
    assert len(captured) == 1
    request = captured[0]
    payload = json.loads(request.content)
    assert request.method == 'POST'
    assert request.url.path.endswith('/chat/completions')
    assert request.headers['Authorization'] == 'Bearer synthetic-test-key'
    assert payload['model'] == 'synthetic-cloud-model'
    assert payload['temperature'] == 0
    if operation == 'extract':
        assert payload['response_format']['type'] == 'json_schema'
        assert payload['response_format']['json_schema']['strict'] is True
    else:
        assert payload['response_format'] == {'type': 'json_object'}
    assert payload['max_tokens'] == (12000 if operation == 'extract' else 5000)
    assert 'thinking' not in payload
    assert 'reasoning_effort' not in payload


@pytest.mark.parametrize('base_url', [
    'https://openrouter.ai/api/v1',
    'https://api.openai.com/v1',
])
@pytest.mark.parametrize('repair', [False, True])
def test_decoding_schema_keeps_full_bounds_for_every_host(monkeypatch, base_url, repair):
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
    assert 'maxItems' in schema['properties']['items']
    item = schema['properties']['items']['items']
    assert 'maxItems' in item['properties']['evidence']
    assert 'maximum' in item['properties']['experience_months']['anyOf'][0]
    assert item['additionalProperties'] is False
    assert set(item['required']) == set(item['properties'])
    assert item['properties']['kind']['enum'] == ['education', 'experience', 'project', 'skill']
    assert {'type': 'null'} in item['properties']['end_date']['anyOf']
    assert 'other_information' in schema['required']
    assert '"maxItems": 160' not in request['messages'][0]['content']
    assert '"maxLength": 500' not in request['messages'][0]['content']


def test_json_object_compatibility_keeps_schema_in_prompt(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv('CV_LLM_RESPONSE_MODE', 'json_object')
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': '{"items":[]}'}}]})
    original = httpx.Client
    monkeypatch.setattr('app.clients.extractor.Client', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    Extractor().extract([])
    assert requests[0]['response_format'] == {'type': 'json_object'}
    assert '"maxItems": 160' in requests[0]['messages'][0]['content']


BLOCKS = [{'id': 'b1', 'location': 'Page 1', 'text': 'Built weekly sales dashboards in Tableau.'}]
JSON_OBJECT_CALLS = {
    'route': lambda: ConversationRouter().route({'message': 'What should I explain?'}),
    'skills_intake': lambda: ConversationRouter().route({'task': 'skills_intake', 'message': 'I use Tableau.'}),
    'skills_question': lambda: ConversationRouter().route({'task': 'skills_question', 'message': 'Tableau'}),
    'cv_review_question': lambda: ConversationRouter().route({'task': 'cv_review_question', 'message': 'Dashboards'}),
    'cv_interview_interpret': lambda: ConversationRouter().route({'task': 'cv_interview_interpret', 'message': 'I built them.'}),
    'cv_interview_plan': lambda: ConversationRouter().route({'task': 'cv_interview_plan'}),
    'cv_skill_levels': lambda: ConversationRouter().rate_skill_levels({'task': 'cv_skill_levels', 'sources': []}),
    'interpret': lambda: Interpreter().interpret({'id': 'item-1'},
        {'id': 'question-1', 'uncertainty': 'proficiency', 'question': 'What did you do?'}, 'I built them.', 1),
    'extract': lambda: Extractor().extract(BLOCKS),
    'repair': lambda: Extractor().repair(BLOCKS, {'items': []}, ['Cite a source block.']),
    'verify_evidence': lambda: Extractor().verify_evidence(BLOCKS, [{'block_id': 'b1', 'excerpt': 'Built dashboards'}]),
}


@pytest.mark.parametrize('call', JSON_OBJECT_CALLS)
def test_json_object_requests_name_json_in_the_system_prompt(monkeypatch, call):
    """OpenAI rejects json_object requests whose messages never mention JSON; OpenRouter reports it as 400 or 502."""
    configure(monkeypatch)
    monkeypatch.setenv('CV_LLM_RESPONSE_MODE', 'json_object')
    captured = []
    def transport(request):
        captured.append(json.loads(request.content))
        return httpx.Response(503, json={'error': {'message': 'synthetic outage'}})
    original = httpx.Client
    for module in ('extractor', 'conversation', 'interpretation'):
        monkeypatch.setattr('app.clients.' + module + '.Client', lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    with pytest.raises(ValueError):
        JSON_OBJECT_CALLS[call]()
    assert len(captured) == 1
    assert captured[0]['response_format'] == {'type': 'json_object'}
    assert 'json' in captured[0]['messages'][0]['content'].lower()


STRICT_KEYWORDS = frozenset({'$ref', 'additionalProperties', 'anyOf', 'description', 'enum', 'items', 'maxItems',
    'maxLength', 'maximum', 'minItems', 'minLength', 'minimum', 'pattern', 'required', 'type'})


def strict_violations(node, path='$'):
    """Paths that break OpenAI strict structured output rules or use an unverified keyword."""
    found = []
    if isinstance(node, dict):
        if node.get('type') == 'object' or 'properties' in node:
            if node.get('additionalProperties') is not False:
                found.append(path + ': additionalProperties must be false')
            if sorted(node.get('required', [])) != sorted(node.get('properties', {})):
                found.append(path + ': every property must be required')
        for key, value in node.items():
            if key in ('properties', '$defs'):
                for name, child in value.items():
                    found += strict_violations(child, f'{path}.{key}.{name}')
            elif key not in STRICT_KEYWORDS:
                found.append(f'{path}: unverified keyword {key}')
            else:
                found += strict_violations(value, f'{path}.{key}')
    elif isinstance(node, list):
        for index, child in enumerate(node):
            found += strict_violations(child, f'{path}[{index}]')
    return found


@pytest.mark.parametrize('call', ['extract', 'repair', 'verify_evidence'])
def test_strict_schemas_follow_openai_structured_output_rules(monkeypatch, call):
    configure(monkeypatch)
    monkeypatch.setenv('CV_LLM_RESPONSE_MODE', 'json_schema')
    captured = []
    def transport(request):
        captured.append(json.loads(request.content))
        return httpx.Response(503, json={'error': {'message': 'synthetic outage'}})
    original = httpx.Client
    monkeypatch.setattr('app.clients.extractor.Client', lambda **kwargs: original(transport=httpx.MockTransport(transport), **kwargs))
    with pytest.raises(ValueError):
        JSON_OBJECT_CALLS[call]()
    response_format = captured[0]['response_format']
    assert response_format['type'] == 'json_schema' and response_format['json_schema']['strict'] is True
    assert response_format['json_schema']['schema'].get('type') == 'object'
    assert strict_violations(response_format['json_schema']['schema']) == []
