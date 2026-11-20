"""Role-tailored initial plans, five intents, compatibility and numeric provenance."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from app.ai.adapter import AIError
from app.ai.jd_scope import JobIdentity
from app.ai.opportunity_contracts import QueryPlan,StructuredFindings,PROMPTS
from app.repositories.goals import now
from app.schemas.analysis import ResearchSource
from app.schemas.opportunity import CATEGORIES,LEGACY_FIELDS,CategoryResult,OpportunityReport
from app.workflows.jd_prefetch import prefetch
from app.workflows.opportunity.domain import validate_claims
from app.workflows.opportunity.topics import TOPICS,policy,topic_query
from tests.test_opportunity import opportunity_flow

@pytest.mark.parametrize('company',['Example',None])
@pytest.mark.parametrize(('role','field','terms'),[
 ('Investment Banking Summer Analyst','Finance','valuation accounting deal exposure'),
 ('Software Engineering Intern','Software Engineering','coding algorithms API projects'),
])
def test_model_writes_every_topic_query_before_search(role,field,terms,company):
    calls=[];plans=[]
    identity=JobIdentity(is_job_description=True,role=role,field=field,company=company,location='Singapore',employment_type='internship',evidence=['Synthetic JD'])
    expected={topic:[f'Example {role} Singapore {topic} {terms}'] for topic in TOPICS}
    class AI:
        async def generate(self,request,operation,**kwargs):
            assert request.stage=='opportunity_plan'
            data=json.loads(request.context);plans.append(data)
            assert data['opportunity']['role']==role and data['opportunity']['field']==field
            assert set(data['opportunity'])=={'company','role','field','location','seniority_level','employment_type'}
            return SimpleNamespace(data=QueryPlan(**expected))
    class Search:
        async def collect_opportunity_query(self,context,query,max_sources):
            assert len(plans)==1;calls.append((query,max_sources));return []
    engine=SimpleNamespace(ai=AI(),source=Search(),slots=asyncio.Semaphore(3),settings=SimpleNamespace(timeout_seconds=30,topic_searches=2,run_searches=40))
    result=asyncio.run(prefetch(engine,identity,'synthetic-owner','synthetic-revision'))
    public={'company':company,'role':role}
    planned={topic:[*values,topic_query(public,topic)] for topic,values in expected.items()}
    assert sorted(calls)==sorted((values[0],policy(topic).urls_per_search) for topic,values in planned.items())
    assert result['queries_planned'] and result['queries']==planned and result['searches_used']==len(TOPICS)
    assert all(' '.join(filter(None,[company,role])) in values[1] and 'Singapore' not in values[1] for values in planned.values())
    assert set(result['history'])==set(TOPICS)
    assert 'actual\nquestions' in PROMPTS['opportunity_plan'] or 'actual questions' in PROMPTS['opportunity_plan']
    assert 'historical' in PROMPTS['opportunity_plan']


def test_prefetch_stops_at_the_run_search_allowance():
    class AI:
        async def generate(self,request,operation,**kwargs):
            return SimpleNamespace(data=QueryPlan(**{topic:[f'Example Analyst {topic}'] for topic in TOPICS}))
    calls=[]
    class Search:
        async def collect_opportunity_query(self,context,query,max_sources):calls.append(query);return []
    engine=SimpleNamespace(ai=AI(),source=Search(),slots=asyncio.Semaphore(3),settings=SimpleNamespace(timeout_seconds=30,topic_searches=2,run_searches=5))
    result=asyncio.run(prefetch(engine,JobIdentity(is_job_description=True,role='Analyst',company='Example'),'owner','revision'))
    assert len(calls)==5 and result['searches_used']==5 and len(result['history'])==5


def test_early_planner_failure_never_sends_template_queries():
    class AI:
        async def generate(self,*args,**kwargs):raise AIError('provider_configuration')
    class Search:
        async def collect_opportunity_query(self,*args):pytest.fail('No unplanned searches allowed')
    engine=SimpleNamespace(ai=AI(),source=Search(),settings=SimpleNamespace(timeout_seconds=30,topic_searches=2,run_searches=40))
    result=asyncio.run(prefetch(engine,JobIdentity(is_job_description=True,role='Analyst'),'owner','revision'))
    assert not result.get('queries_planned') and not result['history']


def test_query_plan_requires_every_topic_and_bounded_nonempty_wording():
    values={topic:['Example Analyst Singapore relevant query'] for topic in TOPICS}
    for change in ({'compensation':[]},{'conversion_rate':['x'*181]},{'mentorship':['one query','two query','three query']}):
        with pytest.raises(ValidationError):QueryPlan(**{**values,**change})
    with pytest.raises(ValidationError):QueryPlan(**{k:v for k,v in values.items() if k!='conversion_rate'})


def test_v1_reports_stay_readable_but_v2_requires_five_explicit_statuses():
    base=dict(fingerprint='a'*64,opportunity_id=None,status='completed',researched_at=now(),expires_at=now())
    categories={k:CategoryResult(status='completed') for k in LEGACY_FIELDS}
    assert OpportunityReport(schema_version=1,categories=categories,**base).schema_version==1
    with pytest.raises(ValidationError):OpportunityReport(categories=categories,**base)
    assert len(OpportunityReport(categories={k:CategoryResult(status='completed') for k in CATEGORIES},**base).categories)==5


@pytest.mark.parametrize(('text','value','valid'),[
 ('Example interns in the 2025 cohort had a 50% conversion rate.','The 2025 intern conversion rate was 50%.',True),
 ('One Example intern received a return offer in 2025.','The 2025 intern conversion rate was 50%.',False),
 ('Example interns had a 50% conversion rate.','The intern conversion rate was 50%.',True),
 ('Example company revenue grew 50% in 2025.','The intern conversion rate was 75%.',False),
])
def test_conversion_numbers_must_match_but_missing_year_is_not_a_failure(text,value,valid):
    source=ResearchSource(source_id='s',platform='other',url='https://example.test/cohort',evidence=text)
    output=StructuredFindings(findings=[dict(field='conversion_rate',value=value,refs=[0],quotes=[text],confidence='medium',evidence_type='candidate_reported',scope='exact')])
    if valid:assert validate_claims(output,'conversion_outcomes',[source])[0].value==value
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


@pytest.mark.parametrize(('text','value','valid'),[
 ('Example conversion offer in 2025 is SGD 5000 monthly base salary.','The 2025 offer has monthly base pay of SGD 5000.',True),
 ('Example salaries are competitive and generous.','The monthly offer is SGD 5000.',False),
 ('Example conversion pay in 2025 is 5000 monthly, currency unknown.','Monthly pay is 5000 in 2025; currency is unknown.',True),
])
def test_salary_numbers_are_exact_without_forcing_absent_currency(text,value,valid):
    source=ResearchSource(source_id='s',platform='other',url='https://example.test/salary',evidence=text)
    output=StructuredFindings(findings=[dict(field='conversion_salary',value=value,refs=[0],quotes=[text],confidence='medium',evidence_type='candidate_reported',scope='exact')])
    if valid:assert validate_claims(output,'career_progression',[source])[0].value==value
    else:
        with pytest.raises(AIError):validate_claims(output,'career_progression',[source])


def test_topic_query_is_a_plain_employer_role_search_with_a_review_site_second_attempt():
    public={'company':'Optiver','role':'Quantitative Trading Intern','location':'Singapore'}
    assert topic_query(public,'compensation')=='Optiver Quantitative Trading Intern intern salary per month'
    assert topic_query(public,'compensation',1)=='Optiver Quantitative Trading Intern intern salary glassdoor'
    assert topic_query({'company':None,'role':'Data Analyst'},'company_culture')=='Data Analyst company culture reviews'
    assert topic_query({'company':None,'role':''},'benefits') is None and topic_query(None,'benefits') is None
