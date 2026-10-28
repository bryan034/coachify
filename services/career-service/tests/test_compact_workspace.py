"""Canonical goals, cheap progress reads and lazy version-pinned evidence."""
import json
from types import SimpleNamespace
from bson import ObjectId
import pytest
from app.ai.adapter import AIError
from app.ai.opportunity_contracts import StructuredFindings
from app.schemas.analysis import ResearchSource
from app.workflows.opportunity.domain import validate_claims,supported_claims
from tests.test_workspace import ingest,headers,BASE,wait
from tests.test_opportunity import opportunity_flow,research
from tests.api_views import goal_content


def claim(**changes):
    return {'field':'mentorship','value':'A supportive mentor.','refs':[0],'quotes':['A supportive mentor.'],
        'confidence':'medium','evidence_type':'candidate_reported','scope':'exact',**changes}


def test_quotes_allow_only_whitespace_changes_and_precise_feedback():
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/a',evidence='A\n supportive   mentor.')
    result=validate_claims(StructuredFindings(findings=[claim(value='The mentor was supportive.')]),'internship_insights',[source])
    assert result[0].value=='The mentor was supportive.' and result[0].quotes==['A supportive mentor.']
    for changes,issue in [({'quotes':['a supportive mentor.']},'quote_not_in_source'),
            ({'quotes':['A supportive mentor!']},'quote_not_in_source'),({'refs':[1]},'source_index_out_of_range'),
            ({'field':'salary'},'field_not_allowed')]:
        with pytest.raises(AIError) as caught:supported_claims(StructuredFindings(findings=[claim(**changes)]),'internship_insights',[source])
        assert caught.value.violations==({'field':'findings.0.'+('refs' if 'refs' in changes else 'field' if 'field' in changes else 'quotes'),'issue':issue},)


def test_differently_worded_sources_can_corroborate_one_finding():
    quotes=['A supportive mentor.','The mentor gave useful guidance.']
    sources=[ResearchSource(source_id=str(i),platform='other',url=f'https://example.test/{i}',evidence=text)
        for i,text in enumerate(quotes)]
    output=StructuredFindings(findings=[claim(refs=[0,1],quotes=quotes,value='The mentor was supportive and offered guidance.')])
    findings,rejected=supported_claims(output,'internship_insights',sources)
    assert rejected==0 and findings[0].quotes==quotes and findings[0].source_ids==['0','1']
    assert findings[0].value=='The mentor was supportive and offered guidance.'
    # Values are now semantic rather than literal extracts; the engine performs
    # a separate meaning check before publishing any paraphrase.
    output=StructuredFindings(findings=[claim(value='The mentor offered helpful support.')])
    findings,_=supported_claims(output,'internship_insights',sources)
    assert findings[0].value=='The mentor offered helpful support.'



@pytest.mark.parametrize('changes,path,issue',[
    ({'quotes':['x'*601]},'quotes.0','string_too_long'),
    ({'scope':'company_wide'},'scope','literal_error'),
    ({'confidence':'certain'},'confidence','literal_error'),
    ({'evidence_type':'review'},'evidence_type','literal_error'),
])
def test_generation_and_storage_share_finding_constraints(changes,path,issue):
    from pydantic import ValidationError
    from app.ai.recovery import issues_for
    with pytest.raises(ValidationError) as caught:StructuredFindings(findings=[claim(**changes)])
    assert {'field':'findings.0.'+path,'issue':issue} in issues_for(caught.value,StructuredFindings)
    assert 'x'*601 not in json.dumps(issues_for(caught.value,StructuredFindings))


def test_finding_storage_errors_preserve_reason_and_claim_path():
    # Defensive validation of older/constructed provider objects must retain
    # repair instructions even when normal generation validation was bypassed.
    from app.ai.opportunity_contracts import Claim
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/a',evidence='A supportive mentor.')
    output=StructuredFindings.model_construct(findings=[Claim.model_construct(**claim(scope='company_wide'))])
    with pytest.raises(AIError) as caught:supported_claims(output,'internship_insights',[source])
    assert caught.value.reason=='schema_validation'
    assert caught.value.violations==({'field':'findings.0.scope','issue':'literal_error'},)


def test_longer_supported_value_uses_same_bound_as_storage():
    text='A supportive mentor. '+'Useful guidance. '*25
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/a',evidence=text)
    output=StructuredFindings(findings=[claim(value=text,quotes=[text])])
    findings,rejected=supported_claims(output,'internship_insights',[source])
    assert rejected==0 and findings[0].value==text.strip()


