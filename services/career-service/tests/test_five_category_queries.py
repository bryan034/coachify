"""Role-tailored initial plans, five intents, compatibility and numeric provenance."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from app.ai.adapter import AIError
from app.ai.jd_scope import JobIdentity
from app.ai.opportunity_contracts import QueryPlan,Evaluation,PROMPTS
from app.repositories.goals import now
from app.schemas.analysis import ResearchSource
from app.schemas.opportunity import CATEGORIES,LEGACY_FIELDS,CategoryResult,OpportunityReport
from app.workflows.jd_prefetch import prefetch
from app.workflows.opportunity.domain import validate_claims
from tests.test_opportunity import opportunity_flow

@pytest.mark.parametrize('company',['Example',None])
@pytest.mark.parametrize(('role','field','terms'),[
 ('Investment Banking Summer Analyst','Finance','valuation accounting deal exposure'),
 ('Software Engineering Intern','Software Engineering','coding algorithms API projects'),
])
def test_gemini_writes_all_five_initial_queries_before_brave(role,field,terms,company):
    calls=[];plans=[]
    identity=JobIdentity(is_job_description=True,role=role,field=field,company=company,location='Singapore',employment_type='internship',evidence=['Synthetic JD'])
    expected={category:[f'Example {role} Singapore {category} {terms}'] for category in CATEGORIES}
    class AI:
        async def generate(self,request,operation,**kwargs):
            assert request.stage=='opportunity_plan'
            data=json.loads(request.context);plans.append(data)
            assert data['opportunity']['role']==role and data['opportunity']['field']==field
            assert set(data['opportunity'])=={'company','role','field','location','seniority_level','employment_type'}
            return SimpleNamespace(data=QueryPlan(**expected))
    class Search:
        async def collect_opportunity_query(self,context,query):
            assert len(plans)==1;calls.append(query);return []
    engine=SimpleNamespace(ai=AI(),source=Search(),slots=asyncio.Semaphore(3),settings=SimpleNamespace(timeout_seconds=30,max_searches=2))
    result=asyncio.run(prefetch(engine,identity,'synthetic-owner','synthetic-revision'))
    assert set(calls)=={values[0] for values in expected.values()}
    assert result['queries_planned'] and result['queries']==expected
    assert set(result['history'])==set(CATEGORIES)
    assert 'actual questions' in PROMPTS['opportunity_plan']
    assert 'historical' in PROMPTS['opportunity_plan']


def test_early_planner_failure_never_sends_template_queries():
    class AI:
        async def generate(self,*args,**kwargs):raise AIError('provider_configuration')
    class Search:
        async def collect_opportunity_query(self,*args):pytest.fail('No unplanned searches allowed')
    engine=SimpleNamespace(ai=AI(),source=Search(),settings=SimpleNamespace(timeout_seconds=30,max_searches=2))
    result=asyncio.run(prefetch(engine,JobIdentity(is_job_description=True,role='Analyst'),'owner','revision'))
    assert not result.get('queries_planned') and not result['history']


def test_query_plan_requires_every_category_and_bounded_nonempty_wording():
    values={category:['Example Analyst Singapore relevant query'] for category in CATEGORIES}
    for change in ({'career_progression':[]},{'conversion_outcomes':['x'*181]}):
        with pytest.raises(ValidationError):QueryPlan(**{**values,**change})
    with pytest.raises(ValidationError):QueryPlan(**{k:v for k,v in values.items() if k!='conversion_outcomes'})


def test_v1_reports_stay_readable_but_v2_requires_five_explicit_statuses():
    base=dict(fingerprint='a'*64,opportunity_id=None,status='completed',researched_at=now(),expires_at=now())
    categories={k:CategoryResult(status='completed') for k in LEGACY_FIELDS}
    assert OpportunityReport(schema_version=1,categories=categories,**base).schema_version==1
    with pytest.raises(ValidationError):OpportunityReport(categories=categories,**base)
    assert len(OpportunityReport(categories={k:CategoryResult(status='completed') for k in CATEGORIES},**base).categories)==5


@pytest.mark.parametrize(('text','valid'),[
 ('Example interns in the 2025 Singapore cohort had a 50% full-time conversion rate.',True),
 ('One Example intern received a return offer in 2025.',False),
 ('Example interns had a 50% conversion rate.',False),
 ('Example company revenue grew 50% in 2025.',False),
])
def test_conversion_percentage_needs_historical_intern_cohort_evidence(text,valid):
    source=ResearchSource(source_id='s',platform='other',url='https://example.test/cohort',evidence=text)
    output=Evaluation(findings=[dict(field='conversion_rate',value=text,refs=[0],quotes=[text],confidence='medium',evidence_type='candidate_reported',scope='exact')])
    if valid:assert validate_claims(output,'conversion_outcomes',[source])[0].value==text
    else:
        with pytest.raises(AIError):validate_claims(output,'conversion_outcomes',[source])


def test_unfinished_legacy_jobs_gain_missing_categories_without_losing_evidence(opportunity_flow):
    client,db,*_=opportunity_flow;engine=client.app.state.opportunities
    categories={k:CategoryResult(status='completed').model_dump(mode='json') for k in LEGACY_FIELDS}
    db.research_contexts.insert_one({'_id':'legacy-upgrade','worker_token':'synthetic','categories':categories,'requested':[],
        'history':{'interview_intelligence':['already paid query']},'evidence':{'interview_intelligence':[]}})
    client.portal.call(engine.load,{'job_id':'legacy-upgrade'})
    job=db.research_contexts.find_one({'_id':'legacy-upgrade'})
    assert set(job['categories'])==set(CATEGORIES)
    assert job['history']=={'interview_intelligence':['already paid query']}
    assert set(job['requested'])=={'career_progression','conversion_outcomes'}


def test_summary_budget_preserves_evidence_from_all_five_categories():
    from app.workflows.opportunity.domain import summary_input
    categories={category:SimpleNamespace(findings=[SimpleNamespace(finding_id=f'{category}-{i}',field='synthetic',value='Synthetic evidence',confidence='medium',scope='exact',conflict_group=None) for i in range(20)]) for category in CATEGORIES}
    selected=summary_input(categories)
    assert len(selected)==60
    assert all(sum(item['category']==category for item in selected)==12 for category in CATEGORIES)


@pytest.mark.parametrize(('text','valid'),[
 ('Example conversion offer in 2025 is SGD 5000 monthly base salary.',True),
 ('Example salaries are competitive and generous.',False),
 ('Example conversion pay in 2025 is 5000 monthly, currency unknown.',False),
])
def test_conversion_salary_cannot_invent_amount_or_currency(text,valid):
    source=ResearchSource(source_id='s',platform='other',url='https://example.test/salary',evidence=text)
    output=Evaluation(findings=[dict(field='conversion_salary',value=text,refs=[0],quotes=[text],confidence='medium',evidence_type='candidate_reported',scope='exact')])
    if valid:assert validate_claims(output,'career_progression',[source])[0].value==text
    else:
        with pytest.raises(AIError):validate_claims(output,'career_progression',[source])
