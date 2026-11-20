"""Transient JD extraction checks: synthetic provider, no raw-source persistence."""
import asyncio
import json
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.ai.adapter import AIAdapter, Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.errors import AIError
from app.domain.extraction import validate_extraction
from app.schemas.jd import JDExtraction

SOURCE='Analyst: SQL required; Python is preferred.'
SKILL={'name':'SQL','category':'Technical','priority':'required','origin':'employer','evidence':'SQL required'}
OWNER='11111111-1111-4111-8111-111111111111'
AUTH={'Authorization':'Bearer synthetic-session','Idempotency-Key':str(uuid4())}
CONTEXT={'role':'Analyst','field':'Data','company':None,'location':'Singapore','seniority_level':'Entry level',
         'summary':'Analyse information for business decisions.','responsibilities':['Query and interpret data.'],
         'skills':[SKILL]}


def extracted(output,source_url=None):
    value=JDExtraction.model_validate(output)
    validate_extraction(value,source_url)
    return value


def profile(req):
    return httpx.Response(200,json={'id':OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})


@pytest.mark.parametrize('defect',['declaration','duplicate','guidance_priority'])
def test_invalid_extraction_classification_is_rejected(defect):
    skill={**SKILL}
    if defect=='declaration':skill.update(origin='user_declaration',evidence='Add SQL')
    if defect=='guidance_priority':skill.update(origin='generated_guidance',priority='required',evidence=None)
    with pytest.raises(AIError,match='invalid_output'):
        extracted({**CONTEXT,'skills':[skill,skill] if defect=='duplicate' else [skill]})


def test_semantic_extraction_accepts_supporting_summaries_and_optional_evidence():
    result=extracted({**CONTEXT,'skills':[{**SKILL,'evidence':'Ability to query relational data with SQL.'},
        {'name':'Collaboration','category':'Interpersonal','priority':'preferred','origin':'employer','evidence':None},
        {'name':'Data interpretation','category':'Analytical','priority':'suggested','origin':'generated_guidance',
         'context':'Inferred from the reporting responsibilities; verify the expected depth.','evidence':None}]})
    assert result.skills[0].evidence=='Ability to query relational data with SQL.'
    assert result.skills[2].origin=='generated_guidance'


def test_extraction_retains_job_fields_conditions_and_real_url():
    url='https://careers.example.test/analyst'
    result=extracted({**CONTEXT,'company':'Example Analytics','job_url':'https://invented.example.test/job',
        'non_skill_requirements':[{'requirement_id':'degree','category':'qualification','description':'A relevant degree is preferred.',
          'priority':'preferred','evidence':'A degree in a related subject would be helpful.','group_id':None,'group_operator':'all'}]},url)
    assert result.job_url==url and result.location=='Singapore' and result.seniority_level=='Entry level'
    assert result.summary==CONTEXT['summary'] and result.responsibilities==CONTEXT['responsibilities']
    assert result.non_skill_requirements[0].category=='qualification'


def test_no_explicit_skills_is_valid():
    assert extracted({'role':None,'field':None,'company':None,'skills':[]}).skills==[]


@pytest.mark.parametrize('evidence',['SQL is required','SQL — required for analysis','SQL is used to retrieve data.'])
def test_line_wrap_punctuation_and_paraphrase_do_not_block_extraction(evidence):
    assert extracted({**CONTEXT,'skills':[{**SKILL,'evidence':evidence}]}).skills[0].evidence==evidence


def test_oversized_job_description_is_rejected_before_ai():
    class Provider:
        def __init__(self):self.inputs=[]
        async def generate(self,data,operation,**kwargs):self.inputs.append(data)
    provider=Provider()
    with TestClient(create_app(profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)),ai=provider)) as client:
        assert client.post('/api/v1/career/workspace/jd',headers=AUTH,json={'text':'x'*20001}).status_code==422
    assert not provider.inputs


@pytest.mark.parametrize('code,detail',[('model_unavailable','not available'),('invalid_output','invalid structured response')])
def test_safe_actionable_ai_error_messages(code,detail):
    app=create_app(profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)))
    async def rejected():raise AIError(code)
    app.add_api_route('/api/v1/career/synthetic-ai-error',rejected,methods=['POST'])
    with TestClient(app) as client:
        response=client.post('/api/v1/career/synthetic-ai-error',json={'text':SOURCE})
    assert response.status_code==503
    assert response.json()['code']==code and detail in response.json()['detail']
    assert SOURCE not in response.text


def test_semantic_extraction_needs_no_quote_correction_with_real_adapter():
    calls=[]
    def upstream(req):
        calls.append(json.loads(req.content))
        output={**CONTEXT,'skills':[{**SKILL,'evidence':'Querying relational databases is essential.'}]}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
    async def invoke():
        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),client)
            return await ai.generate(AIInput(stage='jd_extraction',source_text=SOURCE),Operation(OWNER,'transient','jd_extraction'),
                current_revision=lambda:'transient',validate_output=lambda output:validate_extraction(output,None))
    result=asyncio.run(invoke())
    assert len(calls)==1 and result.data.job_url is None
    assert result.data.skills[0].evidence=='Querying relational databases is essential.'
    assert 'verbatim wording is NOT required' in calls[-1]['messages'][0]['content']
