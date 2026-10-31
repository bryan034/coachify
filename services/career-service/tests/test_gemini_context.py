from tests.api_views import saved_research
"""Synthetic Gemini routing and semantic retrieval; no live APIs."""
import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest
from app.ai.adapter import AIAdapter,AIError,Operation
from app.ai.config import AISettings,GeminiSettings
from app.ai.contracts import AIInput
from app.ai.context_contracts import ContextPlan
from app.ai.qa_contracts import FocusedAnswer
from app.ai.routing import ModelRouter
from app.ai.usage import input_tokens
from app.domain.context import context_index,selected_facts,merge_projection,token_count,INDEX_TOKENS
from tests.test_workspace import flow,ingest,wait,BASE,headers
from tests.test_focused_questions import ask


def plan(**changes):return ContextPlan(**{'topic':'skills','item_refs':['s0'],'resolved_question':'Explain SQL requirements.',**changes})


def test_independent_gemini_configuration_and_safe_errors(monkeypatch):
    monkeypatch.setenv('AI_ENABLED','true');monkeypatch.setenv('GEMINI_API_KEY','gemini-fixture');monkeypatch.setenv('AI_API_KEY','unused-fixture')
    monkeypatch.delenv('CAREER_LLM_MODEL',raising=False)
    config=GeminiSettings.from_env()
    assert config.model=='gemini-3.5-flash-lite' and config.api_key.get_secret_value()=='gemini-fixture'
    assert 'gemini-fixture' not in repr(config)
    monkeypatch.setenv('AI_ENABLED','PRIVATE_INVALID')
    with pytest.raises(ValueError) as error:GeminiSettings.from_env()
    assert 'PRIVATE' not in str(error.value)


