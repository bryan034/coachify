"""Market/employer/role scope checks for question evidence: the scope model labels market and detail, Python checks the rest.

Only verified passages are saved; other-market sources still inform answers as labelled context."""
import asyncio
import json
from datetime import date
from types import SimpleNamespace as NS

import pytest
from app.ai.context_contracts import ContextPlan
from app.ai.errors import AIError
from app.ai.passage_scope import PassageScopes
from app.ai.qa_contracts import FocusedAnswer
from app.clients.search_sources import SourceAPIs
from app.domain.source_scope import money_figures,target_place,verify
from app.domain.question_memory import cited_money,scope_input,trusted_fact
from app.schemas.analysis import ResearchContext,ResearchSource
from app.workflows.context_chat import semantic_chat
from app.workflows.goal_question import question_queries
from tests.test_goal_chat_presentation import environment

GOAL={'company':'Grab','role':'Software Engineer Intern','field':'Technology','location':'Singapore'}
SG='Grab software engineering intern salary in Singapore is SGD 3,000 per month.'
AU='Grab software engineering intern salary in Sydney is AUD 4,500 per month.'
TARGET=NS(market='target',states_detail=True)


def check(text,url='https://www.glassdoor.sg/salary',goal=GOAL,scope=TARGET,**kwargs):
    return verify(url,kwargs.pop('title',None),text,goal,scope=scope,**kwargs)


def test_target_market_passage_stating_the_detail_is_verified():
    verdict=check(SG)
    assert verdict.verified and not verdict.foreign and verdict.reasons==[]


def test_other_market_label_is_foreign_and_never_verified():
    verdict=check(AU,scope=NS(market='other',states_detail=True))
    assert verdict.foreign and not verdict.verified


@pytest.mark.parametrize('text,scope,reason',[
    ('Software engineering intern salary in Singapore is SGD 3,000 per month.',TARGET,'employer'),
    ('Grab data analyst intern salary in Singapore is SGD 3,000 per month.',TARGET,'role'),
    ('Grab software engineer salary in Singapore is SGD 6,000 per month.',TARGET,'role'),
    ('Grab software engineering interns in Singapore are paid well.',NS(market='target',states_detail=False),'topic'),
    ('Grab software engineering intern salary is $3,000 per month.',NS(market='unknown',states_detail=True),'location'),
])
def test_each_missing_signal_blocks_verification(text,scope,reason):
    verdict=check(text,'https://example.test/x',scope=scope)
    assert not verdict.verified and not verdict.foreign and reason in verdict.reasons


def test_employer_domain_counts_as_official_and_page_title_can_name_the_role():
    verdict=check('Interns in Singapore earn SGD 3,000 per month.','https://www.grab.careers/jobs/1',
                  title='Software Engineer Intern')
    assert verdict.verified and verdict.official


def test_stale_question_terms_and_saved_rechecks():
    assert 'stale' in check(SG,published=date(2020,1,1),today=date(2026,11,19)).reasons
    assert check(SG,published=date(2026,1,1),today=date(2026,11,19)).verified
    housing='Grab software engineering interns in Singapore receive a housing allowance.'
    assert check(housing,terms='intern housing allowance').verified
    assert 'question' in check(housing,terms='relocation flights').reasons
    php='Grab software engineering intern in Singapore uses PHP; salary is SGD 3,000 per month.'
    assert check(php).verified
    assert check(housing,terms='relocation flights',scope=None).verified
    assert not check('Grab data analyst intern salary is SGD 3,000 per month.',scope=None).verified


def test_target_market_defaults_to_singapore_and_follows_other_locations():
    assert target_place({})=='singapore' and target_place({'location':'Hybrid'})=='singapore'
    assert target_place({'location':'London, UK'})=='london'
    reverse={'location':'Sydney, Australia (based in Singapore)','company':'Grab','role':'Analyst'}
    assert target_place(reverse)=='sydney'
    assert question_queries({**reverse,'related_locations':['singapore']},'compensation')[:2]==[
        'Grab Analyst sydney salary compensation benefits',
        'Grab Analyst singapore salary compensation benefits',
    ]
    source=ResearchSource(source_id='a',platform='other',url='https://www.example.co.uk/pay',title='Pay')
    labelled=scope_input('compensation',{**GOAL,'location':'London, UK'},[(source,'Pay is £2,000.')],'intern pay')
    assert labelled['target_market']=='london' and labelled['subject']=='intern pay'
    assert labelled['passages']==[{'ref':0,'source':'example.co.uk','title':'Pay','text':'Pay is £2,000.'}]
    assert scope_input('compensation',GOAL,[])['target_market']=='Singapore'


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


