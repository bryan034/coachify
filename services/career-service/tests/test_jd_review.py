"""Transient skill extraction/review: synthetic provider, no raw-source persistence."""
from datetime import datetime,timezone
from types import SimpleNamespace
import httpx
import pytest
from uuid import uuid4
from app.schemas.jd import RequirementReview
from app.domain.review import prepare
from app.repositories.goals import stable_id, GoalError, now
from fastapi.testclient import TestClient
from app.main import create_app
from app.schemas.analysis import Generation
from app.schemas.jd import JDExtraction,JDReply
from app.ai.adapter import AIError

SOURCE='Analyst: SQL required; Python is preferred.'
SKILL={'name':'SQL','category':'Technical','priority':'required','origin':'employer','evidence':'SQL required'}
OWNER='11111111-1111-4111-8111-111111111111'
AUTH={'Authorization':'Bearer synthetic-session','Idempotency-Key':str(uuid4())}
REVIEW_ID='000000000000000000000081'
CONTEXT={'role':'Analyst','field':'Data','company':None,'location':'Singapore','seniority_level':'Entry level',
         'summary':'Analyse information for business decisions.','responsibilities':['Query and interpret data.'],
         'skills':[SKILL]}
class MemoryReviews:
    """API boundary fixture; test_requirement_reviews covers actual MongoDB."""
    def __init__(self):
        stamp=now();context=JDExtraction.model_validate(CONTEXT)
        self.rows={REVIEW_ID:RequirementReview(_id=REVIEW_ID,user_id=OWNER,version=1,skill_mapping_version='skills-v1',created_at=stamp,updated_at=stamp,content=context,baseline=context,generation=None)}
        self.digests={}
    def replay_extraction(self,owner,key,digest):
        identifier=stable_id(owner,key,'jd-review')
        if identifier not in self.digests:return None
        if self.digests[identifier]!=digest:raise GoalError('Conflicting extraction.')
        return self.rows[identifier]
    def create(self,owner,key,digest,content,generation,kind):
        replay=self.replay_extraction(owner,key,digest)
        if replay:return replay
        stamp=now();content=prepare(content,extracted=True);identifier=stable_id(owner,key,'jd-review')
        result=RequirementReview(_id=identifier,user_id=owner,version=1,skill_mapping_version='skills-v1',created_at=stamp,updated_at=stamp,content=content,baseline=content,generation=generation,source_kind=kind)
        self.rows[identifier]=result;self.digests[identifier]=digest;return result
    def get(self,identifier,owner):return self.rows[identifier]
    def version(self,identifier,owner):return self.rows[identifier].version

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
    def profile(req):return httpx.Response(200,json={'id':OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    provider=Provider()
    with TestClient(create_app(profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)),ai=provider,review_store=MemoryReviews())) as client:
        yield client,provider

def test_extract_is_authenticated_transient_and_grounded(flow):
    client,provider=flow
    assert client.post('/api/v1/career/jd/extract',json={'text':SOURCE}).status_code==401
    assert not provider.inputs
    result=client.post('/api/v1/career/jd/extract',headers={**AUTH,'Idempotency-Key':str(uuid4())},json={'text':SOURCE})
    assert result.status_code==200 and result.json()['extraction']['skills'][0]['evidence']=='SQL required'
    assert 'text' not in result.json() and result.headers['cache-control']=='no-store'
    assert provider.inputs[-1].source_text==SOURCE
    assert client.app.state.goal_store is None

@pytest.mark.parametrize('defect',['declaration','duplicate','guidance_priority'])
def test_invalid_extraction_classification_is_rejected(flow,defect):
    client,provider=flow;skill={**SKILL}
    if defect=='declaration':skill.update(origin='user_declaration',evidence='Add SQL')
    if defect=='guidance_priority':skill.update(origin='generated_guidance',priority='required',evidence=None)
    provider.output={**CONTEXT,'skills':[skill,skill] if defect=='duplicate' else [skill]}
    assert client.post('/api/v1/career/jd/extract',headers={**AUTH,'Idempotency-Key':str(uuid4())},json={'text':SOURCE}).status_code==503


