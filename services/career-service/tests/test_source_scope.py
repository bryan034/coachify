"""Deterministic market/employer/role scope checks for question evidence.

Only verified passages are saved; other-market sources still inform answers as labelled context."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace as NS

import httpx
import pytest
from app.ai.context_contracts import ContextPlan
from app.ai.qa_contracts import FocusedAnswer
from app.clients.deepseek_search import DeepSeekSearch
from app.clients.search_sources import SourceAPIs
from app.domain.source_scope import verify,target_place,related_places
from app.domain.question_memory import market_scoped
from app.schemas.analysis import ResearchContext,ResearchSource
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
    reverse={'location':'Sydney, Australia (based in Singapore)','company':'Grab','role':'Analyst'}
    assert target_place(reverse)=='sydney'
    assert question_queries({**reverse,'related_locations':related_places(reverse)},'compensation')[:2]==[
        'Grab Analyst sydney salary compensation benefits',
        'Grab Analyst singapore salary compensation benefits',
    ]
    london={**GOAL,'location':'London, UK'}
    assert check('Grab software engineering intern salary in London is £2,000 per month.',goal=london).verified
    assert not check(SG,goal=london).verified


def test_general_goal_without_employer_needs_only_market_role_and_topic():
    goal={'role':'Data Analyst','field':'Data'}
    assert check('Data analyst salary in Singapore is SGD 4,000 per month.',goal=goal).verified


def test_queries_anchor_the_listed_market_first_then_search_beyond_it():
    queries=question_queries({'company':'Grab','role':'Software Engineer Intern'},'compensation')
    assert queries==['Grab Software Engineer Intern Singapore salary compensation benefits',
                     'Grab Software Engineer Intern salary compensation benefits',
                     'Grab Software Engineer Intern Singapore salary compensation benefits official careers']
    saved=question_queries({'company':'Grab','role':'Analyst','location':'Singapore'},'location')
    assert saved[0].casefold().count('singapore')==1 and 'singapore' not in saved[1].casefold()


def test_overseas_base_named_by_the_goal_is_searched():
    goal={'company':'Grab','role':'Analyst','location':'Singapore','related_locations':['sydney']}
    assert question_queries(goal,'compensation')[1]=='Grab Analyst sydney salary compensation benefits'
    assert related_places({'location':'Singapore (based in Sydney)'})==['sydney']
    assert related_places({'location':'Singapore'},['This role sits with our Kuala Lumpur hub.','Remote'])==['kuala lumpur']
    assert related_places({'location':'London, UK'})==[]
    assert related_places({'location':'London'},['Paris headquarters. This role is based in Singapore.'])==['singapore','paris']


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


def setup(monkeypatch,batch,*,saved_research=None,reply=None,goal=None):
    request,body,*_=environment();body.message='what is the salary';body.conversation=[]
    searches=[];saved=[];contexts=[]
    class Store:
        def __init__(self,*args):pass
        def fetch(self,*args):return {**GOAL,**(goal or {})},saved_research or {}
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


def test_other_market_results_reach_the_model_as_labelled_context_but_are_never_saved(monkeypatch):
    async def run():
        def reply(context):
            [fact]=[f for f in context['facts'] if f['ref'].startswith('web')]
            assert fact['data']['scope']=='related_location' and fact['data']['verified'] is False
            return FocusedAnswer(reply=f'Reported pay in Sydney is AUD 4,500 per month, unverified for Singapore [{fact["ref"]}].',references=[fact['ref']])
        request,body,searches,saved,contexts=setup(monkeypatch,[web('au',AU,'https://www.seek.com.au/x')],reply=reply)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==1 and saved==[] and len(contexts)==1
        assert 'AUD 4,500' in result.reply and 'seek.com.au/x' in result.reply
    asyncio.run(run())


def test_saved_foreign_finding_is_context_not_a_trusted_fact():
    fact={'ref':'f1','kind':'opportunity_finding','data':{'value':AU,'scope':'exact'}}
    assert market_scoped(fact,GOAL)['data']['scope']=='related_location'
    assert market_scoped({**fact,'data':{'value':SG,'scope':'exact'}},GOAL)['data']['scope']=='exact'


def test_verified_saved_fact_answers_without_model_or_search(monkeypatch):
    async def run():
        stored={'opportunity_findings':[{'field':'compensation','value':SG,'scope':'exact','source_ids':['sg']}],
                'sources':[{'source_id':'sg','url':'https://www.glassdoor.sg/sg'}]}
        request,body,searches,saved,contexts=setup(monkeypatch,[],saved_research=stored)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert searches==[] and contexts==[] and saved==[]
        assert result.reply.startswith(SG) and '### ' not in result.reply
    asyncio.run(run())


def test_model_reply_may_quote_another_currency_from_its_source(monkeypatch):
    async def run():
        def reply(context):
            ref=next(f['ref'] for f in context['facts'] if f['ref'].startswith('web'))
            return FocusedAnswer(reply=f'The Sydney team reports about AUD 4,500 per month [{ref}].',references=[ref])
        request,body,searches,saved,contexts=setup(monkeypatch,[web('general',AU)],reply=reply)
        body.message='Explain the compensation for this internship'
        original=request.app.state.ai.generate
        async def generate(payload,*args,**kwargs):
            if payload.stage=='context_route':
                return NS(data=ContextPlan(topic='opportunity',research_focus='compensation',missing=True,resolved_question=body.message))
            return await original(payload,*args,**kwargs)
        request.app.state.ai.generate=generate
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert 'AUD 4,500' in result.reply and len(searches)==1 and saved==[]
    asyncio.run(run())


@pytest.mark.parametrize('url', ['https://grabber.sg/jobs', 'https://grab.example.sg/jobs'])
def test_lookalike_employer_hosts_do_not_verify_unattributed_salary(url):
    verdict=check('Software engineering intern salary in Singapore is SGD 3,000 per month.',url)
    assert not verdict.verified and not verdict.official and 'employer' in verdict.reasons


def test_long_goal_identity_keeps_market_in_anchored_queries():
    queries=question_queries({'company':'Long Company '*12,'role':'Software Engineer Intern'},'compensation')
    assert 'Singapore' in queries[0] and 'Singapore' in queries[2]


def test_chat_search_preserves_interview_provider_scope(monkeypatch):
    async def run():
        calls=[]
        async def search(query,**options):calls.append(options['country'])
        provider=SourceAPIs(None)
        monkeypatch.setattr(provider,'search',search)
        context=ResearchContext(role='Analyst',field='Data',location='Singapore')
        await provider.collect_question_query(context,'Analyst Singapore salary')
        await provider.collect_query(context,'Analyst Singapore interview')
        assert calls==['ALL','SG']
    asyncio.run(run())


def test_saved_summary_base_office_is_retained_in_provider_query(monkeypatch):
    async def run():
        request,body,searches,_,_=setup(monkeypatch,[],goal={
            'company':'Long Company '*12,
            'summary':'The employer has headquarters in London. The role is based out of Sydney.',
        })
        await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==3 and all(len(query)<=128 for query in searches)
        assert 'Singapore' in searches[0]
        assert 'sydney' in searches[1].casefold() and 'london' not in searches[1].casefold()
        assert 'Software Engineer Intern' in searches[1]
    asyncio.run(run())


def test_fewer_distinct_queries_stop_cleanly(monkeypatch):
    async def run():
        request,body,searches,_,_=setup(monkeypatch,[])
        monkeypatch.setattr('app.workflows.context_chat.question_queries',lambda *args:['one','two'])
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert searches==['one','two']
        assert 'could not verify' in result.reply
    asyncio.run(run())


def test_saved_source_market_prevents_direct_job_fact_reply(monkeypatch):
    async def run():
        research={'opportunity_findings':[{'field':'compensation','value':'Paid $4,500 monthly.',
                                         'scope':'exact','source_ids':['sydney']}],
                  'sources':[{'source_id':'sydney','url':'https://www.seek.com.au/old','title':'Sydney salary'}]}
        request,body,searches,_,_=setup(monkeypatch,[web('sg',SG)],saved_research=research)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==1 and SG in result.reply and '$4,500' not in result.reply
    asyncio.run(run())


@pytest.mark.parametrize('figure',['AUD 4,900','USD 4,500'])
def test_unsupported_foreign_figure_retries_and_is_never_rendered(monkeypatch,figure):
    async def run():
        def reply(context):
            ref=next(f['ref'] for f in context['facts'] if f['ref'].startswith('web'))
            return FocusedAnswer(reply=f'Sydney pay is {figure} per month [{ref}].',references=[ref])
        request,body,searches,saved,_=setup(monkeypatch,[web('au',AU)],reply=reply)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==3 and saved==[]
        assert figure not in result.reply and 'could not verify' in result.reply
    asyncio.run(run())


def test_other_market_pay_table_retains_title_context(monkeypatch):
    async def run():
        def reply(context):
            fact=next(f for f in context['facts'] if f['ref'].startswith('web'))
            assert fact['data']['scope']=='related_location'
            assert fact['data']['source_titles']==['Grab Software Engineer Intern pay in Sydney']
            return FocusedAnswer(reply=f'Sydney pay is reported as AUD 4,500 per month [{fact["ref"]}].',
                                 references=[fact['ref']])
        source=web('au','AUD 4,500 per month.').model_copy(
            update={'title':'Grab Software Engineer Intern pay in Sydney'})
        request,body,_,saved,_=setup(monkeypatch,[source],reply=reply)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert 'AUD 4,500' in result.reply and saved==[]
    asyncio.run(run())
