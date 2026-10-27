"""Canonical goals, cheap progress reads and lazy version-pinned evidence."""
import json
from types import SimpleNamespace
from bson import ObjectId
import pytest
from app.ai.adapter import AIError
from app.ai.opportunity_contracts import Evaluation,SupportedSummaries
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
    result=validate_claims(Evaluation(findings=[claim(summary='The mentor was supportive.')]),'internship_insights',[source])
    assert result[0].value=='The mentor was supportive.' and result[0].quotes==['A supportive mentor.']
    for changes,issue in [({'quotes':['a supportive mentor.']},'quote_not_in_source'),
            ({'quotes':['A supportive mentor!']},'quote_not_in_source'),({'refs':[1]},'source_index_out_of_range'),
            ({'field':'salary'},'field_not_allowed')]:
        with pytest.raises(AIError) as caught:supported_claims(Evaluation(findings=[claim(**changes)]),'internship_insights',[source])
        assert caught.value.violations==({'field':'findings.0.'+('refs' if 'refs' in changes else 'field' if 'field' in changes else 'quotes'),'issue':issue},)


@pytest.mark.parametrize('summary,issue',[
    ('SGD 6000 per month in 2025','unsupported_number'),
    ('USD 5000 per month in 2025','unsupported_numeric_unit'),
    ('SGD 5000 in 2025','salary_period_required'),
    ('SGD 5000 per month','salary_year_required'),
])
def test_salary_summaries_preserve_amount_currency_period_and_year(summary,issue):
    text='Graduate salary was SGD 5000 per month in 2025.'
    source=ResearchSource(source_id='a',platform='other',url='https://example.test/a',evidence=text)
    output=Evaluation(findings=[claim(field='conversion_salary',value=text,quotes=[text],summary=summary)])
    with pytest.raises(AIError) as caught:validate_claims(output,'career_progression',[source])
    assert caught.value.violations[0]['issue']==issue


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


def test_grounded_presentation_uses_separate_support_check(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];original=primary.generate;calls=[]
    async def generate(request,operation,**kwargs):
        if request.stage=='opportunity_support':
            calls.append(json.loads(request.context))
            return SimpleNamespace(data=SupportedSummaries(supported_refs=[0]))
        result=await original(request,operation,**kwargs)
        if request.stage=='opportunity_evaluate' and json.loads(request.context)['category']=='interview_intelligence':
            result.data.findings[0].summary='Candidates report a technical interview.'
        return result
    primary.generate=generate;ingest(flow);_,result,_=research(flow)
    finding=result['categories']['interview_intelligence']['findings'][0]
    assert finding['value']=='Candidates report a technical interview.' and calls


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


def test_unsupported_presentation_is_repaired_with_specific_feedback(opportunity_flow):
    flow=opportunity_flow;primary=flow[2];original=primary.generate
    async def generate(request,operation,**kwargs):
        if request.stage=='opportunity_support':return SimpleNamespace(data=SupportedSummaries(supported_refs=[]))
        result=await original(request,operation,**kwargs)
        if request.stage=='opportunity_evaluate' and json.loads(request.context)['category']=='interview_intelligence':
            result.data.findings[0].summary='Candidates are guaranteed to receive an offer.'
        return result
    primary.generate=generate;ingest(flow);_,result,_=research(flow)
    assert result['categories']['interview_intelligence']['status']=='failed'
    assert result['categories']['interview_intelligence']['findings']==[]
    job=flow[1].research_contexts.find_one({'kind':'opportunity_job'})
    feedback=[step['feedback'] for step in job['model_recovery'].values()]
    assert any(v['issue']=='summary_not_supported' for f in feedback for v in f.get('issues',[]))
    assert 'guaranteed' not in json.dumps(feedback)


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
