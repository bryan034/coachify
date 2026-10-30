"""Gemini-only production configuration and Brave-to-domain JSON conversion."""
import asyncio
import json

import httpx
import pytest

from app.ai.adapter import AIAdapter,AIError,MODEL_OUTPUTS,Operation
from app.ai.config import GeminiSettings
from app.ai.contracts import AIInput
from app.ai.opportunity_config import OpportunitySettings
from app.ai.opportunity_contracts import StructuredFindings,FIELD_GUIDANCE
from app.ai.routing import ModelRouter
from app.clients.search_sources import SourceAPIs
from app.repositories.goals import now
from app.schemas.analysis import ResearchContext,ResearchSource
from app.schemas.opportunity import CATEGORIES,FIELDS,CategoryResult,OpportunityReport
from app.workflows.opportunity.domain import supported_claims
from app.workflows.opportunity.engine import select_evidence


def test_runtime_ignores_legacy_credentials_models_and_chat_switch(monkeypatch):
    monkeypatch.delenv('CAREER_LLM_MODEL',raising=False)
    for name,value in {'AI_ENABLED':'true','AI_PROVIDER':'retired-provider','AI_MODEL':'legacy-model',
        'AI_BASE_URL':'https://legacy.test/v1','AI_API_KEY':'synthetic-legacy',
        'GEMINI_ENABLED':'false','GEMINI_MODEL':'legacy-context-model',
        'OPPORTUNITY_GEMINI_MODEL':'legacy-coordinator','GEMINI_API_KEY':'synthetic-gemini'}.items():
        monkeypatch.setenv(name,value)
    settings=GeminiSettings.reasoning_from_env()
    assert settings.enabled and settings.provider=='gemini' and settings.model=='gemini-3.5-flash-lite'
    assert settings.api_key.get_secret_value()=='synthetic-gemini'
    assert settings.base_url=='https://generativelanguage.googleapis.com/v1beta/openai'
    assert settings.response_mode=='json_schema' and settings.token_parameter=='max_tokens'
    assert OpportunitySettings.from_env().gemini_model=='gemini-3.5-flash-lite'
    monkeypatch.setenv('AI_ENABLED','false')
    assert not GeminiSettings.reasoning_from_env().enabled
    monkeypatch.setenv('AI_ENABLED','true');monkeypatch.delenv('GEMINI_API_KEY')
    with pytest.raises(ValueError) as error:GeminiSettings.reasoning_from_env()
    assert 'synthetic-legacy' not in str(error.value)


@pytest.mark.parametrize('stage',MODEL_OUTPUTS)
def test_every_stage_routes_to_the_same_gemini_adapter(stage):
    async def run():
        class RecordingAdapter:
            settings=GeminiSettings(enabled=True,api_key='synthetic')
            async def generate(self,request,operation,**kwargs):
                assert request.stage==stage and operation.stage==stage
                return self.settings.model
        adapter=RecordingAdapter()
        # Routing does not mutate requests; stage-specific contracts are tested by
        # the real adapter flows and by the research conversion below.
        from types import SimpleNamespace
        assert await ModelRouter(adapter,adapter).generate(SimpleNamespace(stage=stage),Operation('synthetic','1',stage))=='gemini-3.5-flash-lite'
    asyncio.run(run())