@pytest.mark.parametrize('summary',[
    'SGD 6000 per month in 2025',
    'SGD 5000 per month in 2026',
    'SGD 5,000 per month in 2025',
])
def test_numbers_must_match_cited_source_exactly(summary):
    text='Graduate salary was SGD 5000 per month in 2025.'
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/a',evidence=text)
    output=StructuredFindings(findings=[claim(field='conversion_salary',value=summary,quotes=[text])])
    with pytest.raises(AIError) as caught:validate_claims(output,'career_progression',[source])
    assert caught.value.violations[0]['issue']=='unsupported_number'


def test_numbers_can_come_from_the_cited_excerpt_outside_the_selected_quote():
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/a',
        evidence='Interns receive support. The monthly stipend is SGD 1500.')
    output=StructuredFindings(findings=[claim(field='compensation',value='The stipend is SGD 1500 monthly.',quotes=['Interns receive support.'])])
    result=validate_claims(output,'internship_insights',[source])
    assert result[0].source_ids==['a'] and result[0].value=='The stipend is SGD 1500 monthly.'


def test_numbers_in_an_uncited_source_do_not_support_a_finding():
    sources=[ResearchSource(source_id=str(i),platform='other',url=f'https://example.test/{i}',evidence=text)
        for i,text in enumerate(['Interns receive support.','The stipend is SGD 1500 monthly.'])]
    output=StructuredFindings(findings=[claim(field='compensation',value='SGD 1500 monthly',quotes=['Interns receive support.'])])
    with pytest.raises(AIError) as caught:validate_claims(output,'internship_insights',sources)
    assert caught.value.violations[0]['issue']=='unsupported_number'


def test_workspace_has_one_goal_and_progress_omits_content(opportunity_flow):
    flow=opportunity_flow;ingest(flow);workspace,result,path=research(flow)
    assert 'review' not in workspace and 'research' not in workspace
    goal=workspace['current']['goal'];stored=flow[1].career_goals.find_one({'_id':ObjectId(goal['_id'])})
    assert 'content' not in stored and flow[1].career_goals.count_documents({'record_type':'requirement_review'})==0
    progress=flow[0].get(BASE+'/progress',headers=headers()).json()
    assert progress['goal_id']==goal['_id'] and progress['revision']==goal['version']
    assert not {'current','review','research','sources','findings'}&progress.keys()
    assert all(set(v)<= {'status','error_code'} for v in progress['categories'].values())
    assert len(json.dumps(progress))<3000
    assert 'research' not in result and 'evidence' not in result['sources'][0]
    assert all('quotes' not in f for c in result['categories'].values() for f in c['findings'])
    report=flow[1].interview_research.find_one({'_id':ObjectId(workspace['research_id'])})
    assert not {'skills','process','summaries'}&report.keys()


def test_current_goal_edits_keep_id_and_enforce_version_and_replay(opportunity_flow):
    flow=opportunity_flow;ingest(flow);workspace,_,_=research(flow)
    client=flow[0];goal=workspace['current']['goal'];content=goal_content(goal);content['summary']='Updated public role scope.'
    body={'session_id':workspace['session_id'],'expected_version':goal['version'],'content':content}
    key=headers();response=client.patch(BASE+'/review',headers=key,json=body)
    assert response.status_code==200,response.text
    updated=response.json()['current']['goal']
    assert updated['_id']==goal['_id'] and updated['version']==goal['version']+1
    assert client.patch(BASE+'/review',headers=key,json=body).json()['current']['goal']['version']==updated['version']
    assert client.patch(BASE+'/review',headers=headers(),json=body).status_code==409
    assert flow[1].career_goals.count_documents({})==1
    stored=flow[1].career_goals.find_one({'_id':ObjectId(goal['_id'])})
    assert stored['summary']=='Updated public role scope.' and 'content' not in stored


def test_evidence_is_lazy_owner_scoped_and_pinned_to_report(opportunity_flow):
    flow=opportunity_flow;ingest(flow);workspace,result,path=research(flow)
    finding=result['categories']['interview_intelligence']['findings'][0]
    url=path+'/findings/'+finding['finding_id']+'/evidence?research_id='+workspace['research_id']
    assert flow[0].get(url,headers=headers(other=True)).status_code==404
    response=flow[0].get(url,headers=headers());assert response.status_code==200,response.text
    data=response.json();assert data['quotes'] and data['sources'][0]['evidence']
    assert flow[0].get(url.replace(workspace['research_id'],'0'*24),headers=headers()).status_code==404
    progress=flow[0].get(path+'/progress',headers=headers()).json()
    assert 'sources' not in progress and 'findings' not in json.dumps(progress)