@pytest.mark.parametrize('text,figures',[
    ('S$1,500 a month',{('s$','1500')}),('AUD 4,900',{('aud','4900')}),('4,900 AUD',{('aud','4900')}),
    ('pay SGD1500',{('sgd','1500')}),('HK$20,000',{('hk$','20000')}),('£30k',{('£','30k')}),
    ('2 rounds and SQL questions',set()),
])
def test_money_figures_are_found_by_currency_structure(text,figures):
    assert money_figures(text)==figures


def test_answers_may_state_only_money_figures_their_cited_facts_contain():
    facts=[{'ref':'w1','data':{'value':AU}},{'ref':'w2','data':{'value':SG}}]
    assert cited_money('Sydney pays AUD 4,500 [w1].',['w1'],facts)
    assert not cited_money('Sydney pays AUD 4,900 [w1].',['w1'],facts)
    assert not cited_money('Sydney pays USD 4,500 [w1].',['w1'],facts)
    assert not cited_money('Singapore pays SGD 3,000 [w1].',['w1'],facts)
    assert cited_money('No figure here.',[],facts)


def test_only_job_details_and_exact_findings_are_trusted_facts():
    assert trusted_fact({'kind':'job_details','data':{'value':'Singapore'}})
    assert trusted_fact({'kind':'opportunity_finding','data':{'value':SG,'scope':'exact'}})
    assert not trusted_fact({'kind':'opportunity_finding','data':{'value':AU,'scope':'related_location'}})


def market_of(passage):
    """Synthetic stand-in for the scope model's market judgement."""
    text=f"{passage['title'] or ''} {passage['text']} {passage['source']}"
    if 'Sydney' in text or 'AUD' in text or passage['source'].endswith('.au'):return 'other'
    return 'target' if 'Singapore' in text or passage['source'].endswith('.sg') else 'unknown'


def setup(monkeypatch,batch,*,saved_research=None,reply=None,goal=None,plan=None):
    request,body,*_=environment();body.message='what is the salary';body.conversation=[]
    searches=[];saved=[];contexts=[];labels=[]
    class Store:
        def __init__(self,*args):pass
        def fetch(self,*args):return {**GOAL,**(goal or {})},saved_research or {}
        def save_question(self,owner,row,focus,findings,sources):saved.append((focus,findings,sources))
    async def collect(context,query):
        searches.append(query);return batch
    async def generate(payload,*args,**kwargs):
        if payload.stage=='context_route':
            output=plan or ContextPlan(topic='opportunity',research_focus='compensation',resolved_question=body.message)
        elif payload.stage=='passage_scope':
            labels.append(json.loads(payload.context))
            output=PassageScopes(passages=[{'ref':p['ref'],'market':market_of(p),'states_detail':any(c.isdigit() for c in p['text'])}
                                           for p in labels[-1]['passages']])
        else:
            contexts.append(json.loads(payload.context))
            output=reply(contexts[-1]) if reply else FocusedAnswer(status='not_found',reply='Not found.')
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return NS(data=output)
    monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
    request.app.state.research_client=NS(collect_query=collect);request.app.state.ai=NS(generate=generate)
    return request,body,searches,saved,contexts,labels


def web(identifier,text,url=None):
    return ResearchSource(source_id=identifier,platform='other',url=url or f'https://www.glassdoor.sg/{identifier}',evidence=text)


def cite(prefix,text):
    def reply(context):
        ref=next(f['ref'] for f in context['facts'] if f['ref'].startswith(prefix))
        return FocusedAnswer(reply=f'{text} [{ref}].',references=[ref])
    return reply


def test_mixed_market_results_save_and_answer_only_the_verified_singapore_figure(monkeypatch):
    async def run():
        def reply(context):
            verified=[f for f in context['facts'] if f['data'].get('verified')]
            assert [f['data']['value'] for f in verified]==[SG]
            return FocusedAnswer(reply=f'{SG} [{verified[0]["ref"]}]',references=[verified[0]['ref']])
        request,body,searches,saved,contexts,labels=setup(monkeypatch,[web('au',AU),web('sg',SG)],reply=reply)
        first=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==1 and len(labels)==1 and labels[0]['target_market']=='Singapore'
        assert [p['text'] for p in labels[0]['passages']]==[AU,SG]
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
        request,body,searches,saved,contexts,_=setup(monkeypatch,[web('au',AU,'https://www.seek.com.au/x')],reply=reply)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==1 and saved==[] and len(contexts)==1
        assert 'AUD 4,500' in result.reply and 'seek.com.au/x' in result.reply
    asyncio.run(run())


