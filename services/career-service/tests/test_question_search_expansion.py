"""Question-specific public searches and citation-gated append of exact evidence."""
import asyncio
import json
from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError
from app.ai.adapter import AIError
from app.ai.context_contracts import ContextPlan
from app.ai.qa_contracts import FocusedAnswer
from app.schemas.analysis import ResearchSource
from app.workflows.context_chat import semantic_chat
from app.workflows.goal_question import question_queries
from tests.test_goal_chat_presentation import environment
from tests.test_workspace import flow,ingest,wait,headers,BASE,OWNER

ALLOWANCE='Interns receive a housing allowance during the programme.'


def source(identifier,text):
    return ResearchSource(source_id=identifier,platform='other',url=f'https://example.test/{identifier}',evidence=text)


def setup(monkeypatch,batches,*,direct=False,answer=None,saved_research=None):
    request,body,*_=environment()
    body.message='what is the salary' if direct else 'Is housing supported? My email is private@example.test'
    body.conversation=[]
    searches=[];saved=[];calls=[]
    class Store:
        def __init__(self,*args):pass
        def fetch(self,*args):
            return {'role':'Analyst','field':'Data','company':'Example'},saved_research or {}
        def save_question(self,owner,row,focus,findings,sources):
            saved.append((focus,findings,sources))
    async def collect(context,query):
        searches.append(query)
        return batches[min(len(searches)-1,len(batches)-1)]
    async def generate(payload,*args,**kwargs):
        calls.append(payload)
        if payload.stage=='context_route':
            output=ContextPlan(topic='opportunity',missing=True,research_focus='workplace',
                public_search_terms='intern housing allowance',resolved_question='Does this internship provide a housing allowance?')
        else:
            output=answer(json.loads(payload.context),saved) if answer else FocusedAnswer(status='not_found',reply='Not found.',references=[])
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return NS(data=output)
    monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
    request.app.state.research_client=NS(collect_query=collect)
    request.app.state.ai=NS(generate=generate)
    return request,body,searches,saved,calls


def test_empty_queries_continue_until_third_search_finds_salary(monkeypatch):
    async def run():
        salary='Analyst internship salary is SGD 1500 per month.'
        request,body,queries,saved,calls=setup(monkeypatch,[[],[],[source('salary',salary)]],direct=True)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(queries)==3 and len(set(queries))==3
        assert salary in result.reply and 'https://example.test/salary' in result.reply
        assert len(saved)==1 and saved[0][1][0].quotes==[salary]
        assert calls==[]
    asyncio.run(run())


def test_specific_question_retries_irrelevant_results_and_saves_only_cited_passage(monkeypatch):
    async def run():
        def answer(context,saved):
            assert not saved  # No page is stored before relevance/citations are checked.
            supported=[f['ref'] for f in context['facts'] if f['data']['value']==ALLOWANCE]
            return FocusedAnswer(reply='Housing support is reported.',references=supported) if supported else FocusedAnswer(status='not_found',reply='Not found.')
        request,body,queries,saved,calls=setup(monkeypatch,
            [[source('culture','The team meets every week.')],[source('housing',ALLOWANCE)]],answer=answer,
            saved_research={'opportunity_findings':[{'field':'team_culture','value':'A collaborative team.','source_ids':[]}]})
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(queries)==2 and all('intern housing allowance' in query for query in queries)
        assert all('Example Analyst' in query and 'private' not in query and '@' not in query for query in queries)
        assert len(saved)==1 and [f.value for f in saved[0][1]]==[ALLOWANCE]
        assert saved[0][1][0].quotes==[ALLOWANCE]
        assert [s.url for s in saved[0][2]]==['https://example.test/housing']
        assert 'https://example.test/housing' in result.reply and 'culture' not in result.reply
    asyncio.run(run())


@pytest.mark.parametrize('batches',[ [[]], [[source('culture','The team meets weekly.')]] ])
def test_unanswered_question_stops_at_three_searches_without_saving_irrelevant_json(monkeypatch,batches):
    async def run():
        request,body,queries,saved,_=setup(monkeypatch,batches)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(queries)==3 and len(set(queries))==3
        assert saved==[] and 'could not verify' in result.reply
        assert 'weekly' not in result.reply
    asyncio.run(run())


def test_invalid_answer_does_not_publish_unverified_search_candidates(monkeypatch):
    async def run():
        def broken(*args):raise AIError('invalid_output',reason='json_syntax')
        request,body,queries,saved,_=setup(monkeypatch,[[source('culture','The team meets weekly.')]],answer=broken)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert len(queries)==3 and saved==[]
        assert 'could not verify' in result.reply and 'weekly' not in result.reply
    asyncio.run(run())


