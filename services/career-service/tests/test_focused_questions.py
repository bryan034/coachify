from tests.api_views import saved_research
"""Scoped Q&A uses projected saved facts, not whole documents/history/edit schemas."""
import json
from types import SimpleNamespace
from bson import ObjectId
import pytest
from app.ai.adapter import AIAdapter
from app.ai.errors import AIError
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.qa_contracts import QuestionRoute,FocusedAnswer
from app.ai.usage import input_tokens
from app.domain.questions import facts_for
from app.repositories.questions import QuestionStore
from app.repositories.goals import GoalError
from tests.test_workspace import flow,ingest,wait,headers,BASE,OWNER


def ask(flow,current,message,**extras):
    return flow[0].post(BASE+'/messages',headers=headers(),json={'session_id':current['session_id'],'expected_version':current['revision'],'message':message,**extras})


def route_as(flow,route):
    """Make the synthetic question router return this route."""
    ai=flow[2];original=ai.generate
    async def generate(request,operation,**kwargs):
        if request.stage=='question_route':
            ai.calls.append(request);return SimpleNamespace(data=route)
        return await original(request,operation,**kwargs)
    ai.generate=generate


def answer_facts(ai,before):
    [answer]=[call for call in ai.calls[before:] if call.stage=='focused_answer']
    return json.loads(answer.context)['facts']


def test_clear_skill_question_sends_only_relevant_fields_without_history(flow):
    ingest(flow);current=wait(flow);_,_,ai,sources=flow
    before=len(ai.calls)
    response=ask(flow,current,'Which skills are required?',conversation=[{'role':'assistant','content':'UNRELATED_OLD_HISTORY '*100} for _ in range(12)])
    assert response.status_code==200,response.text
    calls=ai.calls[before:];assert [v.stage for v in calls]==['question_route','focused_answer']
    context=json.loads(calls[1].context)
    assert [f['kind'] for f in context['facts']]==['jd_skill']
    assert 'sources' not in context and 'summaries' not in context and 'responsibilities' not in str(context)
    assert len(calls[1].conversation)==1 and 'OLD_HISTORY' not in calls[1].model_dump_json()
    payload=AIAdapter(AISettings(enabled=True,model='openai/gpt-4o-mini',api_key='fixture'),None)._payload(calls[1])
    assert input_tokens(payload)<1000
    assert 'SkillEdits' not in str(payload['response_format'])


def test_missing_round_count_is_never_supplied_as_a_fact(flow):
    ingest(flow);current=wait(flow);ai=flow[2];before=len(ai.calls)
    route_as(flow,QuestionRoute(topic='interview_process'))
    reply=ask(flow,current,'How many interview rounds are there?')
    assert reply.status_code==200,reply.text
    facts=answer_facts(ai,before)
    assert facts and all(f['kind']=='interview_stage' for f in facts)


def test_saved_location_reaches_the_answer_as_a_job_detail(flow):
    ingest(flow);current=wait(flow);_,db,ai,_=flow
    db.career_goals.update_one({'_id':ObjectId(current['current']['goal']['_id'])},{'$set':{'location':'Singapore'}})
    before=len(ai.calls);route_as(flow,QuestionRoute(topic='role'))
    response=ask(flow,current,'Where is this role based?')
    assert response.status_code==200,response.text
    [details]=[f['data'] for f in answer_facts(ai,before) if f['kind']=='job_details']
    assert details['location']=='Singapore'


def test_ambiguous_question_routes_then_answers_and_followups_have_only_two_short_turns(flow):
    ingest(flow);current=wait(flow);_,_,ai,_=flow;original=ai.generate
    async def generate(request,operation,**kwargs):
        if request.stage=='question_route':
            ai.calls.append(request)
            assert len(request.conversation)==3 and len(request.conversation[0].content)<=200
            return SimpleNamespace(data=QuestionRoute(topic='skills',terms=['SQL'],followup=True))
        return await original(request,operation,**kwargs)
    ai.generate=generate
    response=ask(flow,current,'What about that one?',conversation=[{'role':'user','content':'Explain SQL '+('x'*900)},{'role':'assistant','content':'SQL '+('x'*900)}]*6)
    assert response.status_code==200,response.text
    answer=ai.calls[-1];assert answer.stage=='focused_answer' and len(answer.conversation)==3
    assert len(answer.conversation[0].content)<=300