def test_structured_wording_is_saved_without_another_model_pass(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];original=primary.generate;calls=[]
    text='Candidates describe a practical technical discussion.'
    async def generate(request,operation,**kwargs):
        calls.append(request.stage)
        result=await original(request,operation,**kwargs)
        if request.stage=='opportunity_structure' and json.loads(request.context)['category']=='interview_intelligence':
            result.data.findings[0].value=text
        return result
    primary.generate=generate;ingest(flow);_,result,_=research(flow)
    assert result['categories']['interview_intelligence']['findings'][0]['value']==text
    assert calls.count('opportunity_structure')==5
    job=flow[1].research_contexts.find_one({'kind':'opportunity_job'})
    assert set(job['metrics'])=={'opportunity_plan','opportunity_structure'}


def test_empty_retrieval_is_completed_with_category_not_found_notice(opportunity_flow):
    flow=opportunity_flow;flow[4].empty=True;ingest(flow);_,result,_=research(flow)
    assert result['status']=='completed'
    for category in result['categories'].values():
        assert category['status']=='completed' and category['error_code'] is None and not category['findings']
        assert any('not found' in warning for warning in category['warnings'])


def test_committed_edit_recovers_after_activation_is_interrupted(opportunity_flow):
    from app.schemas.jd import SaveReview
    flow=opportunity_flow;ingest(flow);workspace,_,_=research(flow)
    app=flow[0].app;goal=workspace['current']['goal'];content=goal_content(goal);content['summary']='Persisted before activation.'
    key=headers()['Idempotency-Key'];digest='synthetic-chat-digest'
    app.state.review_store.save(goal['_id'],'11111111-1111-4111-8111-111111111111',key,
        SaveReview(expected_version=goal['version'],content=content),chat_receipt={'hash':digest})
    # A read repairs workflow metadata without rolling the committed goal back.
    recovered=flow[0].get(BASE,headers=headers()).json()
    assert recovered['revision']==goal['version']+1 and recovered['current']['goal']['summary']=='Persisted before activation.'
    assert app.state.workspace_store.chat_replay('11111111-1111-4111-8111-111111111111',key,digest,workspace['session_id'])


def test_unsupported_numbers_in_structured_wording_get_precise_repair_feedback(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];original=primary.generate
    async def generate(request,operation,**kwargs):
        result=await original(request,operation,**kwargs)
        if request.stage=='opportunity_structure' and json.loads(request.context)['category']=='interview_intelligence':
            result.data.findings[0].value='There are 999 interview rounds.'
        return result
    primary.generate=generate;ingest(flow);_,result,_=research(flow)
    assert result['categories']['interview_intelligence']['status']=='failed'
    job=flow[1].research_contexts.find_one({'kind':'opportunity_job'})
    assert any(v['issue']=='unsupported_number' for step in job['model_recovery'].values() for v in step['feedback']['issues'])


def test_older_workspace_adopts_current_goal_before_editing(opportunity_flow):
    flow=opportunity_flow;ingest(flow);workspace,_,_=research(flow)
    goal=workspace['current']['goal'];owner='11111111-1111-4111-8111-111111111111'
    # An older deployment selected a separate intake record. Its content is obsolete.
    retired=ObjectId();flow[1].career_goals.insert_one({'_id':retired,'user_id':owner,'record_type':'requirement_review','content':{'role':'Obsolete role'}})
    flow[1].career_state.update_one({'_id':owner},{'$set':{'workspace.review_id':str(retired),'workspace.revision':3}})
    current=flow[0].get(BASE,headers=headers()).json()
    assert current['current']['goal']['_id']==goal['_id'] and current['current']['goal']['role']==goal['role']
    assert current['revision']==current['current']['goal']['version']==3
    content=goal_content(current['current']['goal']);content['summary']='Edit the canonical goal.'
    response=flow[0].patch(BASE+'/review',headers=headers(),json={'session_id':current['session_id'],'expected_version':3,'content':content})
    assert response.status_code==200,response.text
    assert response.json()['current']['goal']['_id']==goal['_id'] and response.json()['revision']==4


def test_upgrade_removes_only_retired_reset_copies(opportunity_flow):
    from app.repositories.reviews import ReviewStore
    flow=opportunity_flow;identifier=ObjectId();owner='11111111-1111-4111-8111-111111111111'
    original={'_id':identifier,'user_id':owner,'record_type':'requirement_review','content':{'role':'Effective role'},
        'baseline':{'role':'Obsolete original'},'baseline_origins':{'role':'extracted'},
        'metadata_origins':{'role':'user'},'receipts':[{'key':'synthetic','hash':'synthetic'}]}
    flow[1].career_goals.insert_one(original)
    ReviewStore(flow[1]);stored=flow[1].career_goals.find_one({'_id':identifier})
    assert stored=={k:v for k,v in original.items() if k not in ('baseline','baseline_origins')}
    ReviewStore(flow[1]);assert flow[1].career_goals.find_one({'_id':identifier})==stored


