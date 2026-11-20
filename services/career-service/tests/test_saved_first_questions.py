"""Saved-first graph, exact follow-up evidence and durable owner/version isolation."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS
import pytest
from app.ai.errors import AIError
from app.ai.context_contracts import ContextPlan
from app.ai.passage_scope import PassageScopes
from app.ai.qa_contracts import FocusedAnswer
from app.ai.routing import ModelRouter
from app.domain.question_memory import question_passages,scoped_question_findings
from app.repositories.question_memory import QuestionMemory
from app.repositories.questions import QuestionStore
from app.schemas.analysis import ResearchSource
from app.workflows.context_chat import semantic_chat
from tests.test_goal_chat_presentation import environment
from tests.test_workspace import flow,ingest,wait,headers,BASE,OWNER,OTHER

SALARY='Synthetic Example Data Analyst salary in Singapore is SGD 1500 per month.'
SALARY_PLAN=ContextPlan(topic='opportunity',research_focus='compensation',resolved_question='what is the salary')


def context_stages(plan=SALARY_PLAN,*,answer=None,market='target',fallback=None):
    """Synthetic routing, passage-scope and answer stages; answer=None returns malformed answer JSON."""
    async def generate(payload,*args,**kwargs):
        if payload.stage=='context_route':output=plan
        elif payload.stage=='passage_scope':
            passages=json.loads(payload.context)['passages']
            output=PassageScopes(passages=[{'ref':p['ref'],'market':market,'states_detail':True} for p in passages])
        elif payload.stage in ('context_answer','focused_answer'):
            if answer is None:raise AIError('invalid_output',True,reason='json_syntax')
            output=answer(json.loads(payload.context))
        else:return await fallback(payload,*args,**kwargs)
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return NS(data=output,generation=None)
    return generate


def cite_salary(context):
    fact=next(f for f in context['facts'] if SALARY in str(f['data'].get('value')))
    return FocusedAnswer(reply=f'{SALARY} [{fact["ref"]}]',references=[fact['ref']])


def test_saved_salary_needs_no_search_and_survives_malformed_answer_json(monkeypatch):
    async def run():
        request,body,*_=environment();body.message='what is the salary';body.conversation=[]
        async def forbidden(*args,**kwargs):pytest.fail('Saved salary must not search.')
        request.app.state.ai=NS(generate=context_stages());request.app.state.research_client=NS(collect_query=forbidden)
        class Store:
            def __init__(self,*args):pass
            def fetch(self,*args):return {'role':'Analyst','field':'Data'},{'intelligence':{'categories':{'internship_insights':{'findings':[
                {'field':'compensation','value':SALARY,'scope':'exact','source_ids':['salary']}]}}},
                'sources':[{'source_id':'salary','url':'https://example.test/salary'}]}
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert SALARY in result.reply and '[Source](<https://example.test/salary>)' in result.reply
    asyncio.run(run())


def test_missing_salary_searches_once_saves_exact_evidence_and_reuses_it_next_turn(monkeypatch):
    async def run():
        request,body,*_=environment();body.message='what is the salary';body.conversation=[]
        saved=[];searches=[]
        class Store:
            def __init__(self,*args):pass
            def fetch(self,*args):return {'role':'Analyst','field':'Data','company':'Synthetic Example'},{
                'opportunity_findings':[f.model_dump() for f,s in saved],
                'sources':[s.model_dump() for f,s in saved]}
            def save_question(self,owner,row,focus,findings,sources):
                assert focus=='compensation'
                saved.extend((finding,sources[0]) for finding in findings)
        async def collect(context,query):
            searches.append(query)
            return [ResearchSource(source_id='salary',platform='other',url='https://example.test/salary',evidence=SALARY)]
        request.app.state.ai=NS(generate=context_stages());request.app.state.research_client=NS(collect_query=collect)
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
        first=await semantic_chat(request,'owner',{'workspace':{}},body)
        second=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert SALARY in first.reply and SALARY in second.reply
        assert len(searches)==1 and len(saved)==1
        assert saved[0][0].quotes==[SALARY] and saved[0][0].value==SALARY
        assert saved[0][0].scope=='exact' and '[Source](<https://example.test/salary>)' in first.reply
    asyncio.run(run())


def test_empty_search_does_not_save_or_invent_a_salary(monkeypatch):
    async def run():
        request,body,*_=environment();body.message='what is the salary';body.conversation=[]
        class Store:
            def __init__(self,*args):pass
            def fetch(self,*args):return {'role':'Analyst','field':'Data'},{}
            def save_question(self,*args):pytest.fail('Empty evidence must not be saved as an answer.')
        async def collect(*args):return []
        request.app.state.ai=NS(generate=context_stages(answer=lambda context:FocusedAnswer(status='not_found',reply='Not found.')))
        request.app.state.research_client=NS(collect_query=collect)
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
        reply=(await semantic_chat(request,'owner',{'workspace':{}},body)).reply
        assert 'could not verify' in reply and 'SGD' not in reply
    asyncio.run(run())


def test_complex_question_with_broken_answer_json_uses_saved_cited_evidence(monkeypatch):
    async def run():
        request,body,*_=environment();body.message='Explain the compensation information';body.conversation=[]
        class Store:
            def __init__(self,*args):pass
            def fetch(self,*args):return {'role':'Analyst','field':'Data'},{'opportunity_findings':[
                {'field':'compensation','value':SALARY,'source_ids':['salary'],'scope':'exact'}],
                'sources':[{'source_id':'salary','url':'https://example.test/salary'}]}
        async def generate(payload,*args,**kwargs):
            if payload.stage=='context_route':return NS(data=ContextPlan(topic='opportunity',research_focus='compensation',resolved_question=body.message))
            raise AIError('invalid_output',reason='json_syntax')
        request.app.state.ai=NS(generate=generate)
        monkeypatch.setattr('app.workflows.context_chat.QuestionStore',Store)
        result=await semantic_chat(request,'owner',{'workspace':{}},body)
        assert SALARY in result.reply and '[Source](<https://example.test/salary>)' in result.reply
    asyncio.run(run())


def evidence(text=SALARY,url='https://example.test/salary',focus='compensation'):
    source=ResearchSource(source_id='original',platform='other',url=url,evidence=text)
    sources,passages=question_passages({'web0':[source.model_dump()]})
    scopes={ref:NS(market='target',states_detail=True) for ref in range(len(passages))}
    findings,sources,*_=scoped_question_findings(focus,sources,passages,scopes,{'role':'Data Analyst','field':'Data'})
    return findings,sources


def test_salary_reuse_and_json_exposure_survive_new_store_instances(flow):
    ingest(flow);current=wait(flow);client,db,ai,_=flow;queries=[]
    async def collect(context,query):
        queries.append(query)
        return [ResearchSource(source_id='original',platform='other',url='https://example.test/salary',evidence=SALARY)]
    client.app.state.research_client=NS(collect_query=collect)
    staged=NS(settings=ai.settings,generate=context_stages(answer=cite_salary,fallback=ai.generate))
    client.app.state.ai=ModelRouter(staged,staged)
    command={'session_id':current['session_id'],'expected_version':current['revision'],'message':'what is the salary'}
    first=client.post(BASE+'/messages',headers=headers(),json=command)
    assert first.status_code==200,first.text
    assert SALARY in first.json()['reply'] and len(queries)==1
    repo=client.app.state.workspace_store;row=repo.row(OWNER)
    records=QuestionMemory(repo,client.app.state.research_store).entries(OWNER,row)
    assert len(records)==1 and records[0].question_findings[0].value==SALARY
    assert records[0].question_findings[0].quotes==[SALARY]
    projection=QuestionStore(repo,client.app.state.research_store).fetch(OWNER,row,'opportunity')
    assert any(item['value']==SALARY for item in projection[1]['opportunity_findings'])
    second=client.post(BASE+'/messages',headers=headers(),json=command)
    assert second.status_code==200 and SALARY in second.json()['reply'] and len(queries)==1
    result=client.get(f"/api/v1/career/goals/{current['current']['goal']['_id']}/opportunity-research",headers=headers())
    assert result.status_code==200,result.text
    saved=result.json()['question_research'][0]
    assert saved['focus']=='compensation' and saved['findings'][0]['value']==SALARY
    assert 'quotes' not in saved['findings'][0] and 'evidence' not in saved['sources'][0]
    path=f"/api/v1/career/goals/{current['current']['goal']['_id']}/opportunity-research/findings/{saved['findings'][0]['finding_id']}/evidence?research_id={saved['research_id']}"
    assert client.get(path,headers=headers()).json()['quotes']==[SALARY]
    assert client.get(path,headers=headers(other=True)).status_code==404
    assert db.research_contexts.count_documents({'kind':'question_result','owner':OWNER})==1


def test_concurrent_question_saves_merge_and_keep_immutable_history(flow):
    ingest(flow);wait(flow);client,db,*_=flow;repo=client.app.state.workspace_store;research=client.app.state.research_store
    row=repo.row(OWNER)
    a=evidence();b=evidence('Data Analyst salary in Singapore is SGD 1800 per month.','https://example.test/second')
    def save(values):return QuestionMemory(repo,research).save(OWNER,row,'compensation',*values)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,[a,b]))
    records=QuestionMemory(repo,research).entries(OWNER,row)
    assert len(records)==1 and {f.value for f in records[0].question_findings}=={SALARY,'Data Analyst salary in Singapore is SGD 1800 per month.'}
    assert len(research.records.get_research(results[0].id).question_findings) in (1,2)
    assert db.interview_research.count_documents({'question_focus':'compensation'})>=2
    save(evidence('Data Analyst salary in Singapore is SGD 1600 per month.'))
    latest=QuestionMemory(repo,research).entries(OWNER,row)[0]
    assert {SALARY,'Data Analyst salary in Singapore is SGD 1600 per month.'}<={f.value for f in latest.question_findings}


def test_question_memory_rejects_wrong_owner_stale_revision_and_forged_evidence(flow):
    ingest(flow);wait(flow);client,db,*_=flow;repo=client.app.state.workspace_store;research=client.app.state.research_store
    row=repo.row(OWNER);memory=QuestionMemory(repo,research)
    from app.repositories.goals import GoalError
    with pytest.raises(GoalError):memory.save(OTHER,row,'compensation',*evidence())
    findings,sources=evidence();findings[0].quotes=['Invented salary.'];findings[0].value='Invented salary.'
    with pytest.raises(GoalError):memory.save(OWNER,row,'compensation',findings,sources)
    memory.save(OWNER,row,'compensation',*evidence())
    db.career_goals.update_one({'_id':row['goal_id']},{'$inc':{'version':1}})
    with pytest.raises(GoalError):memory.save(OWNER,row,'compensation',*evidence())
    newer=repo.row(OWNER)
    assert memory.entries(OWNER,newer)==[]


def test_store_refuses_unverified_evidence_and_rechecks_employer_and_role(flow):
    from app.domain.question_memory import passage_finding
    from app.repositories.goals import GoalError
    from app.repositories.question_memory import VERIFIED_EVIDENCE
    ingest(flow);wait(flow);client,db,*_=flow;repo=client.app.state.workspace_store;research=client.app.state.research_store
    row=repo.row(OWNER);memory=QuestionMemory(repo,research)
    foreign=ResearchSource(source_id='au',platform='other',url='https://www.seek.com.au/x',
                           evidence='Data Analyst salary in Sydney is AUD 5000 per month.')
    unscoped=([passage_finding('compensation',foreign.evidence,foreign)],[foreign])
    with pytest.raises(GoalError,match='verified'):memory.save(OWNER,row,'compensation',*unscoped)
    other_role=ResearchSource(source_id='marketing',platform='other',url='https://example.test/marketing',
                              evidence='Marketing intern salary in Singapore is SGD 900 per month.')
    forged=passage_finding('compensation',other_role.evidence,other_role,verified=True)
    with pytest.raises(GoalError,match='verified'):memory.save(OWNER,row,'compensation',[forged],[other_role])
    assert memory.entries(OWNER,row)==[]
    record=memory.save(OWNER,row,'compensation',*evidence())
    assert record.generation.prompt_version==VERIFIED_EVIDENCE and len(memory.entries(OWNER,row))==1
