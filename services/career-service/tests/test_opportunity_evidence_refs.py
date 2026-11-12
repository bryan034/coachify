"""Request-bound decoding and backend-owned evidence links for public research."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.ai.adapter import AIAdapter,AIError,Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.opportunity_contracts import (
    ReferencedClaim,ReferencedFindings,FindingReferenceError,evidence_passages,
    findings_schema,structure_input,
)
from app.schemas.analysis import ResearchSource
from app.schemas.opportunity import CATEGORIES,FIELDS
from app.workflows.opportunity.domain import supported_claims,dedupe_findings
from app.workflows.opportunity.engine import OpportunityEngine
from tests.test_opportunity import opportunity_flow,research
from tests.test_workspace import ingest,headers


def source(index=0,text='Example interns receive SGD 1500 monthly.'):
    return ResearchSource(source_id=f's{index}',platform='other',url=f'https://example.test/{index}',evidence=text)


def claim(**changes):
    return {'field':'compensation','value':'Interns receive SGD 1500 monthly.',
        'evidence_ref':0,'confidence':'medium','evidence_type':'candidate_reported',
        'scope':'exact','conflict_group':None,**changes}


@pytest.mark.parametrize('category',CATEGORIES)
@pytest.mark.parametrize('provider',['local','compatible','deepseek'])
def test_decoding_schema_is_bound_to_actual_category_sources_and_passages(category,provider):
    sources=[source(0,('A complete sentence about mentorship. '*25)),source(1)]
    context=structure_input({},category,sources)
    settings=AISettings(provider=provider,response_mode='json_object' if provider=='deepseek' else 'json_schema_strict')
    payload=AIAdapter(settings,None)._payload(AIInput(stage='opportunity_structure',context=json.dumps(context)))
    if provider=='deepseek':
        schema=json.loads(payload['messages'][0]['content'].split('JSON schema: ',1)[1])
        assert payload['response_format']=={'type':'json_object'}
    else:
        schema=payload['response_format']['json_schema']['schema']
    item=schema['properties']['findings']['items']
    properties=(schema['$defs'][item['$ref'].split('/')[-1]] if '$ref' in item else item)['properties']
    assert properties['field']['enum']==list(FIELDS[category])
    assert properties['evidence_ref']['enum']==list(range(len(context['evidence'])))
    assert schema['properties']['relevant_refs']['items']['enum']==[0,1]
    assert len(context['evidence'])>len(sources)
    assert not {'quotes','refs','source_ids'}&set(properties)
    assert all('excerpt' not in item for item in context['sources'])


def test_passages_preserve_exact_unicode_text_and_multiple_source_attribution():
    text='  Internship account.\n資料 and café — mentorship. '+('Complete sentence about projects. '*60)
    sources=[source(0,text),source(1,text)]
    passages=evidence_passages(sources)
    assert [item['ref'] for item in passages]==list(range(len(passages)))
    assert {item['source_ref'] for item in passages}=={0,1}
    for item in passages:
        assert 1<=len(item['text'])<=600
        assert item['text'] in sources[item['source_ref']].evidence
    for index in (0,1):
        selected=[item['text'] for item in passages if item['source_ref']==index]
        assert ''.join(''.join(part.split()) for part in selected)==''.join(text.split())


def test_python_resolves_the_selected_passage_and_actual_source_without_model_quotes():
    sources=[source(0,'Example interns report mentorship.'),source(1)]
    context=structure_input({},'internship_insights',sources)
    output=ReferencedFindings(findings=[claim(evidence_ref=1)],relevant_refs=[1])
    resolved=output.to_domain(context)
    findings,rejected=supported_claims(resolved,'internship_insights',sources)
    assert rejected==0
    assert findings[0].source_ids==['s1']
    assert findings[0].quotes==[context['evidence'][1]['text']]


@pytest.mark.parametrize('change,issue',[
    ({'field':'recruitment_stages'},'field_not_allowed'),
    ({'field':'PRIVATE_MODEL_ALIAS'},'field_not_allowed'),
    ({'evidence_ref':77},'evidence_reference_not_found'),
])
def test_json_mode_cannot_bypass_request_bound_reference_validation(change,issue):
    sources=[source()];context=structure_input({},'internship_insights',sources)
    output=ReferencedFindings(findings=[claim(**change)]).to_domain(context)
    with pytest.raises(AIError) as caught:supported_claims(output,'internship_insights',sources)
    assert caught.value.violations==({'field':'findings.0.'+('field' if 'field' in change else 'evidence_ref'),'issue':issue},)
    assert 'PRIVATE' not in str(caught.value.violations)


@pytest.mark.parametrize('reference',[-1,2,True,'0'])
def test_relevance_and_evidence_refs_cannot_use_missing_or_coerced_indexes(reference):
    context=structure_input({},'internship_insights',[source()])
    if type(reference) is not int or reference<0:
        with pytest.raises(ValidationError):ReferencedFindings(relevant_refs=[reference])
        with pytest.raises(ValidationError):ReferencedClaim(**claim(evidence_ref=reference))
    else:
        with pytest.raises(FindingReferenceError):ReferencedFindings(relevant_refs=[reference]).to_domain(context)


def test_invalid_reference_does_not_discard_independently_supported_findings():
    sources=[source()];context=structure_input({},'internship_insights',sources)
    output=ReferencedFindings(findings=[claim(),claim(evidence_ref=99),claim(field='salary')]).to_domain(context)
    findings,rejected=supported_claims(output,'internship_insights',sources)
    assert len(findings)==1 and rejected==2
    assert findings[0].quotes==[sources[0].evidence]


def test_numeric_claim_must_be_supported_by_selected_passage_not_neighbouring_text():
    text='Example interns report weekly mentorship. '+('Projects use team collaboration. '*22)+' Another role receives SGD 9000 monthly.'
    sources=[source(text=text)];context=structure_input({},'internship_insights',sources)
    assert len(context['evidence'])>1 and '9000' not in context['evidence'][0]['text']
    output=ReferencedFindings(findings=[claim(value='Interns receive SGD 9000 monthly.')]).to_domain(context)
    with pytest.raises(AIError) as caught:supported_claims(output,'internship_insights',sources)
    assert caught.value.violations[0]['issue']=='unsupported_number'


def test_repeated_findings_from_two_passages_merge_both_real_citations():
    sources=[source(0),source(1)];context=structure_input({},'internship_insights',sources)
    output=ReferencedFindings(findings=[claim(evidence_ref=index) for index in (0,1)]).to_domain(context)
    findings,_=supported_claims(output,'internship_insights',sources)
    merged=dedupe_findings('internship_insights',findings)
    assert len(merged)==1 and merged[0].source_ids==['s0','s1']
    assert merged[0].quotes==[s.evidence for s in sources]


def test_adapter_and_bounded_repair_use_the_same_catalogue_and_preserve_safe_feedback(caplog):
    async def run():
        sources=[source()];context=structure_input({},'internship_insights',sources)
        calls=[]
        def handler(request):
            calls.append(json.loads(request.content))
            # A provider ignoring schema enums must still pass backend validation.
            output={'findings':[claim(evidence_ref=99 if len(calls)==1 else 0)],'relevant_refs':[0],'follow_up_query':None}
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            engine=object.__new__(OpportunityEngine)
            engine.ai=AIAdapter(AISettings(enabled=True,provider='local'),client)
            engine.settings=SimpleNamespace(schema_repairs=1)
            engine.store=SimpleNamespace(update=lambda *a,**kw:None,rows=SimpleNamespace(update_one=lambda *a:None))
            result=await engine.generate({'_id':'synthetic','owner':'synthetic','goal_id':'synthetic','worker_token':'synthetic'},
                'opportunity_structure',context,lambda output:supported_claims(output,'internship_insights',sources))
        assert len(calls)==2
        assert calls[0]['messages'][1]==calls[1]['messages'][1]
        assert 'evidence_reference_not_found' in calls[1]['messages'][0]['content']
        assert result.findings[0].quotes==[sources[0].evidence]
        assert '1500' not in caplog.text and 'example.test' not in caplog.text
    asyncio.run(run())


def test_passage_catalogue_is_never_silently_truncated_to_fit_context():
    context=structure_input({},'internship_insights',[source(text='資料 '*1400)])
    adapter=AIAdapter(AISettings(provider='local',context_tokens=8192),None)
    with pytest.raises(AIError,match='context_limit'):
        adapter._payload(AIInput(stage='opportunity_structure',context=json.dumps(context,ensure_ascii=False)))


def test_model_cannot_supply_its_own_quote_or_source_binding():
    with pytest.raises(ValidationError):ReferencedClaim(**claim(quotes=['fabricated quote'],refs=[0]))


def test_referenced_provider_findings_persist_and_remain_readable_through_existing_apis(opportunity_flow):
    client,db,primary,*_=opportunity_flow
    original=primary.generate;calls=[]
    def handler(request):
        payload=json.loads(request.content);context=json.loads(payload['messages'][1]['content']);calls.append(context)
        passage=context['evidence'][0]
        output={'findings':[claim(field=context['allowed_fields'][0],value=passage['text'],evidence_ref=passage['ref'])],
                'relevant_refs':[passage['source_ref']],'follow_up_query':None}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
    transport=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter=AIAdapter(AISettings(enabled=True,provider='local'),transport)
    async def generate(request,operation,**kwargs):
        if request.stage=='opportunity_structure':return await adapter.generate(request,operation,**kwargs)
        return await original(request,operation,**kwargs)
    primary.generate=generate
    try:
        assert ingest(opportunity_flow).status_code==202
        workspace,result,path=research(opportunity_flow)
        assert result['status']=='completed' and len(calls)==5
        assert all(category['findings'] for category in result['categories'].values())
        finding=result['categories']['internship_insights']['findings'][0]
        # Public reads stay compact; exact quotes remain in the existing evidence read.
        assert 'quotes' not in finding
        evidence=client.get(path+'/findings/'+finding['finding_id']+'/evidence?research_id='+workspace['research_id'],headers=headers())
        assert evidence.status_code==200
        assert evidence.json()['quotes']==['Example interns report SGD 1500 per month.']
        saved=db.interview_research.find_one({'intelligence.categories.internship_insights.findings.finding_id':finding['finding_id']})
        assert saved['intelligence']['categories']['internship_insights']['findings'][0]['quotes']==evidence.json()['quotes']
        historical=client.get(path+'?research_id='+workspace['research_id'],headers=headers())
        assert historical.status_code==200 and historical.json()['historical'] is True
        assert historical.json()['categories']==result['categories']
    finally:client.portal.call(transport.aclose)


def test_finding_wording_is_short_while_stored_quotes_keep_full_passages():
    with pytest.raises(ValidationError):ReferencedClaim.model_validate(claim(value='x'*241))
    sources=[source(0,'Example interns receive SGD 1500 monthly. '+('Complete sentence about projects. '*15))]
    context=structure_input({},'internship_insights',sources)
    result=ReferencedFindings.model_validate({'findings':[claim(value='x'*240)]}).to_domain(context)
    assert len(result.findings[0].quotes[0])>240


@pytest.mark.parametrize('category',CATEGORIES)
def test_interview_research_may_return_more_findings_than_other_categories(category):
    context=structure_input({},category,[source()])
    expected=20 if category=='interview_intelligence' else 12
    assert findings_schema(context)['properties']['findings']['maxItems']==expected
    items=[claim(field='interview_questions',value=f'Question {n}?') for n in range(20)]
    assert len(ReferencedFindings.model_validate({'findings':items}).findings)==20


def test_key_term_bold_is_kept_when_reasonable_and_dropped_when_not():
    from app.schemas.opportunity import plain_text
    kept='Interns receive **SGD 1500** monthly.'
    assert ReferencedClaim.model_validate(claim(value=kept)).value==kept
    for bad in ('**Everything is bold here**','**All** **bold**','**a** **b** **c** **d** extra text here','Use <b>html</b> and **bold**','Stray * asterisk'):
        assert '*' not in ReferencedClaim.model_validate(claim(value=bad)).value
    assert plain_text('A **key** term') =='A key term'


def test_bold_markers_do_not_change_identity_numbers_or_dedupe():
    sources=[source(0)]
    out=lambda value:supported_claims(ReferencedFindings.model_validate({'findings':[claim(value=value)]}).to_domain(structure_input({},'internship_insights',sources)),'internship_insights',sources)[0]
    plain,bold=out('Interns receive SGD 1500 monthly.')[0],out('Interns receive **SGD 1500** monthly.')[0]
    assert plain.finding_id==bold.finding_id and bold.value=='Interns receive **SGD 1500** monthly.'
    assert len(dedupe_findings('internship_insights',[plain,bold]))==1