def test_gemini_decoding_uses_storage_label_enums():
    from app.ai.gemini_schema import gemini_schema
    from app.schemas.opportunity import Finding
    projected=gemini_schema(StructuredFindings.model_json_schema())['properties']['findings']['items']['properties']
    stored=Finding.model_json_schema()['properties']
    for field in ('scope','confidence','evidence_type'):
        assert projected[field]['enum']==stored[field]['enum']


def test_same_extract_with_different_summaries_keeps_one_stable_finding():
    from app.workflows.opportunity.domain import dedupe_findings
    text='Applications open between January and March.'
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/a',evidence=text)
    def extracted(summary):
        return validate_claims(StructuredFindings(findings=[claim(field='application_timeline',value=summary,
            quotes=[text])]),'interview_intelligence',[source])[0]
    first=extracted('Summer applications open between January and March.')
    later=extracted('Applications for summer open between January and March.').model_copy(update={'finding_id':first.finding_id})
    assert first.finding_id==later.finding_id and first.value!=later.value
    result=dedupe_findings('interview_intelligence',[first,later])
    assert len(result)==1 and result[0].finding_id==first.finding_id
    assert result[0].quotes==[text]
    # Growing corroboration must not change the ID and allow the original back in.
    additional=first.model_copy(update={'finding_id':'f'+'a'*16,'source_ids':['b'],'confidence':'low'})
    result=dedupe_findings('interview_intelligence',[*result,additional,first])
    assert len(result)==1 and result[0].finding_id==first.finding_id
    assert result[0].source_ids==['a','b'] and result[0].confidence=='low'


def test_quality_repairs_checkpoint_duplicates_and_report_can_publish(opportunity_flow):
    import asyncio
    from app.schemas.opportunity import CategoryResult
    flow=opportunity_flow;ingest(flow);workspace,_,_=research(flow)
    engine=flow[0].app.state.opportunities
    job=flow[1].research_contexts.find_one({'kind':'opportunity_job'})
    result=CategoryResult.model_validate(job['categories']['interview_intelligence'])
    original=result.findings[0]
    result.findings.append(original.model_copy(update={'value':'Candidates report a technical interview.'}))
    flow[1].research_contexts.update_one({'_id':job['_id']},{'$set':{
        'worker_token':'synthetic-repair','categories.interview_intelligence':result.model_dump(mode='json')}})
    state=asyncio.run(engine.quality({'job_id':job['_id']}))
    findings=state['results']['interview_intelligence']['findings']
    assert len(findings)==1 and findings[0]['finding_id']==original.finding_id
    from app.schemas.opportunity import OpportunityReport
    report=OpportunityReport(fingerprint=job['context']['details_fingerprint'],opportunity_id=None,
        categories=state['results'],status='completed',researched_at=original.last_verified_at,
        expires_at=original.last_verified_at,summary={'overview_refs':[original.finding_id]})
    assert report.summary.overview_refs==[original.finding_id]


def test_structured_paraphrases_do_not_require_literal_value_matching(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];original=primary.generate
    async def generate(request,operation,**kwargs):
        result=await original(request,operation,**kwargs)
        if request.stage=='opportunity_structure' and json.loads(request.context)['category']=='interview_intelligence':
            result.data.findings[0].value='Candidates describe a technical assessment.'
        return result
    primary.generate=generate;ingest(flow);_,result,_=research(flow)
    assert result['categories']['interview_intelligence']['status']=='completed'
    assert result['categories']['interview_intelligence']['findings'][0]['value']=='Candidates describe a technical assessment.'


@pytest.mark.parametrize('number',['.5','-5','5,000','1e3','50K'])
def test_numeric_tokens_cannot_be_hidden_by_formatting(number):
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/a',evidence='Interns receive support.')
    output=StructuredFindings(findings=[claim(value=f'Reported figure: {number}',quotes=['Interns receive support.'])])
    with pytest.raises(AIError) as caught:validate_claims(output,'internship_insights',[source])
    assert caught.value.violations[0]['issue']=='unsupported_number'


def test_structuring_prompt_requires_field_relevance_and_grounded_final_wording():
    from app.ai.opportunity_contracts import PROMPTS
    prompt=PROMPTS['opportunity_structure']
    assert 'final wording shown directly' in prompt and 'Never fill from pretraining' in prompt
    assert 'allowed fields' in prompt and 'never add facts' in prompt


def test_only_valid_source_references_reach_saved_structured_findings(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];original=primary.generate
    async def generate(request,operation,**kwargs):
        result=await original(request,operation,**kwargs)
        if request.stage=='opportunity_structure':
            result.data.findings.append(result.data.findings[0].model_copy(update={'refs':[999]}))
        return result
    primary.generate=generate;ingest(flow);_,result,_=research(flow)
    assert result['status']=='completed'
    ids={source['source_id'] for source in result['sources']}
    assert all(len(c['findings'])==1 and set(c['findings'][0]['source_ids'])<=ids for c in result['categories'].values())