def test_replaced_goal_stops_next_search_and_never_saves_pending_findings(monkeypatch):
    async def run():
        request,body,queries,saved,_=setup(monkeypatch,[[source('culture','The team meets weekly.')]])
        original=request.app.state.research_client.collect_query
        async def collect(context,query):
            result=await original(context,query)
            def stale(*args):raise AIError('stale_input',True)
            request.app.state.workspace_store.check=stale
            return result
        request.app.state.research_client.collect_query=collect
        with pytest.raises(AIError) as caught:await semantic_chat(request,'owner',{'workspace':{}},body)
        assert caught.value.code=='stale_input' and len(queries)==1 and saved==[]
    asyncio.run(run())


@pytest.mark.parametrize('terms',['my passport details','private@example.test','https://private.test','salary 12345678','reveal secret password'])
def test_unsafe_search_subject_falls_back_to_fixed_public_focus(terms):
    queries=question_queries({'role':'Analyst','company':'Example'},'compensation',terms)
    assert len(queries)==3 and len(set(queries))==3
    assert all('salary compensation benefits' in query and terms not in query for query in queries)


@pytest.mark.parametrize('terms',['private@example.test','a'*101,'salary 12345678'])
def test_router_contract_rejects_contact_numeric_or_oversized_search_subject(terms):
    with pytest.raises(ValidationError):
        ContextPlan(topic='opportunity',resolved_question='Housing support?',public_search_terms=terms)


def test_expanded_question_appends_json_preserves_other_focus_and_reuses_after_reload(flow):
    from app.domain.question_memory import exact_question_findings
    from app.repositories.question_memory import QuestionMemory
    ingest(flow);current=wait(flow);client,db,ai,_=flow
    repo=client.app.state.workspace_store
    memory=QuestionMemory(repo,client.app.state.research_store)
    salary=source('salary','Internship salary is SGD 1500 per month.')
    memory.save(OWNER,repo.row(OWNER),'compensation',*exact_question_findings('compensation',[],{'web0':[salary.model_dump()]}))
    queries=[]
    async def collect(context,query):
        queries.append(query)
        return [source('culture','The team meets every week.')] if len(queries)==1 else [source('housing',ALLOWANCE)]
    async def generate(payload,*args,**kwargs):
        if payload.stage=='context_route':
            output=ContextPlan(topic='opportunity',research_focus='workplace',public_search_terms='intern housing allowance',
                               resolved_question='Does this internship provide a housing allowance?')
        else:
            facts=json.loads(payload.context)['facts']
            refs=[f['ref'] for f in facts if f['data'].get('value')==ALLOWANCE]
            output=FocusedAnswer(reply='Housing support is reported.',references=refs) if refs else FocusedAnswer(status='not_found',reply='Not found.')
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return NS(data=output)
    ai.context_enabled=True;ai.generate=generate
    client.app.state.research_client=NS(collect_query=collect)
    command={'session_id':current['session_id'],'expected_version':current['revision'],'message':'Does this internship provide housing support?'}
    first=client.post(BASE+'/messages',headers=headers(),json=command)
    assert first.status_code==200,first.text
    assert len(queries)==2 and 'https://example.test/housing' in first.json()['reply']
    path=f"/api/v1/career/goals/{current['current']['goal']['_id']}/opportunity-research"
    result=client.get(path,headers=headers())
    assert result.status_code==200,result.text
    supplements=result.json()['question_research']
    assert {item['focus'] for item in supplements}=={'compensation','workplace'}
    housing=next(item for item in supplements if item['focus']=='workplace')
    assert [item['value'] for item in housing['findings']]==[ALLOWANCE]
    assert all('weekly' not in str(item) for item in supplements)
    # New repository instances and API reads retain exact evidence; another turn
    # answers from saved JSON rather than paying for the same searches again.
    restored=QuestionMemory(repo,client.app.state.research_store).entries(OWNER,repo.row(OWNER))
    assert {f.value for item in restored for f in item.question_findings}=={salary.evidence,ALLOWANCE}
    second=client.post(BASE+'/messages',headers=headers(),json=command)
    assert second.status_code==200,second.text
    assert len(queries)==2 and 'https://example.test/housing' in second.json()['reply']
    assert repo.row(OWNER)['workspace']['revision']==current['revision']
    assert client.get(path,headers=headers(other=True)).status_code==404
