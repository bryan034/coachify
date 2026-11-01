"""Regression coverage for planner truncation, safe diagnostics and advert scope."""
import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest
from app.ai.adapter import AIAdapter, AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.jd_scope import identify_job, CareerScopeError
from app.ai.recovery import recover_responses
from app.schemas.opportunity import CATEGORIES
from app.ai.opportunity_contracts import structure_input
from app.schemas.analysis import ResearchSource
from app.workflows.opportunity.engine import OpportunityEngine


@pytest.mark.parametrize('stage', ['opportunity_plan', 'opportunity_structure'])
@pytest.mark.parametrize('ceiling', [512, 8192])
def test_research_output_has_room_and_local_schema_is_explicit(stage, ceiling):
    settings=AISettings(provider='local',max_output_tokens=ceiling,response_mode='json_object')
    context=structure_input({},'internship_insights',[ResearchSource(source_id='synthetic',platform='other',url='https://example.test/intern',evidence='Example interns report mentorship.')]) if stage=='opportunity_structure' else {}
    payload=AIAdapter(settings,None)._payload(AIInput(stage=stage,context=json.dumps(context)))
    assert payload['max_tokens']==min(4096,ceiling)
    assert payload['response_format']['json_schema']['strict'] is True
    assert 'JSON schema:' in payload['messages'][0]['content']
    if stage=='opportunity_plan':
        assert all(category in payload['messages'][0]['content'] for category in CATEGORIES)
        assert 'query STRINGS' in payload['messages'][0]['content']


def test_model_deadline_defaults_to_sixty_seconds(monkeypatch):
    assert AISettings().timeout_seconds==60
    monkeypatch.setenv('CAREER_LLM_PROVIDER','local')
    monkeypatch.delenv('CAREER_LOCAL_TIMEOUT_SECONDS',raising=False)
    assert AISettings.from_env().timeout_seconds==60


@pytest.mark.parametrize('recheck_accepts', [True, False])
def test_advert_negative_classification_gets_one_grounded_recheck(recheck_accepts):
    source='ExampleCo is hiring an AI Product Intern. Responsibilities: evaluate agent workflows. Qualifications: Python. Please submit your resume.'
    async def run():
        calls=[]
        def handler(request):
            calls.append(json.loads(request.content))
            output={'document_type':'job_description' if len(calls)==2 and recheck_accepts else 'resume',
                    'evidence':['Responsibilities: evaluate agent workflows.']}
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
        settings=AISettings(enabled=True,provider='local')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            token=recover_responses.set(True)
            try:
                if recheck_accepts:
                    identity=await identify_job(AIAdapter(settings,client),source,'synthetic')
                    assert identity.is_job_description
                else:
                    with pytest.raises(CareerScopeError):await identify_job(AIAdapter(settings,client),source,'synthetic')
            finally:recover_responses.reset(token)
        assert len(calls)==2
        assert 'ambiguous_document_type' in calls[1]['messages'][0]['content']
    asyncio.run(run())


def test_research_repairs_log_safe_schema_fields_and_retain_truncation_reason(caplog):
    async def run():
        requests=[];updates=[]
        def handler(request):
            requests.append(json.loads(request.content))
            # Truncation followed by a complete but incorrectly typed category.
            content={category:['Example public interview query'] for category in CATEGORIES}
            content['company_intelligence']={'PRIVATE_EXTRA_FIELD':'PRIVATE_MODEL_TEXT'}
            return httpx.Response(200,json={'choices':[{'finish_reason':'length' if len(requests)==1 else 'stop',
                'message':{'content':json.dumps(content)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            engine=object.__new__(OpportunityEngine)
            engine.ai=AIAdapter(AISettings(enabled=True,api_key='synthetic'),client)
            engine.settings=SimpleNamespace(schema_repairs=1)
            engine.store=SimpleNamespace(update=lambda *a,**kw:updates.append(kw),rows=SimpleNamespace(update_one=lambda *a:None))
            with pytest.raises(AIError) as caught:
                await engine.generate({'_id':'synthetic','owner':'synthetic','goal_id':'synthetic','worker_token':'synthetic'},'opportunity_plan',{})
        assert caught.value.reason=='schema_validation'
        assert caught.value.violations==({'field':'company_intelligence','issue':'list_type'},)
        assert 'incomplete_json' in requests[1]['messages'][0]['content']
        assert 'company_intelligence' in caplog.text and 'list_type' in caplog.text
        assert 'PRIVATE' not in caplog.text
        assert len(updates)==2
    asyncio.run(run())
