"""Synthetic recovery tests: no provider credentials, live tools or discarded output reuse."""
import asyncio
import json
import httpx
import pytest
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from app.ai.adapter import AIAdapter,AIError,Operation
from app.ai.config import AISettings
from app.ai.contracts import AIInput
from app.ai.recovery import recover_responses,validation_progress,validation_budget
from app.ai.waiting import quota_progress
from app.workflows.structured import structured_node


def test_graph_repairs_repeated_schema_json_and_truncated_responses_then_displays_only_valid_output():
    async def run():
        calls=[];feedback=[];waits=[]
        valid={'role':'Analyst','field':'Data','company':None,'skills':[]}
        def response(content,finish='stop'):
            return httpx.Response(200,json={'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},
                'choices':[{'finish_reason':finish,'message':{'content':content if isinstance(content,str) else json.dumps(content)}}]})
        def provider(request):
            calls.append(json.loads(request.content))
            if len(calls)==1:return response({'role':'PRIVATE_FAILED_VALUE','field':'Data','skills':[],'untrusted-secret-key':'DO_NOT_REUSE'})
            if len(calls)==2:return response({**valid,'skills':[{'name':'SQL','priority':'required','origin':'employer'}]})
            if len(calls)==3:return httpx.Response(429,headers={'Retry-After':'7'})
            if len(calls)==4:return response('{bad JSON')
            if len(calls)==5:return httpx.Response(400,json={'error':{'code':'json_validate_failed','failed_generation':'PRIVATE_PROVIDER_BODY'}})
            if len(calls)==6:return response('{"role":',finish='length')
            return response(valid)
        async def sleep(seconds):waits.append(seconds)
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            ai=AIAdapter(AISettings(enabled=True,model='fixture',api_key='fixture',response_mode='json_schema',max_output_tokens=2048),client,sleep=sleep)
            async def interpret(state):
                value=await ai.generate(AIInput(stage='jd_extraction',source_text='Synthetic Data Analyst role.'),
                    Operation('alice','1','jd_extraction'),current_revision=lambda:'1')
                return {'result':value.data}
            graph=StateGraph(dict);graph.add_node('interpret',structured_node(interpret));graph.add_edge(START,'interpret');graph.add_edge('interpret',END)
            enabled=recover_responses.set(True);observer=validation_progress.set(feedback.append);quota=quota_progress.set(lambda _:None)
            try:
                # Repairs stay within the same graph node, not graph recursion steps.
                with tracing_context(enabled=False): result=await graph.compile().ainvoke({},config={'recursion_limit':3})
            finally:
                quota_progress.reset(quota);validation_progress.reset(observer);recover_responses.reset(enabled)
        assert result['result'].role=='Analyst' and len(calls)==7 and waits==[7]
        assert {'field':'company','issue':'missing'} in feedback[0]['violations']
        assert {'field':'skills.0.category','issue':'missing'} in feedback[1]['violations']
        assert calls[2]==calls[3]  # A quota wait preserves the current corrective payload.
        prompt=calls[2]['messages'][0]['content']
        latest=json.loads(prompt.split('Latest validation issues: ')[1])
        assert latest['fields']==['skills','category'] and latest['violations']==[{'field':'skills.0.category','issue':'missing'}]
        assert prompt.count('Latest validation issues: ')==1
        assert all('PRIVATE_FAILED_VALUE' not in json.dumps(c) and 'DO_NOT_REUSE' not in json.dumps(c)
                   and 'untrusted-secret-key' not in json.dumps(c) and 'PRIVATE_PROVIDER_BODY' not in json.dumps(c) for c in calls)
        assert feedback[-1] is None
    asyncio.run(run())


def test_corrections_do_not_expire_the_original_graph_execution_budget():
    async def run():
        count=[]
        async def node(state):
            count.append(1)
            if len(count)==1:raise AIError('invalid_output',reason='schema_validation',fields=('reply',))
            await asyncio.sleep(.03)
            return {'result':'Valid'}
        enabled=recover_responses.set(True)
        try:
            async with asyncio.timeout(.01) as budget:
                timer=validation_budget.set(budget)
                try:result=await structured_node(node)({})
                finally:validation_budget.reset(timer)
        finally:recover_responses.reset(enabled)
        assert result=={'result':'Valid'} and len(count)==2
    asyncio.run(run())


@pytest.mark.parametrize('code',['provider_auth','input_limit','stale_input'])
def test_non_format_failures_do_not_enter_repair_loop(code):
    async def run():
        calls=[]
        async def node(state):calls.append(1);raise AIError(code)
        enabled=recover_responses.set(True)
        try:
            with pytest.raises(AIError,match=code):await structured_node(node)({})
        finally:recover_responses.reset(enabled)
        assert calls==[1]
    asyncio.run(run())


def test_unfinished_repair_loop_can_be_cancelled():
    async def run():
        entered=asyncio.Event();calls=[]
        async def node(state):
            calls.append(1)
            raise AIError('invalid_output',reason='schema_validation',fields=('reply',))
        def progress(value):
            if value is not None:entered.set()
        enabled=recover_responses.set(True);observer=validation_progress.set(progress)
        task=asyncio.create_task(structured_node(node)({}))
        recover_responses.reset(enabled);validation_progress.reset(observer)
        await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert calls
    asyncio.run(run())


def test_repeated_invalid_responses_stop_after_six_repairs():
    async def run():
        calls=[]
        async def node(state):calls.append(1);raise AIError('invalid_output',reason='schema_validation')
        context=recover_responses.set(True)
        try:
            with pytest.raises(AIError,match='invalid_output'):await structured_node(node)({})
        finally:recover_responses.reset(context)
        assert len(calls)==7
    asyncio.run(run())