def test_unknown_skill_returns_missing_after_routing_without_answer_call(flow):
    ingest(flow);current=wait(flow);_,_,ai,_=flow;original=ai.generate
    async def generate(request,operation,**kwargs):
        if request.stage=='question_route':
            ai.calls.append(request);return SimpleNamespace(data=QuestionRoute(topic='skills',terms=['Kubernetes']))
        return await original(request,operation,**kwargs)
    ai.generate=generate;before=len(ai.calls)
    response=ask(flow,current,'Is Kubernetes required?')
    assert response.status_code==200 and 'not found' in response.json()['reply']
    assert [v.stage for v in ai.calls[before:]]==['question_route']


def test_answer_cannot_invent_citation_references(flow):
    ingest(flow);current=wait(flow);_,_,ai,_=flow;original=ai.generate
    async def generate(request,operation,**kwargs):
        if request.stage=='focused_answer':return SimpleNamespace(data=FocusedAnswer(reply='Unsupported answer',references=['invented']))
        return await original(request,operation,**kwargs)
    ai.generate=generate
    assert ask(flow,current,'Which skills are required?').status_code==503


def test_question_store_uses_fixed_projections_and_owner_scope(flow):
    ingest(flow);current=wait(flow);_,_,_,_=flow
    repo=flow[0].app.state.workspace_store;store=QuestionStore(repo,flow[0].app.state.research_store)
    row=repo.row(OWNER)
    goal,research=store.fetch(OWNER,row,'skills')
    assert set(goal)=={'skills'} and 'process' not in research and 'summaries' not in research
    assert all('evidence' not in source for source in research.get('sources',[]))
    with pytest.raises(GoalError):store.metadata('another-owner',current['current']['goal']['_id'])
    row['workspace']['research_id']='000000000000000000000099'
    with pytest.raises(GoalError):store.fetch(OWNER,row,'skills')
    with pytest.raises(ValueError):store.fetch(OWNER,row,'$where')


def test_incomplete_skill_lists_are_marked_as_partial():
    facts,_,partial=facts_for(QuestionRoute(topic='skills'),{'skills':[{'name':f'Skill{i}'} for i in range(30)]},{})
    assert partial and len(facts)==12


def test_process_only_research_is_persisted_and_its_round_count_reaches_the_answer(flow):
    from app.schemas.analysis import ResearchSource,InterviewProcess,InterviewEvidence
    from app.schemas.research import SourcedTopics
    text='There are three interview rounds. A technical interview includes SQL.'
    client,db,ai,sources=flow
    async def collect(context,platform,round=0):
        return [ResearchSource(source_id='rounds-source',platform='other',url='https://example.test/interviews',evidence=text)]
    sources.collect_platform=collect;original=ai.generate
    async def generate(request,operation,**kwargs):
        result=await original(request,operation,**kwargs)
        if request.stage=='interview_synthesis':
            result.data=SourcedTopics(topics=[],process=InterviewProcess(round_count=3,round_count_evidence=InterviewEvidence(source_ids=['rounds-source'],text=text)))
        return result
    ai.generate=generate
    ingest(flow);current=wait(flow)
    assert saved_research(flow,current)['skills']==[] and saved_research(flow,current)['research_status']=='succeeded'
    assert db.interview_research.find_one({'_id':ObjectId(current['research_id'])})['process']['round_count']==3
    before=len(ai.calls);route_as(flow,QuestionRoute(topic='interview_process'))
    response=ask(flow,current,'How many interview rounds are there?')
    assert response.status_code==200,response.text
    assert {'kind':'interview_round_count','data':{'round_count':3}}.items()<=next(
        f for f in answer_facts(ai,before) if f['kind']=='interview_round_count').items()
    assert 'https://example.test/interviews' in response.json()['reply']


def test_explicit_skill_edits_use_edit_contract_without_interview_payload(flow):
    ingest(flow);current=wait(flow);_,_,ai,_=flow;before=len(ai.calls)
    route_as(flow,QuestionRoute(topic='edit'))
    response=ask(flow,current,'Add Python')
    assert response.status_code==200,response.text
    request=ai.calls[before:][1]
    assert request.stage=='goal_edit' and 'interview_research' not in json.loads(request.context)
    assert len(request.conversation)==1
    assert response.json()['edit_status']=='saved'
    assert any(s['name']=='Python' for s in response.json()['workspace']['current']['goal']['skills'])