def test_all_reasoning_and_context_routes_share_gemini_without_local_quota():
    async def run():
        calls=[]
        def handler(request):
            body=json.loads(request.content);calls.append(body)
            assert request.url.host=='generativelanguage.googleapis.com' and request.headers['authorization']=='Bearer gemini-fixture'
            assert body['model']=='gemini-3.5-flash-lite'
            assert body['reasoning_effort']=='minimal' and 'max_tokens' in body and 'max_completion_tokens' not in body
            output=plan().model_dump() if body['response_format']['json_schema']['name']=='context_route' else FocusedAnswer(reply='SQL is required.',references=['f1']).model_dump()
            return httpx.Response(200,json={'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output)}}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=AIAdapter(GeminiSettings(enabled=True,api_key='gemini-fixture'),client)
            for stage in ('context_route','context_answer','focused_answer'):
                await ModelRouter(adapter,adapter).generate(AIInput(stage=stage,context='{"facts":[]}',conversation=[{'role':'user','content':'Explain SQL'}]),Operation('alice','1',stage),current_revision=lambda:'1')
        assert len(calls)==3
    asyncio.run(run())


def test_context_refs_preserve_alternatives_and_catalogue_omits_evidence():
    goal={'skills':[{'name':'Python','group_id':'g','group_operator':'any'},{'name':'Java','group_id':'g','group_operator':'any'},{'name':'SQL'}]}
    research={'skills':[{'name':'System design','source_ids':['s1']}],'sources':[{'source_id':'s1','url':'https://example.test/report'}]}
    facts,links,partial=selected_facts(plan(item_refs=['s0','i0'],related_topics=['interview_skills']),goal,research)
    assert [v['data']['name'] for v in facts]==['Python','Java','System design'] and not partial
    assert links['f3'][0]['url']=='https://example.test/report'
    index=context_index({'role':'Engineer','skills':[{'name':('Skill '+str(i)+' 技術能力測試範例'*15)[:160],'evidence':'PRIVATE_EVIDENCE','item_id':'PRIVATE_ID'} for i in range(60)]},{})
    assert token_count(index)<=INDEX_TOKENS and index['partial'] and 'PRIVATE' not in json.dumps(index)


def test_complementary_projections_keep_skill_names_process_and_evidence():
    first={'skills':[{'name':'SQL','source_ids':['s1']}],'sources':[{'source_id':'s1','evidence':'SQL assessment'}]}
    second={'skills':[{'interview_stage':'Technical interview'}],'sources':[{'source_id':'s1','url':'https://example.test/report'}]}
    merged=merge_projection(first,second)
    assert merged['skills'][0]['name']=='SQL' and merged['skills'][0]['interview_stage']=='Technical interview'
    assert merged['sources'][0]['evidence']=='SQL assessment' and 'url' in merged['sources'][0] and 'url' not in first['sources'][0]


class ContextAI:
    def __init__(self,decision):self.decision=decision;self.calls=[]
    async def generate(self,request,operation,**kwargs):
        self.calls.append(request)
        output=self.decision if request.stage=='context_route' else FocusedAnswer(reply='SQL is a required skill.',references=['f1'])
        if kwargs.get('validate_output'):kwargs['validate_output'](output)
        return SimpleNamespace(data=output)


def enable_context(flow,decision):
    context=ContextAI(decision);flow[0].app.state.ai=ModelRouter(flow[2],context);return context


def test_simple_semantic_question_uses_gemini_and_only_selected_facts(flow):
    ingest(flow);current=wait(flow);before=len(flow[2].calls);context=enable_context(flow,plan())
    response=ask(flow,current,'What capabilities does this role call for?')
    assert response.status_code==200,response.text
    assert response.json()['reply']=='SQL is a required skill.' and len(flow[2].calls)==before
    assert [v.stage for v in context.calls]==['context_route','context_answer']
    payload=json.loads(context.calls[-1].context)
    assert [f['data']['name'] for f in payload['facts']]==['SQL'] and 'index' not in payload


def test_followup_comparison_uses_gemini_with_multiple_topics_without_keyword_matching(flow):
    ingest(flow);current=wait(flow);before=len(flow[2].calls)
    context=enable_context(flow,plan(related_topics=['interview_skills','interview_process'],item_refs=['s0','i0'],followup=True,include_evidence=True,needs_reasoning=True,resolved_question='How does SQL support the technical interview?'))
    response=ask(flow,current,'How would that help with the technical screen?',conversation=[{'role':'assistant','content':'Relational data queries. '+('x'*800)}]*12)
    assert response.status_code==200,response.text
    calls=flow[2].calls[before:];assert [v.stage for v in calls]==['focused_answer']
    assert {'jd_skill','interview_finding','interview_stage'}<={v['kind'] for v in json.loads(calls[0].context)['facts']}
    assert len(calls[0].conversation)==1 and calls[0].conversation[0].content=='How does SQL support the technical interview?'
    assert len(context.calls)==1 and len(context.calls[0].conversation)==7 and all(len(m.content)<=400 for m in context.calls[0].conversation[:-1])
    assert saved_research(flow,current)['sources'][0]['url'] in response.json()['reply']


def test_context_clarification_avoids_an_extra_answer_call(flow):
    ingest(flow);current=wait(flow);before=len(flow[2].calls)
    context=enable_context(flow,plan(item_refs=[],clarification='Do you mean job skills or interview skills?'))
    response=ask(flow,current,'Can you explain that part?')
    assert response.status_code==200 and 'Do you mean' in response.json()['reply']
    assert len(context.calls)==1 and len(flow[2].calls)==before


def test_context_references_and_owner_scope_are_checked(flow):
    ingest(flow);current=wait(flow);context=enable_context(flow,plan(item_refs=['s999']))
    assert ask(flow,current,'Explain the requirements').status_code==503 and len(context.calls)==1
    other=flow[0].post(BASE+'/messages',headers=headers(other=True),json={'session_id':current['session_id'],'expected_version':current['revision'],'message':'Explain SQL'})
    assert other.status_code!=200 and len(context.calls)==1


def test_semantic_edit_intent_still_uses_the_validated_primary_edit_workflow(flow):
    ingest(flow);current=wait(flow);before=len(flow[2].calls);enable_context(flow,plan(topic='edit',item_refs=[]))
    response=ask(flow,current,'Could Python be part of my goal as well?')
    assert response.status_code==200,response.text
    assert response.json()['edit_status']=='saved' and [v.stage for v in flow[2].calls[before:]]==['goal_edit']


@pytest.mark.parametrize('provider,model',[('gemini','gemini-3.5-flash-lite'),('deepseek','deepseek-flash'),('local','deepseek-r1:1.5b')])
def test_startup_wires_one_configured_adapter_for_all_stages(monkeypatch,provider,model):
    from app.main import create_app
    from fastapi.testclient import TestClient
    monkeypatch.delenv('MONGODB_URI',raising=False)
    monkeypatch.setenv('AI_ENABLED','true')
    monkeypatch.setenv('CAREER_LLM_PROVIDER',provider)
    monkeypatch.setenv('CAREER_LLM_API_KEY','synthetic-key' if provider!='local' else '')
    upstream=httpx.AsyncClient(base_url='http://profile.test',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={})))
    with TestClient(create_app(profile_client=upstream)) as client:
        router=client.app.state.ai
        assert router.context_enabled and router.primary.settings.model==model
        assert router.context.settings.model==model and router.settings.provider==provider
        assert router.primary is router.context
