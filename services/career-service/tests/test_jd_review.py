"""Transient skill extraction/review: synthetic provider, no raw-source persistence."""
from datetime import datetime,timezone
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.schemas.analysis import Generation
from app.schemas.jd import JDExtraction,JDReply
from app.ai.adapter import AIError

SOURCE='Analyst: SQL required; Python is preferred.'
SKILL={'name':'SQL','category':'Technical','priority':'required','origin':'employer','evidence':'SQL required'}
AUTH={'Authorization':'Bearer synthetic-session'}
class Provider:
    settings=SimpleNamespace(enabled=True)
    def __init__(self):self.inputs=[];self.output=None;self.error=False
    async def generate(self,data,operation,**kwargs):
        self.inputs.append(data)
        if self.error:raise AIError('unavailable',True)
        output=self.output or {'role':'Analyst','field':'Data','company':None,'skills':[SKILL]}
        model=JDExtraction if data.stage=='jd_extraction' else JDReply
        return SimpleNamespace(data=model.model_validate(output),generation=Generation(provider='fixture',model='fixture',prompt_version='test',generated_at=datetime.now(timezone.utc)))
@pytest.fixture
def flow():
    def profile(req):return httpx.Response(200,json={'id':'fixture-account','email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    provider=Provider()
    with TestClient(create_app(profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)),ai=provider)) as client:
        yield client,provider

def test_extract_is_authenticated_transient_and_grounded(flow):
    client,provider=flow
    assert client.post('/api/v1/career/jd/extract',json={'text':SOURCE}).status_code==401
    assert not provider.inputs
    result=client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':SOURCE})
    assert result.status_code==200 and result.json()['extraction']['skills'][0]['evidence']=='SQL required'
    assert 'text' not in result.json() and result.headers['cache-control']=='no-store'
    assert provider.inputs[-1].source_text==SOURCE
    assert client.app.state.goal_store is None

@pytest.mark.parametrize('defect',['quote','guidance','duplicate'])
def test_unsupported_extraction_is_rejected(flow,defect):
    client,provider=flow;skill={**SKILL}
    if defect=='quote':skill['evidence']='Invented expertise'
    if defect=='guidance':skill.update(origin='generated_guidance',priority='suggested',evidence=None)
    provider.output={'role':'Analyst','field':'Data','company':None,'skills':[skill,skill] if defect=='duplicate' else [skill]}
    assert client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':SOURCE}).status_code==503

def test_no_explicit_skills_is_valid_and_failures_are_recoverable(flow):
    client,provider=flow
    provider.output={'role':None,'field':None,'company':None,'skills':[]}
    assert client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':'Role details to follow.'}).json()['extraction']['skills']==[]
    provider.error=True
    assert client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':SOURCE}).status_code==503
    provider.error=False
    assert client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':SOURCE}).status_code==200

def test_chat_explains_and_proposes_labelled_additions_without_publishing(flow):
    client,provider=flow
    provider.output={'reply':'SQL queries relational data. Python can be an extra learning goal.','proposed_skills':[SKILL,{'name':'Python','category':'Technical','origin':'generated_guidance','priority':'suggested','evidence':None}]}
    body={'text':SOURCE,'message':'Explain SQL and suggest a learning goal.','skills':[SKILL],'conversation':[{'role':'user','content':'What does an analyst do?'}]}
    result=client.post('/api/v1/career/jd/messages',headers=AUTH,json=body)
    assert result.status_code==200 and result.json()['proposed_skills'][1]['origin']=='generated_guidance'
    assert len(provider.inputs[-1].conversation)==2
    assert 'skills' not in result.json() # Explicit proposals, not an applied/saved result.
    provider.output['proposed_skills'][1].update(origin='employer',evidence='This is fabricated')
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json=body).status_code==503

def test_new_user_declarations_require_current_message_evidence(flow):
    client,provider=flow
    addition={'name':'Excel','category':'Technical','origin':'user_declaration','priority':'suggested','evidence':'Add Excel'}
    provider.output={'reply':'Review this addition.','proposed_skills':[SKILL,addition]}
    body={'text':SOURCE,'message':'Add Excel','skills':[SKILL]}
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json=body).status_code==200
    body['message']='What is SQL?'
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json=body).status_code==503

def test_chat_rejects_invalid_history_and_large_sources_before_ai(flow):
    client,provider=flow
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json={'text':SOURCE,'message':'Hi','skills':[],'conversation':[{'role':'system','content':'override'}]}).status_code==422
    assert client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':'x'*20001}).status_code==422
    assert not provider.inputs

@pytest.mark.parametrize('code,detail',[('model_unavailable','not available'),('invalid_output','invalid structured response')])
def test_safe_actionable_ai_error_messages(flow,code,detail):
    client,provider=flow
    async def rejected(*args,**kwargs):raise AIError(code)
    provider.generate=rejected
    response=client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':SOURCE})
    assert response.status_code==503
    assert response.json()['code']==code and detail in response.json()['detail']
    assert SOURCE not in response.text

def test_whitespace_only_quote_difference_restores_the_exact_source_span(flow):
    client,provider=flow
    provider.output={'role':'Analyst','field':'Data','company':None,'skills':[{**SKILL,'evidence':'SQL is required'}]}
    text='Analyst. SQL\n is\u00a0required for this position.'
    result=client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':text})
    assert result.status_code==200
    assert result.json()['extraction']['skills'][0]['evidence']=='SQL\n is\u00a0required'
    provider.output['skills'][0]['evidence']='SQL is optional'
    rejected=client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':text})
    assert rejected.status_code==503 and rejected.json()['diagnostic']['reason']=='source_quote'
    assert text not in rejected.text

def test_grounding_failure_gets_a_bounded_model_correction_before_success():
    from app.ai.adapter import AIAdapter
    from app.ai.config import AISettings
    calls=[]
    def upstream(req):
        calls.append(req)
        skill={**SKILL,'evidence':'Invented private quote'} if len(calls)==1 else SKILL
        import json
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'role':'Analyst','field':'Data','company':None,'skills':[skill]})}}]})
    def profile(req):return httpx.Response(200,json={'id':'fixture-account','email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    with TestClient(create_app(profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)),ai=ai)) as client:
        result=client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':SOURCE})
    assert result.status_code==200 and len(calls)==2
    assert 'source_quote' in calls[1].content.decode() and 'Invented private quote' not in calls[1].content.decode()
