"""Deterministic Singapore/employer/role scope checks for question evidence."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace as NS

import httpx
import pytest
from app.ai.context_contracts import ContextPlan
from app.ai.qa_contracts import FocusedAnswer
from app.clients.deepseek_search import DeepSeekSearch
from app.domain.source_scope import verify,target_place
from app.schemas.analysis import ResearchSource
from app.workflows.context_chat import semantic_chat
from app.workflows.goal_question import question_queries
from tests.test_goal_chat_presentation import environment

GOAL={'company':'Grab','role':'Software Engineer Intern','field':'Technology','location':'Singapore'}
SG='Grab software engineering intern salary in Singapore is SGD 3,000 per month.'
AU='Grab software engineering intern salary in Sydney is AUD 4,500 per month.'


def check(text,url='https://www.glassdoor.sg/salary',goal=GOAL,focus='compensation',**kwargs):
    return verify(focus,url,kwargs.pop('title',None),text,goal,**kwargs)


def test_singapore_employer_role_salary_is_verified():
    verdict=check(SG)
    assert verdict.verified and not verdict.foreign and verdict.reasons==[]


@pytest.mark.parametrize('text,url',[
    (AU,'https://www.glassdoor.sg/salary'),
    ('Grab software engineer intern pay is A$30 per hour.','https://www.glassdoor.sg/salary'),
    ('Grab software engineer intern salary is $3,000 per month.','https://www.seek.com.au/grab'),
    ('Grab software engineer intern salary is $3,000 per month.','https://au.indeed.com/grab'),
    ('Grab software engineer intern salary in Kuala Lumpur is RM 2500 per month.','https://example.test/x'),
    ('Grab software engineer intern salary is £2,000 per month in Singapore.','https://example.test/x'),
])
def test_other_markets_are_rejected_as_foreign(text,url):
    verdict=check(text,url)
    assert verdict.foreign and not verdict.verified


@pytest.mark.parametrize('text,reason',[
    ('Software engineering intern salary in Singapore is SGD 3,000 per month.','employer'),
    ('Grab data analyst intern salary in Singapore is SGD 3,000 per month.','role'),
    ('Grab software engineer salary in Singapore is SGD 6,000 per month.','role'),
    ('Grab software engineering interns in Singapore are paid well.','topic'),
    ('Grab software engineering intern salary is $3,000 per month.','location'),
])
def test_each_missing_signal_blocks_verification(text,reason):
    verdict=check(text,'https://example.test/x')
    assert not verdict.verified and not verdict.foreign and reason in verdict.reasons


def test_employer_domain_counts_as_official_and_page_title_can_name_the_role():
    verdict=check('Interns in Singapore earn SGD 3,000 per month.','https://www.grab.careers/jobs/1',
                  title='Software Engineer Intern')
    assert verdict.verified and verdict.official


def test_stale_question_terms_and_programming_languages():
    assert 'stale' in check(SG,published=date(2020,1,1),today=date(2026,11,19)).reasons
    assert check(SG,published=date(2026,1,1),today=date(2026,11,19)).verified
    housing='Grab software engineering interns in Singapore receive a housing allowance.'
    assert check(housing,focus='workplace',terms='intern housing allowance').verified
    assert 'question' in check(housing,focus='workplace',terms='relocation flights').reasons
    php='Grab software engineering intern in Singapore uses PHP; salary is SGD 3,000 per month.'
    assert check(php).verified
    # The store's re-check covers scope only; question relevance is decided at retrieval.
    assert check(housing,focus='workplace',terms='relocation flights',scope_only=True).verified
    assert not check(AU,scope_only=True).verified


def test_target_market_defaults_to_singapore_and_follows_other_locations():
    assert target_place({})=='singapore' and target_place({'location':'Hybrid'})=='singapore'
    assert target_place({'location':'London, UK'})=='london'
    london={**GOAL,'location':'London, UK'}
    assert check('Grab software engineering intern salary in London is £2,000 per month.',goal=london).verified
    assert not check(SG,goal=london).verified


def test_general_goal_without_employer_needs_only_market_role_and_topic():
    goal={'role':'Data Analyst','field':'Data'}
    assert check('Data analyst salary in Singapore is SGD 4,000 per month.',goal=goal).verified


def test_queries_always_anchor_singapore_and_narrow_rather_than_broaden():
    queries=question_queries({'company':'Grab','role':'Software Engineer Intern'},'compensation')
    assert len(queries)==3 and all(q.startswith('Grab Software Engineer Intern Singapore') for q in queries)
    assert 'candidate reports' not in ' '.join(queries) and 'SGD per month' in queries[2]
    saved=question_queries({'company':'Grab','role':'Analyst','location':'Singapore'},'location')
    assert all(q.casefold().count('singapore')==1 for q in saved)


def test_deepseek_truncation_keeps_singapore_anchor():
    async def run():
        calls=[]
        def handler(request):calls.append(request);return httpx.Response(200,json={'results':[]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await DeepSeekSearch(client,api_key='synthetic').search(
                'Very Long Employer Name Holdings '*2+'Senior Software Engineering Intern Singapore salary compensation benefits SGD per month')
        query=json.loads(calls[0].content)['query']
        assert len(query)<=128 and 'Singapore' in query and query.endswith('SGD per month')
    asyncio.run(run())


def setup(monkeypatch,batch,*,saved_research=None,reply=None):
    request,body,*_=environment();body.message='what is the salary';body.conversation=[]
    searches=[];saved=[];contexts=[]
    class Store:
        def __init__(self,*args):pass
        def fetch(self,*args):return dict(GOAL),saved_research or {}
        def save_question(self,owner,row,focus,findings,sources):saved.append((focus,findings,sources))
    async def collect(context,query):
        searches.append(query);return batch
    async def generate(payload,*args,**kwargs):
        contexts.append(json.loads(payload.context))
        output=reply(contexts[-1]) if reply else FocusedAnswer(status='not_found',reply='Not found.')
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return NS(data=output)
    monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
    request.app.state.research_client=NS(collect_query=collect);request.app.state.ai=NS(generate=generate)
    return request,body,searches,saved,contexts


def web(identifier,text,url=None):
    return ResearchSource(source_id=identifier,platform='other',url=url or f'https://www.glassdoor.sg/{identifier}',evidence=text)


def test_mixed_market_results_save_and_answer_only_the_verified_singapore_figure(monkeypatch):
    async def run():
        request,body,searches,saved,contexts=setup(monkeypatch,[web('au',AU),web('sg',SG)])
        first=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==1 and contexts==[]
        assert SG in first.reply and 'AUD' not in first.reply and 'glassdoor.sg/sg' in first.reply
        [(focus,findings,sources)]=saved
        assert focus=='compensation' and [f.value for f in findings]==[SG]
        assert findings[0].scope=='exact' and [s.url for s in sources]==['https://www.glassdoor.sg/sg']
    asyncio.run(run())


def test_foreign_only_results_never_reach_the_model_or_the_database(monkeypatch):
    async def run():
        request,body,searches,saved,contexts=setup(monkeypatch,[web('au',AU,'https://www.seek.com.au/x')])
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==3 and saved==[] and contexts==[]
        assert 'AUD' not in result.reply and 'could not verify' in result.reply
    asyncio.run(run())


def test_saved_foreign_finding_is_ignored_and_triggers_a_search(monkeypatch):
    async def run():
        poisoned={'opportunity_findings':[{'field':'compensation','value':AU,'scope':'exact','source_ids':['old']}],
                  'sources':[{'source_id':'old','url':'https://www.seek.com.au/old'}]}
        request,body,searches,saved,_=setup(monkeypatch,[web('sg',SG)],saved_research=poisoned)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==1 and SG in result.reply and 'AUD' not in result.reply
    asyncio.run(run())


def test_verified_saved_fact_answers_without_model_or_search(monkeypatch):
    async def run():
        stored={'opportunity_findings':[{'field':'compensation','value':SG,'scope':'exact','source_ids':['sg']}],
                'sources':[{'source_id':'sg','url':'https://www.glassdoor.sg/sg'}]}
        request,body,searches,saved,contexts=setup(monkeypatch,[],saved_research=stored)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert searches==[] and contexts==[] and saved==[]
        assert result.reply.startswith(SG) and '### ' not in result.reply
    asyncio.run(run())


def test_model_reply_quoting_a_foreign_currency_is_rejected(monkeypatch):
    async def run():
        unverified='Software engineering intern salary in Singapore is SGD 2,800 per month.'
        def reply(context):
            ref=next(f['ref'] for f in context['facts'] if f['ref'].startswith('web'))
            assert all(f['data']['verified'] is False for f in context['facts'] if f['ref'].startswith('web'))
            return FocusedAnswer(reply=f'Interns earn about AUD 4,500 per month [{ref}].',references=[ref])
        request,body,searches,saved,contexts=setup(monkeypatch,[web('general',unverified)],reply=reply)
        body.message='Explain the compensation for this internship'
        original=request.app.state.ai.generate
        async def generate(payload,*args,**kwargs):
            if payload.stage=='context_route':
                return NS(data=ContextPlan(topic='opportunity',research_focus='compensation',missing=True,resolved_question=body.message))
            return await original(payload,*args,**kwargs)
        request.app.state.ai.generate=generate
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        # Each AUD reply fails validation; the workflow retries the bounded searches
        # and then reports the detail as unverified rather than publishing it.
        assert 'AUD' not in result.reply and 'could not verify' in result.reply
        assert len(searches)==3 and saved==[]
    asyncio.run(run())


@pytest.mark.parametrize('url', ['https://grabber.sg/jobs', 'https://grab.example.sg/jobs'])
def test_lookalike_employer_hosts_do_not_verify_unattributed_salary(url):
    verdict=check('Software engineering intern salary in Singapore is SGD 3,000 per month.',url)
    assert not verdict.verified and not verdict.official and 'employer' in verdict.reasons


def test_long_goal_identity_keeps_market_in_every_query():
    queries=question_queries({'company':'Long Company '*20,'role':'Software Engineer Intern'},'compensation')
    assert all('Singapore' in query for query in queries)
