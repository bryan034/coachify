"""Native Google errors must remain actionable without exposing provider content."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai.adapter import AIAdapter,AIError
from app.ai.config import GeminiSettings
from app.ai.contracts import AIInput
from app.ai.rejections import classify
from app.ai.routing import opportunity_models
from app.ai.opportunity_config import OpportunitySettings
from app.main import create_app


@pytest.mark.parametrize('wrapped',[False,True])
@pytest.mark.parametrize('status,error,expected,code,fields',[
    (400,{'code':400,'status':'INVALID_ARGUMENT','details':[{'reason':'API_KEY_INVALID'}]},'provider_auth','API_KEY_INVALID',[]),
    (404,{'code':404,'status':'NOT_FOUND'},'model_unavailable','NOT_FOUND',[]),
    (403,{'status':'PERMISSION_DENIED'},'provider_auth','PERMISSION_DENIED',[]),
    (400,{'status':'FAILED_PRECONDITION'},'provider_access','FAILED_PRECONDITION',[]),
    (403,{'status':'PERMISSION_DENIED','details':[{'reason':'SERVICE_DISABLED'}]},'provider_access','SERVICE_DISABLED',[]),
    (400,{'status':'INVALID_ARGUMENT','details':[{'fieldViolations':[{'field':'generation_config.response_schema.properties.role'}]}]},'provider_schema','INVALID_ARGUMENT',['response_format']),
    (400,{'status':'INVALID_ARGUMENT','details':[{'fieldViolations':[{'field':'generation_config.response_schema.properties.model'}]}]},'provider_schema','INVALID_ARGUMENT',['model','response_format']),
    (400,{'status':'INVALID_ARGUMENT','message':'Unsupported parameter: reasoning_effort. PRIVATE provider prose'},'provider_parameter','INVALID_ARGUMENT',['reasoning_effort']),
    (422,{'status':'INVALID_ARGUMENT','param':'max_tokens'},'provider_parameter','INVALID_ARGUMENT',['max_tokens']),
    (400,{'code':400,'status':'INVALID_ARGUMENT'},'provider_configuration','INVALID_ARGUMENT',[]),
])
def test_google_rejections_keep_only_fixed_machine_diagnostics(status,error,expected,code,fields,caplog,wrapped):
    async def run():
        calls=[]
        def handler(request):
            calls.append(request)
            envelope={'error':{**error,'private':'PRIVATE key and JD'}}
            return httpx.Response(status,json=[envelope] if wrapped else envelope)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(GeminiSettings(enabled=True,api_key='synthetic'),client)
            with pytest.raises(AIError) as raised:
                await adapter._complete({'model':'gemini-3.5-flash-lite','messages':[]},owner='synthetic')
        result=raised.value
        assert result.code==expected and not result.retryable and len(calls)==1
        assert result.provider_error=={'provider':'gemini','http_status':status,'code':code,'fields':fields}
        assert 'PRIVATE' not in json.dumps(result.provider_error) and 'PRIVATE' not in caplog.text
    asyncio.run(run())


@pytest.mark.parametrize('payload',[[],{'error':[]},{'error':{'code':[],'status':{},'details':[None,{'fieldViolations':'PRIVATE'}]}},'PRIVATE'])
def test_malformed_google_errors_do_not_crash_or_echo_payloads(payload):
    code,info=classify(json.dumps(payload).encode(),400,'gemini')
    assert code=='provider_configuration'
    assert info=={'http_status':400,'provider':'gemini','fields':[]}


def test_schema_rejection_never_silently_retries_without_the_schema():
    async def run():
        calls=[]
        def handler(request):
            calls.append(json.loads(request.content))
            return httpx.Response(400,json={'error':{'status':'INVALID_ARGUMENT','message':'Unknown name "response_format". PRIVATE generated text'}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(GeminiSettings(enabled=True,api_key='synthetic'),client)
            from app.ai.adapter import Operation
            with pytest.raises(AIError,match='provider_schema'):
                await adapter.generate(AIInput(stage='jd_scope',source_text='Analyst. SQL required.'),
                    Operation('synthetic','1','jd_scope'),current_revision=lambda:'1')
        assert len(calls)==1 and calls[0]['response_format']['type']=='json_schema'
    asyncio.run(run())


def test_api_exposes_status_and_known_fields_without_echoing_provider_prose(monkeypatch):
    monkeypatch.setenv('AI_ENABLED','false');monkeypatch.delenv('MONGODB_URI',raising=False)
    def profile(request):return httpx.Response(200,json={'id':'synthetic','email_verified':True} if request.url.path.endswith('/session') else {'onboarding_complete':True})
    def rejected(*args):
        raise AIError('provider_parameter',provider_error={'provider':'gemini','http_status':400,
            'code':'INVALID_ARGUMENT','fields':['reasoning_effort','PRIVATE SECRET'],'message':'PRIVATE provider content'})
    client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile))
    with TestClient(create_app(profile_client=client,processor=rejected)) as app:
        result=app.post('/api/v1/career/imports/url',headers={'Authorization':'Bearer synthetic'},json={'url':'https://example.test/job'})
    assert result.status_code==503
    assert result.json()['provider_error']=={'provider':'gemini','http_status':400,'code':'INVALID_ARGUMENT','fields':['reasoning_effort']}
    assert 'PRIVATE' not in result.text and 'message' not in result.json()['provider_error']


def test_explicit_model_override_is_shared_by_all_roles_and_legacy_settings_stay_ignored(monkeypatch):
    for name,value in {'AI_ENABLED':'true','GEMINI_API_KEY':' synthetic-gemini ',
        'GEMINI_REASONING_MODEL':'gemini-3.6-flash','GEMINI_MODEL':'legacy-lite',
        'AI_MODEL':'unused-model','AI_PROVIDER':'retired-provider'}.items():monkeypatch.setenv(name,value)
    settings=GeminiSettings.reasoning_from_env()
    assert settings.model=='gemini-3.6-flash' and settings.api_key.get_secret_value()=='synthetic-gemini'
    adapter=AIAdapter(settings,None)
    router=opportunity_models(adapter,None,settings,OpportunitySettings(),None)
    assert router.primary is router.context is adapter
    for stage in ('jd_scope','jd_extraction','opportunity_structure','opportunity_plan','discovery_extract'):
        request=AIInput(stage=stage,source_text='Analyst. SQL required.') if stage in ('jd_scope','jd_extraction') else AIInput(stage=stage,context='{}')
        assert adapter._payload(request)['model']=='gemini-3.6-flash'


def test_public_docker_example_contains_only_active_inputs_and_no_example_secrets():
    import re
    from pathlib import Path
    root=Path(__file__).resolve().parents[3]
    # This is the explicitly maintained public template, never a private .env.
    template=(root/'infrastructure/docker/.env.example').read_text()
    compose=(root/'infrastructure/docker/compose.yaml').read_text()
    pairs=dict(re.findall(r'^([A-Z][A-Z0-9_]*)=(.*)$',template,re.M))
    consumed=set(re.findall(r'\$\{([A-Z][A-Z0-9_]*)',compose))
    assert set(pairs)<=consumed
    from app.ai.config import REASONING_MODEL
    assert pairs['GEMINI_REASONING_MODEL']==REASONING_MODEL=='gemini-3.5-flash-lite'
    assert '${GEMINI_REASONING_MODEL:-'+REASONING_MODEL+'}' in compose
    for name,value in pairs.items():
        if name.endswith(('_PASSWORD','_API_KEY','_SECRET')):assert value==''


def test_deeply_nested_provider_errors_still_return_safe_diagnostics():
    raw=b'['*1200+b'0'+b']'*1200
    code,info=classify(raw,400,'gemini')
    assert code=='provider_configuration' and info=={'http_status':400,'provider':'gemini','fields':[]}