def test_an_invalid_scope_label_set_never_saves_a_passage(monkeypatch):
    async def run():
        request,body,searches,saved,_,_=setup(monkeypatch,[web('sg',SG)])
        original=request.app.state.ai.generate
        async def generate(payload,*args,**kwargs):
            if payload.stage=='passage_scope':
                output=PassageScopes(passages=[])
                kwargs['validate_output'](output)
            return await original(payload,*args,**kwargs)
        request.app.state.ai.generate=generate
        with pytest.raises(AIError,match='invalid_output'):await semantic_chat(request,'owner',{'workspace':{}},body)
        assert saved==[]
    asyncio.run(run())


def test_verified_saved_fact_answers_without_search(monkeypatch):
    async def run():
        stored={'opportunity_findings':[{'field':'compensation','value':SG,'scope':'exact','source_ids':['sg']}],
                'sources':[{'source_id':'sg','url':'https://www.glassdoor.sg/sg'}]}
        request,body,searches,saved,contexts,labels=setup(monkeypatch,[],saved_research=stored,reply=cite('f',SG))
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert searches==[] and labels==[] and saved==[] and len(contexts)==1
        assert result.reply.startswith(SG)
    asyncio.run(run())


def test_router_selected_saved_condition_answers_the_pay_question(monkeypatch):
    async def run():
        condition={'requirement_id':'pay','category':'other','description':'Monthly allowance of SGD 1,200.','priority':'unspecified'}
        plan=ContextPlan(topic='opportunity',research_focus='compensation',item_refs=['c0'],resolved_question='What is the allowance?')
        request,body,searches,_,contexts,_=setup(monkeypatch,[],goal={'non_skill_requirements':[condition]},plan=plan,
                                                 reply=cite('f','The JD states a monthly allowance of SGD 1,200'))
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert searches==[] and 'SGD 1,200' in result.reply
        assert contexts[0]['facts'][0]['data']=={'value':condition['description']}
    asyncio.run(run())


def test_model_reply_may_quote_another_currency_from_its_source(monkeypatch):
    async def run():
        plan=ContextPlan(topic='opportunity',research_focus='compensation',missing=True,resolved_question='Explain the compensation for this internship')
        request,body,searches,saved,contexts,_=setup(monkeypatch,[web('general',AU)],plan=plan,
                                                     reply=cite('web','The Sydney team reports about AUD 4,500 per month'))
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
        provider=SourceAPIs(None,backend='brave')
        monkeypatch.setattr(provider,'search',search)
        context=ResearchContext(role='Analyst',field='Data',location='Singapore')
        await provider.collect_question_query(context,'Analyst Singapore salary')
        await provider.collect_query(context,'Analyst Singapore interview')
        assert calls==['ALL','SG']
    asyncio.run(run())


def test_router_named_base_office_is_retained_in_provider_query(monkeypatch):
    async def run():
        plan=ContextPlan(topic='opportunity',research_focus='compensation',related_locations=['Sydney'],resolved_question='what is the salary')
        request,body,searches,_,_,_=setup(monkeypatch,[],plan=plan,goal={
            'company':'Long Company '*12,
            'summary':'The employer has headquarters in London. The role is based out of Sydney.',
        })
        await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(searches)==3 and all(len(query)<=128 for query in searches)
        assert 'Singapore' in searches[0]
        assert 'sydney' in searches[1].casefold() and 'london' not in searches[1].casefold()
        assert 'Software Engineer Intern' in searches[1]
    asyncio.run(run())


def test_the_router_sees_the_saved_summary_for_related_locations(monkeypatch):
    async def run():
        seen=[]
        request,body,*_=setup(monkeypatch,[],goal={'summary':'The role is based out of Sydney.'})
        original=request.app.state.ai.generate
        async def generate(payload,*args,**kwargs):
            if payload.stage=='context_route':seen.append(json.loads(payload.context))
            return await original(payload,*args,**kwargs)
        request.app.state.ai.generate=generate
        await semantic_chat(request,'owner',{'workspace':{}},body)
        assert seen[0]['index']['goal']['summary']=='The role is based out of Sydney.'
    asyncio.run(run())


def test_fewer_distinct_queries_stop_cleanly(monkeypatch):
    async def run():
        request,body,searches,_,_,_=setup(monkeypatch,[])
        monkeypatch.setattr('app.workflows.context_chat.question_queries',lambda *args:['one','two'])
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert searches==['one','two']
        assert 'could not verify' in result.reply
    asyncio.run(run())


@pytest.mark.parametrize('figure',['AUD 4,900','USD 4,500'])
def test_unsupported_foreign_figure_retries_and_is_never_rendered(monkeypatch,figure):
    async def run():
        request,body,searches,saved,_,_=setup(monkeypatch,[web('au',AU)],reply=cite('web',f'Sydney pay is {figure} per month'))
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
        request,body,_,saved,_,_=setup(monkeypatch,[source],reply=reply)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert 'AUD 4,500' in result.reply and saved==[]
    asyncio.run(run())