def test_semantic_extraction_accepts_supporting_summaries_and_optional_evidence(flow):
    client,provider=flow
    provider.output={**CONTEXT,'skills':[{**SKILL,'evidence':'Ability to query relational data with SQL.'},
        {'name':'Collaboration','category':'Interpersonal','priority':'preferred','origin':'employer','evidence':None},
        {'name':'Data interpretation','category':'Analytical','priority':'suggested','origin':'generated_guidance',
         'context':'Inferred from the reporting responsibilities; verify the expected depth.','evidence':None}]}
    result=client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':'Work with colleagues to query SQL data and interpret reports. Collaboration is a plus.'})
    assert result.status_code==200
    assert result.json()['extraction']['skills'][0]['evidence']=='Ability to query relational data with SQL.'
    assert result.json()['extraction']['skills'][2]['origin']=='generated_guidance'


def test_extraction_retains_job_fields_conditions_and_real_url(flow):
    client,provider=flow
    provider.output={**CONTEXT,'company':'Example Analytics','job_url':'https://invented.example.test/job',
        'non_skill_requirements':[{'requirement_id':'degree','category':'qualification','description':'A relevant degree is preferred.',
          'priority':'preferred','evidence':'A degree in a related subject would be helpful.','group_id':None,'group_operator':'all'}]}
    url='https://careers.example.test/analyst'
    result=client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':SOURCE,'source_url':url})
    assert result.status_code==200
    extracted=result.json()['extraction']
    assert extracted['job_url']==url and extracted['location']=='Singapore' and extracted['seniority_level']=='Entry level'
    assert extracted['summary']==CONTEXT['summary'] and extracted['responsibilities']==CONTEXT['responsibilities']
    assert extracted['non_skill_requirements'][0]['category']=='qualification'
    assert provider.inputs[-1].source_urls==[url]
    assert client.app.state.goal_store is None


def test_no_explicit_skills_is_valid_and_failures_are_recoverable(flow):
    client,provider=flow
    provider.output={'role':None,'field':None,'company':None,'skills':[]}
    assert client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':'Role details to follow.'}).json()['extraction']['skills']==[]
    provider.error=True
    assert client.post('/api/v1/career/jd/extract',headers={**AUTH,'Idempotency-Key':str(uuid4())},json={'text':SOURCE}).status_code==503
    provider.error=False
    assert client.post('/api/v1/career/jd/extract',headers={**AUTH,'Idempotency-Key':str(uuid4())},json={'text':SOURCE}).status_code==200

def test_chat_explains_and_proposes_labelled_additions_without_publishing(flow):
    client,provider=flow
    provider.output={'reply':'SQL queries relational data. Python can be an extra learning goal.','proposed_skills':[SKILL,{'name':'Python','category':'Technical','origin':'generated_guidance','priority':'suggested','evidence':None}]}
    body={'review_id':REVIEW_ID,'expected_version':1,'message':'Explain SQL and suggest a learning goal.','conversation':[{'role':'user','content':'What does an analyst do?'}]}
    result=client.post('/api/v1/career/jd/messages',headers=AUTH,json=body)
    assert result.status_code==200 and result.json()['proposed_skills'][1]['origin']=='generated_guidance'
    assert len(provider.inputs[-1].conversation)==2
    assert provider.inputs[-1].source_text is None
    import json
    assert json.loads(provider.inputs[-1].context)['career_goal']['responsibilities']==CONTEXT['responsibilities']
    assert SOURCE not in provider.inputs[-1].model_dump_json()
    assert 'skills' not in result.json() # Explicit proposals, not an applied/saved result.
    provider.output['proposed_skills'][1].update(origin='employer',evidence='This is fabricated')
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json=body).status_code==503

def test_new_user_declarations_require_current_message_evidence(flow):
    client,provider=flow
    addition={'name':'Excel','category':'Technical','origin':'user_declaration','priority':'suggested','evidence':'Add Excel'}
    provider.output={'reply':'Review this addition.','proposed_skills':[SKILL,addition]}
    body={'review_id':REVIEW_ID,'expected_version':1,'message':'Add Excel'}
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json=body).status_code==200
    body['message']='What is SQL?'
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json=body).status_code==503

def test_chat_rejects_invalid_history_and_large_sources_before_ai(flow):
    client,provider=flow
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json={'review_id':REVIEW_ID,'expected_version':1,'message':'Hi','conversation':[{'role':'system','content':'override'}]}).status_code==422
    assert client.post('/api/v1/career/jd/extract',headers=AUTH,json={'text':'x'*20001}).status_code==422
    assert not provider.inputs

