"""Discovery candidate selection and provider-budget regressions."""
import asyncio
import json
import httpx
import pytest
from app.ai.adapter import AIAdapter,AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.usage import input_tokens
from app.clients.search_sources import SourceAPIs
from app.domain.discovery_sources import candidates,excluded_kind,ranked_sources,validate_assessments
from app.schemas.analysis import ResearchContext
from app.schemas.discovery import DiscoverySource as ResearchSource
from app.schemas.discovery import SourceAssessment,SourceAssessments,Listings,Listing,Requirement,Scope
from app.workflows.discovery import validated_listings


def source(index,company='Employer'):
    return ResearchSource(source_id=f's{index}',platform='other',url=f'https://example.test/job/{index}',
        company=company,title=f'{company} Portfolio Manager',evidence=f'{company} Portfolio Manager manages investment portfolios. Bloomberg is required.')


def test_discovery_requests_five_ranked_url_contexts_without_changing_opportunity_budgets():
    async def run():
        calls=[]
        def handler(request):
            calls.append(dict(request.url.params))
            return httpx.Response(200,json={'grounding':{'generic':[
                {'url':f'https://example.test/job/{i}','title':f'Employer {i} Portfolio Manager',
                 'snippets':[f'Employer {i} Portfolio Manager manages investment portfolios. Bloomberg is required.']}
                for i in (7,14,19,22,29)]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider=SourceAPIs(client,brave_key='synthetic')
            context=ResearchContext(field='Finance',role='Portfolio Management')
            found=await provider.collect_discovery_query(context,'Finance Portfolio Management employer vacancy')
            old=await provider.collect_opportunity_query(context,'Portfolio Management interview')
        assert len(found)==5 and len(old)==3
        assert {v.url for v in found}=={f'https://example.test/job/{i}' for i in (7,14,19,22,29)}
        assert calls[0]['count']=='50' and calls[0]['maximum_number_of_urls']=='5'
        assert calls[0]['maximum_number_of_tokens']=='16384' and calls[0]['maximum_number_of_tokens_per_url']=='2048'
        assert calls[0]['context_threshold_mode']=='strict'
        assert calls[1]['count']=='30' and calls[1]['maximum_number_of_tokens']=='8192' and calls[1]['context_threshold_mode']=='balanced'
    asyncio.run(run())


@pytest.mark.parametrize('url,title',[
    ('https://www.glassdoor.com/Job/portfolio-manager-jobs-SRCH_KO0,17.htm','Portfolio manager jobs'),
    ('https://www.indeed.com/q-portfolio-manager-jobs.html','Portfolio Manager Jobs, Employment'),
    ('https://www.indeed.com/jobs?q=portfolio+manager','Search jobs'),
    ('https://example.test/careers/search','Find vacancies'),
    ('https://example.test/job-descriptions/portfolio-manager','Portfolio Manager Job Description'),
    ('https://example.test/job-search/position-overview/portfolio-manager','How to become a Portfolio Manager'),
])
def test_indexes_and_templates_cannot_become_listing_evidence(url,title):
    item=source(0);item.url=url;item.title=title
    assert excluded_kind(item)
    listing=Listing(ref=0,job_title='Portfolio Manager',location=None,career_stage='experienced',
        relevant=True,requirements=[Requirement(kind='skill',name='Bloomberg',quote='Bloomberg is required.')])
    assert validated_listings(Listings(listings=[listing]),[item],Scope(field='Finance',area='Portfolio Management'))==[]


def test_sources_beyond_first_five_are_ranked_by_relevance_and_employer_diversity():
    found=[source(i,'Repeated employer' if i<6 else f'Employer {i}') for i in range(10)]
    scores={v.source_id:{'relevant':True,'score':1 if i<6 else 3,'company':'Repeated employer' if i<6 else f'Employer {i}'} for i,v in enumerate(found)}
    selected=ranked_sources(found,scores,[],[],5)
    assert {v.source_id for v in selected}=={'s0','s6','s7','s8','s9'}
    assert selected[0].source_id in {'s6','s7','s8','s9'}


def test_rejected_same_title_other_field_does_not_enter_selected_sources():
    right=source(0);wrong=source(1,'Project Company')
    wrong.evidence='Project Company Portfolio Manager coordinates a portfolio of software projects.'
    values=SourceAssessments(sources=[
        SourceAssessment(ref=0,relevant=True,score=3,quote='manages investment portfolios.'),
        SourceAssessment(ref=1,relevant=False,score=0,quote=None)])
    assessments=validate_assessments(values,[right,wrong])
    assert ranked_sources([wrong,right],assessments,[],[],20)==[right]


def test_assessment_accepts_paraphrases_and_uses_only_brave_employer_metadata():
    correct=SourceAssessment(ref=0,relevant=True,score=3,quote='Oversees a portfolio of investments.')
    result=validate_assessments(SourceAssessments(sources=[correct]),[source(0)])
    assert result['s0']['quote']=='Oversees a portfolio of investments.'
    assert result['s0']['company']=='Employer'
    assert 'kind' not in SourceAssessment.model_fields and 'company' not in SourceAssessment.model_fields
    with pytest.raises(AIError):validate_assessments(SourceAssessments(sources=[correct.model_copy(update={'ref':1})]),[source(0)])
    with pytest.raises(AIError):validate_assessments(SourceAssessments(sources=[]),[source(0)])


def test_kind_and_generated_company_are_ignored_even_in_legacy_responses():
    value=SourceAssessment.model_validate({'ref':0,'kind':'Job Listing / role',
        'company':'A model-invented company','relevant':True,'score':3,
        'quote':'Oversees investments.'})
    result=validate_assessments(SourceAssessments(sources=[value]),[source(0)])
    assert result['s0']['company']=='Employer' and 'kind' not in result['s0']
    listing=Listing.model_validate({'ref':0,'company':'A different invented company',
        'job_title':'Portfolio Manager','location':None,'career_stage':'unspecified',
        'relevant':True,'requirements':[{'kind':'skill','name':'Bloomberg',
        'quote':'Knowledge of Bloomberg is necessary.'}]})
    assert validated_listings(Listings(listings=[listing]),[source(0)],
        Scope(field='Finance',area='Finance'))[0]['company']=='Employer'


def test_discovery_prompts_and_provider_schemas_allow_faithful_paraphrases():
    from app.ai.discovery_contracts import PROMPTS
    assert 'kind' not in SourceAssessment.model_json_schema()['properties']
    assert 'company' not in Listing.model_json_schema()['properties']
    assert 'faithful paraphrase' in PROMPTS['discovery_assess']
    assert 'negations' in PROMPTS['discovery_assess']
    assert 'not necessarily exact substrings' in PROMPTS['discovery_extract']
    assert 'required/preferred' in PROMPTS['discovery_extract']


def test_all_candidates_are_pooled_and_failed_extractions_free_slots():
    found=candidates([source(i).model_dump(mode='json') for i in range(40)])
    assert len(found)==40
    scores={v.source_id:{'relevant':True,'score':3,'company':f'Employer {i}'} for i,v in enumerate(found)}
    evaluated=[v.source_id for v in found[:20]]
    selected=ranked_sources(found,scores,evaluated,[],20)
    assert len(selected)==20 and all(v.source_id not in evaluated for v in selected)


def test_discovery_uses_larger_output_and_real_token_input_estimates():
    async def run():
        async with httpx.AsyncClient() as client:
            adapter=AIAdapter(AISettings(enabled=True,api_key='synthetic'),client)
            context=json.dumps({'sources':[{'excerpt':'資料'*10000}]},ensure_ascii=False)
            payload=adapter._payload(AIInput(stage='discovery_extract',context=context))
            assert payload['max_tokens']==8192
            assert input_tokens(payload)<=32768
            assert json.loads(payload['messages'][1]['content'])['context']==context
            assert '[truncated]' not in str(payload)
            assert sum(len(v['content'].encode()) for v in payload['messages'])>32768
            for shared_cap in (512,4096,8192):
                configured=AIAdapter(AISettings(enabled=True,api_key='synthetic',max_output_tokens=shared_cap),client)
                assert configured._payload(AIInput(stage='discovery_extract',context='{}'))['max_tokens']==8192
                assert configured._payload(AIInput(stage='opportunity_structure',context='{}'))['max_tokens']==min(shared_cap,2048)
    asyncio.run(run())


def test_discovery_does_not_silently_shorten_evidence_to_fit_small_context():
    async def run():
        async with httpx.AsyncClient() as client:
            adapter=AIAdapter(AISettings(enabled=True,api_key='synthetic',context_tokens=16000),client)
            context=json.dumps({'sources':[{'excerpt':'alpha1 beta2 gamma3 '*1800}]})
            with pytest.raises(AIError,match='context_limit'):adapter._payload(AIInput(stage='discovery_extract',context=context))
    asyncio.run(run())


def test_employer_is_copied_from_brave_structured_data_not_publisher_or_gemini():
    async def run():
        def handler(request):
            url='https://example.test/job/1'
            return httpx.Response(200,json={
                'grounding':{'generic':[{'url':url,'title':'Analyst vacancy',
                    'snippets':[json.dumps({'@type':'JobPosting','hiringOrganization':{'name':'Example Bank'}}),
                                'Analyst works with financial statements.']}]},
                'sources':{url:{'site_name':'Example Job Board'}}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider=SourceAPIs(client,brave_key='synthetic')
            context=ResearchContext(field='Finance',role='Finance')
            found=await provider.collect_discovery_query(context,'Finance jobs')
            other=await provider.collect_opportunity_query(context,'Finance interview')
        assert found[0].company=='Example Bank'
        assert 'company' not in other[0].model_dump()
        from app.clients.search_sources import discovery_employer
        assert discovery_employer(['Ordinary page text']) is None
        assert discovery_employer([json.dumps({'site_name':'Job Board'})]) is None
        assert discovery_employer([json.dumps({'hiringOrganization':{'name':'A'}}),
                                   json.dumps({'hiringOrganization':{'name':'B'}})]) is None
    asyncio.run(run())