@pytest.mark.parametrize('category',CATEGORIES)
def test_brave_snippets_convert_to_every_existing_research_json_field(category):
    async def run():
        fields=FIELDS[category]
        assert set(FIELD_GUIDANCE[category])==set(fields)
        # Each field has distinguishable synthetic evidence, never real user data.
        passages={field:f'Example interns report {field.replace("_"," ")} detail {i}.' for i,field in enumerate(fields)}
        if 'compensation' in passages:passages['compensation']='Example interns receive SGD 1500 per month.'
        for field in ('historical_cohort','offer_acceptance'):
            if field in passages:passages[field]='Example interns in the 2025 cohort reported '+field.replace('_',' ')+' detail.'
        if 'conversion_rate' in passages:passages['conversion_rate']='Example interns in the 2025 cohort had a 50% full-time conversion rate.'
        if 'conversion_salary' in passages:passages['conversion_salary']='Example full-time conversion salary was SGD 5000 monthly base in 2025.'
        calls=[]
        def handler(request):
            calls.append(request)
            if request.url.host=='api.search.brave.com':
                assert request.url.path=='/res/v1/llm/context'
                return httpx.Response(200,json={'grounding':{'generic':[
                    {'url':'https://example.test/report','snippets':list(passages.values())}]},
                    'sources':{'https://example.test/report':{'title':'Example internship report'}}})
            assert request.url.host=='generativelanguage.googleapis.com'
            assert request.headers['authorization']=='Bearer synthetic-gemini'
            payload=json.loads(request.content)
            assert payload['model']=='gemini-3.5-flash-lite' and payload['response_format']['type']=='json_schema'
            schema=payload['response_format']['json_schema']
            assert schema['name']=='opportunity_structure'
            supplied=json.loads(payload['messages'][1]['content'])
            assert supplied['field_guidance']==FIELD_GUIDANCE[category]
            excerpt=supplied['sources'][0]['excerpt']
            assert all(text in excerpt for text in passages.values())
            result={'findings':[{'field':field,'value':text,'refs':[0],'quotes':[text],
                'confidence':'medium','evidence_type':'candidate_reported','scope':'exact'} for field,text in passages.items()]}
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sources=await SourceAPIs(client,brave_key='synthetic-brave').collect_opportunity_query(
                ResearchContext(role='Analyst Intern',field='Data',company='Example'),f'Example internship {category}')
            selected=select_evidence(sources,OpportunitySettings().evidence_tokens)
            context={'category':category,'allowed_fields':fields,'field_guidance':FIELD_GUIDANCE[category],
                'sources':[{'ref':i,'title':s.title,'url':s.url,'excerpt':s.evidence} for i,s in enumerate(selected)]}
            public={'company':'Example','employment_type':'internship'}
            adapter=AIAdapter(GeminiSettings(enabled=True,api_key='synthetic-gemini',max_output_tokens=4096),client)
            result=await adapter.generate(AIInput(stage='opportunity_structure',context=json.dumps(context)),
                Operation('synthetic','1','opportunity_structure'),current_revision=lambda:'1',
                validate_output=lambda output:supported_claims(output,category,selected,public))
        findings,rejected=supported_claims(result.data,category,selected,public)
        assert not rejected and {f.field for f in findings}==set(fields)
        categories={key:CategoryResult(status='completed',findings=findings if key==category else [],
            missing_fields=[] if key==category else list(FIELDS[key])) for key in CATEGORIES}
        report=OpportunityReport(fingerprint='0'*64,opportunity_id=None,categories=categories,
            status='completed',researched_at=now(),expires_at=now(),models={'reasoning':'gemini-3.5-flash-lite'})
        restored=OpportunityReport.model_validate_json(report.model_dump_json())
        assert restored==report and len(calls)==2
        assert all(f.source_ids==[sources[0].source_id] and f.quotes[0] in sources[0].evidence for f in findings)
        # Provider schema success alone cannot authorise an alias or forged quote.
        for changes in ({'field':'salary'},{'quotes':['Invented interview detail.']}):
            invalid=StructuredFindings(findings=[result.data.findings[0].model_copy(update=changes)])
            with pytest.raises(AIError):supported_claims(invalid,category,selected,public)
    asyncio.run(run())


def test_larger_gemini_evidence_budget_still_respects_context_character_bounds():
    sources=[ResearchSource(source_id=f's{i}',platform='other',url=f'https://example.test/{i}',
        evidence='a'*2400) for i in range(24)]
    selected=select_evidence(sources,8192)
    assert selected and len(json.dumps([s.model_dump(mode='json') for s in selected]))<=24000
    assert all(s.evidence in sources[i].evidence for i,s in enumerate(selected))


@pytest.mark.parametrize('kind',['opportunity_job','career_discovery'])
def test_only_unleased_obsolete_model_waits_resume_without_losing_work(kind):
    import os
    from datetime import timedelta
    from uuid import uuid4
    from pymongo import MongoClient
    from app.workflows.model_waits import resume_obsolete_model_waits
    uri=os.getenv('MONGODB_TEST_URI')
    if not uri:pytest.skip('Requires disposable MongoDB')
    mongo=MongoClient(uri,tz_aware=True,serverSelectionTimeoutMS=3000)
    db=mongo['elo_model_waits_test_'+uuid4().hex];rows=db.research_contexts
    stamp=now();future=stamp+timedelta(seconds=600)
    common={'kind':kind,'provider':'retired-provider','limit_scope':'provider','error_code':'rate_limited',
        'next_attempt_at':future,'status':'pending' if kind=='opportunity_job' else 'waiting',
        'finished':False,'lease_until':stamp,'worker_until':stamp,
        'evidence':{'saved':['synthetic public report']},'evaluated':['completed query']}
    values=[{'_id':'retired',**common},{'_id':'old-local',**common,'provider':None,'limit_scope':'user'},
        {'_id':'gemini',**common,'provider':'gemini'},{'_id':'brave',**common,'provider':'brave'},
        {'_id':'active',**common,'lease_until':future,'worker_until':future},
        {'_id':'complete',**common,'status':'completed','finished':True}]
    if kind=='opportunity_job':values.append({'_id':'parallel-brave',**common,
        'categories':{'internship_insights':{'status':'pending','error_code':'source_rate_limited'}}})
    try:
        rows.insert_many(values)
        assert resume_obsolete_model_waits(rows,kind)==2
        for identifier in ('retired','old-local'):
            row=rows.find_one({'_id':identifier})
            assert row['next_attempt_at']<=now() and row['provider'] is None and row['limit_scope'] is None
            assert row['evidence']==common['evidence'] and row['evaluated']==common['evaluated']
        for original in values[2:]:assert rows.find_one({'_id':original['_id']})==original
        assert resume_obsolete_model_waits(rows,kind)==0
    finally:
        mongo.drop_database(db.name);mongo.close()


@pytest.mark.parametrize('provider,expected',[
    ('gemini','gemini'),('brave','brave'),('retired-provider',None),(None,None)])
def test_public_responses_normalise_historical_provider_names(provider,expected):
    from pydantic import TypeAdapter
    from app.schemas.providers import ResearchProvider
    assert TypeAdapter(ResearchProvider).validate_python(provider)==expected