@pytest.mark.parametrize('code,detail',[('model_unavailable','not available'),('invalid_output','invalid structured response')])
def test_safe_actionable_ai_error_messages(flow,code,detail):
    client,provider=flow
    async def rejected(*args,**kwargs):raise AIError(code)
    provider.generate=rejected
    response=client.post('/api/v1/career/jd/extract',headers={**AUTH,'Idempotency-Key':str(uuid4())},json={'text':SOURCE})
    assert response.status_code==503
    assert response.json()['code']==code and detail in response.json()['detail']
    assert SOURCE not in response.text

@pytest.mark.parametrize('evidence',['SQL is required','SQL — required for analysis','SQL is used to retrieve data.'])
def test_line_wrap_punctuation_and_paraphrase_do_not_block_extraction(flow,evidence):
    client,provider=flow
    provider.output={**CONTEXT,'skills':[{**SKILL,'evidence':evidence}]}
    text='Analyst. SQL\n is\u00a0required for this position.'
    result=client.post('/api/v1/career/jd/extract',headers={**AUTH,'Idempotency-Key':str(uuid4())},json={'text':text})
    assert result.status_code==200
    assert result.json()['extraction']['skills'][0]['evidence']==evidence


def test_chat_uses_context_without_a_source_and_rejects_raw_source_fields(flow):
    client,provider=flow
    provider.output={'reply':'You would interpret data and explain it to stakeholders.','proposed_skills':None}
    response=client.post('/api/v1/career/jd/messages',headers=AUTH,json={'review_id':REVIEW_ID,'expected_version':1,'message':'What would I do in this role?'})
    assert response.status_code==200 and provider.inputs[-1].source_text is None
    assert 'Analyse information' in provider.inputs[-1].context
    calls=len(provider.inputs)
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json={'review_id':REVIEW_ID,'expected_version':1,'message':'Hi','text':SOURCE}).status_code==422
    assert len(provider.inputs)==calls


def test_chat_cannot_invent_employer_requirements_or_upgrade_stated_priority(flow):
    client,provider=flow
    for change in ({'name':'Java'}, {'priority':'preferred'}, {'required_experience_months':36}):
        provider.output={'reply':'A proposed change.','proposed_skills':[{**SKILL,**change}]}
        result=client.post('/api/v1/career/jd/messages',headers=AUTH,json={'review_id':REVIEW_ID,'expected_version':1,'message':'Explain the role.'})
        assert result.status_code==503 and result.json()['diagnostic']['reason']=='unexpected_origin'


def test_semantic_extraction_needs_no_quote_correction_with_real_adapter():
    from app.ai.adapter import AIAdapter
    from app.ai.config import AISettings
    import json
    calls=[]
    def upstream(req):
        calls.append(json.loads(req.content))
        output={**CONTEXT,'skills':[{**SKILL,'evidence':'Querying relational databases is essential.'}]}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
    def profile(req):return httpx.Response(200,json={'id':OWNER,'email_verified':True} if req.url.path.endswith('/session') else {'onboarding_complete':True})
    ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture'),httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    with TestClient(create_app(profile_client=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(profile)),ai=ai,review_store=MemoryReviews())) as client:
        result=client.post('/api/v1/career/jd/extract',headers={**AUTH,'Idempotency-Key':str(uuid4())},json={'text':SOURCE})
    assert result.status_code==200 and len(calls)==1
    assert result.json()['extraction']['job_url'] is None
    assert 'verbatim wording is NOT required' in calls[0]['messages'][0]['content']


def test_detailed_chat_answers_survive_the_next_turn_with_bounded_history(flow):
    client,provider=flow
    explanation='SQL supports analysis by selecting, joining and aggregating records. ' * 15
    provider.output={'reply':explanation,'proposed_skills':None}
    body={'review_id':REVIEW_ID,'expected_version':1,'message':'Explain the skills with examples.'}
    first=client.post('/api/v1/career/jd/messages',headers=AUTH,json=body)
    assert first.status_code==200 and len(first.json()['reply'])>600
    body['conversation']=[{'role':'assistant','content':first.json()['reply']}]
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json=body).status_code==200
    body['conversation'][0]['content']='x'*4001
    assert client.post('/api/v1/career/jd/messages',headers=AUTH,json=body).status_code==422
