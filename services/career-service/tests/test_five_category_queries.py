"""Role-tailored initial plans, five intents, compatibility and numeric provenance."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from app.ai.errors import AIError
from app.ai.jd_scope import JobIdentity
from app.ai.opportunity_contracts import QueryPlan,StructuredFindings,PROMPTS
from app.repositories.goals import now
from app.schemas.analysis import ResearchSource
from app.schemas.opportunity import CATEGORIES,CategoryResult,OpportunityReport
from app.workflows.jd_prefetch import prefetch
from app.workflows.opportunity.domain import validate_claims
from app.workflows.opportunity.queries import topic_queries
from app.workflows.opportunity.topics import GROUP_CANDIDATES,GROUPS,TOPIC_GROUP,TOPICS,group_query,topic_query
from tests.test_opportunity import opportunity_flow

@pytest.mark.parametrize('company',['Example',None])
@pytest.mark.parametrize(('role','field','terms'),[
 ('Investment Banking Summer Analyst','Finance','valuation accounting deal exposure'),
 ('Software Engineering Intern','Software Engineering','coding algorithms API projects'),
])
def test_model_writes_every_group_query_before_search(role,field,terms,company):
    calls=[];plans=[]
    identity=JobIdentity(is_job_description=True,role=role,field=field,company=company,location='Singapore',employment_type='internship',evidence=['Synthetic JD'])
    expected={group:f'Example {role} Singapore {group} {terms}' for group in GROUPS}
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
    assert sorted(calls)==sorted((query,GROUP_CANDIDATES) for query in expected.values())
    assert result['queries_planned'] and result['group_queries']==expected and result['searches_used']==len(GROUPS)
    assert result['queries']==topic_queries(public,2) and set(result['queries'])==set(TOPICS)
    assert all(' '.join(filter(None,[company,role])) in query and 'Singapore' not in query for values in result['queries'].values() for query in values)
    assert set(result['group_history'])==set(GROUPS) and set(result['evidence'])==set(TOPICS)
    assert 'actual\nquestions' in PROMPTS['opportunity_plan'] or 'actual questions' in PROMPTS['opportunity_plan']
    assert 'historical' in PROMPTS['opportunity_plan']


def test_prefetch_stops_at_the_run_search_allowance():
    class AI:
        async def generate(self,request,operation,**kwargs):
            return SimpleNamespace(data=QueryPlan(**{group:f'Example Analyst {group}' for group in GROUPS}))
    calls=[]
    class Search:
        async def collect_opportunity_query(self,context,query,max_sources):calls.append(query);return []
    engine=SimpleNamespace(ai=AI(),source=Search(),slots=asyncio.Semaphore(3),settings=SimpleNamespace(timeout_seconds=30,topic_searches=2,run_searches=5))
    result=asyncio.run(prefetch(engine,JobIdentity(is_job_description=True,role='Analyst',company='Example'),'owner','revision'))
    assert len(calls)==5 and result['searches_used']==5 and len(result['group_history'])==5


def test_early_planner_failure_never_sends_template_queries():
    class AI:
        async def generate(self,*args,**kwargs):raise AIError('provider_configuration')
    class Search:
        async def collect_opportunity_query(self,*args):pytest.fail('No unplanned searches allowed')
    engine=SimpleNamespace(ai=AI(),source=Search(),settings=SimpleNamespace(timeout_seconds=30,topic_searches=2,run_searches=40))
    result=asyncio.run(prefetch(engine,JobIdentity(is_job_description=True,role='Analyst'),'owner','revision'))
    assert not result.get('queries_planned') and not result['group_history']


def test_query_plan_requires_one_bounded_query_per_group():
    values={group:'Example Analyst Singapore relevant query' for group in GROUPS}
    assert QueryPlan(**values)
    for change in ({'pay':''},{'conversion':'x'*181},{'culture':['one query','two query']}):
        with pytest.raises(ValidationError):QueryPlan(**{**values,**change})
    with pytest.raises(ValidationError):QueryPlan(**{k:v for k,v in values.items() if k!='conversion'})


def test_every_topic_is_searched_by_exactly_one_group():
    assert sorted(t for topics in GROUPS.values() for t in topics)==sorted(TOPICS)
    assert all(topic in GROUPS[TOPIC_GROUP[topic]] for topic in TOPICS)


def test_group_query_is_a_plain_employer_role_search():
    public={'company':'Optiver','role':'Quantitative Trading Intern'}
    assert group_query(public,'pay')=='Optiver Quantitative Trading Intern intern salary benefits graduate pay'
    assert group_query({'company':None,'role':''},'pay') is None and group_query(None,'pay') is None
    assert len({group_query(public,g) for g in GROUPS})==len(GROUPS)
    assert not {group_query(public,g) for g in GROUPS}&{topic_query(public,t,a) for t in TOPICS for a in (0,1)}


def test_reports_require_five_explicit_statuses():
    base=dict(fingerprint='a'*64,opportunity_id=None,status='completed',researched_at=now(),expires_at=now())
    categories={k:CategoryResult(status='completed') for k in ('interview_intelligence','internship_insights','company_intelligence')}
    with pytest.raises(ValidationError):OpportunityReport(categories=categories,**base)
    with pytest.raises(ValidationError):OpportunityReport(schema_version=1,categories={k:CategoryResult(status='completed') for k in CATEGORIES},**base)
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