def test_named_skill_retrieval_preserves_its_or_alternatives():
    goal={'skills':[{'name':'Python','group_id':'g1','group_operator':'any'}, {'name':'Java','group_id':'g1','group_operator':'any'}, {'name':'SQL'}]}
    facts,_,_=facts_for(QuestionRoute(topic='skills',terms=['Python']),goal,{})
    assert [v['data']['name'] for v in facts]==['Python','Java']
    assert all(v['data']['group_operator']=='any' for v in facts)


def test_supporting_evidence_is_only_sent_for_questions_that_need_it():
    goal={'skills':[{'name':'SQL','evidence':'SQL is required.','priority':'required'}]}
    route=QuestionRoute(topic='skills',terms=['SQL'])
    plain,_,_=facts_for(route,goal,{})
    explained,_,_=facts_for(route,goal,{},include_evidence=True)
    assert 'evidence' not in plain[0]['data']
    assert explained[0]['data']['evidence']=='SQL is required.'
    research={'skills':[{'name':'SQL','source_ids':['s1'],'summary_id':'a1','evidence_origin':'brave_summary'}],
        'summaries':[{'summary_id':'a1','text':'UNNEEDED FULL SUMMARY','claims':[{'text':'SQL assessment was reported.','source_ids':['s1']}]}],
        'sources':[{'source_id':'s1','url':'https://example.test/report','evidence':'Unrelated source excerpt.'}]}
    facts,_,_=facts_for(QuestionRoute(topic='interview_skills',terms=['SQL']),{},research,include_evidence=True)
    assert facts[0]['data']['supporting_evidence']==['SQL assessment was reported.']
    assert 'UNNEEDED FULL SUMMARY' not in str(facts)


def test_goal_questions_are_answered_in_refine_mode_without_the_edit_model(flow):
    ingest(flow);current=wait(flow);_,_,ai,_=flow
    before=len(ai.calls)
    response=ask(flow,current,'Which skills are required?',mode='refine')
    assert response.status_code==200,response.text
    assert [v.stage for v in ai.calls[before:]]==['question_route','focused_answer']
    assert response.json().get('edit_status') is None


def guidance_ai(ai):
    original=ai.generate
    async def generate(request,operation,**kwargs):
        if request.stage=='question_route':
            ai.calls.append(request);return SimpleNamespace(data=QuestionRoute(topic='career_guidance'))
        if request.stage=='career_guidance':
            from app.ai.qa_contracts import FocusedAnswer
            ai.calls.append(request)
            return SimpleNamespace(data=FocusedAnswer(reply='General guidance: data engineering could suit you.',references=[]))
        return await original(request,operation,**kwargs)
    ai.generate=generate


def test_refine_mode_allows_general_career_and_new_path_questions(flow):
    ingest(flow);current=wait(flow);_,_,ai,_=flow;guidance_ai(ai);before=len(ai.calls)
    response=ask(flow,current,'What other career paths could suit me?',mode='refine')
    assert response.status_code==200,response.text
    assert response.json()['reply'].startswith('General guidance') and response.json().get('edit_status') is None
    calls=ai.calls[before:];assert [v.stage for v in calls]==['question_route','career_guidance']
    assert json.loads(calls[0].context)['scope']=='career' and json.loads(calls[1].context)['scope']=='career'
    assert flow[0].get(BASE,headers=headers()).json()['revision']==current['revision']


def test_question_mode_still_refuses_career_path_exploration(flow):
    from app.domain.questions import REFUSAL
    ingest(flow);current=wait(flow);_,_,ai,_=flow;guidance_ai(ai);before=len(ai.calls)
    response=ask(flow,current,'What other career paths could suit me?')
    assert response.status_code==200 and response.json()['reply']==REFUSAL
    assert 'career_guidance' not in [v.stage for v in ai.calls[before:]]


def test_refine_mode_still_refuses_unrelated_tasks_the_router_rejects(flow):
    from app.domain.questions import REFUSAL
    ingest(flow);current=wait(flow);_,_,ai,_=flow;before=len(ai.calls)
    route_as(flow,QuestionRoute(topic='off_topic'))
    response=ask(flow,current,'Write a python script that sorts a list',mode='refine')
    assert response.json()['reply']==REFUSAL and [v.stage for v in ai.calls[before:]]==['question_route']
