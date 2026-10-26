"""Gemini interprets and selects saved context; reasoning is delegated selectively."""
import json
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from starlette.concurrency import run_in_threadpool as thread
from fastapi.encoders import jsonable_encoder
from app.ai.adapter import AIError,Operation
from app.ai.contracts import AIInput,Message
from app.ai.context_contracts import ContextPlan
from app.domain.context import context_index,selected_facts,merge_projection
from app.domain.questions import REFUSAL,MISSING
from app.repositories.questions import QuestionStore,GOAL_FIELDS
from app.schemas.jd import JDReply
from app.workflows.structured import structured_node


async def semantic_chat(request,account,row,body):
    repo=request.app.state.workspace_store
    store=QuestionStore(repo,request.app.state.research_store)
    revision=str(body.expected_version)
    async def generate(stage,context,history=(),question=None,validate=None):
        await thread(repo.check,account,body.session_id,body.expected_version)
        result=await request.app.state.ai.generate(AIInput(stage=stage,
            context=json.dumps(jsonable_encoder(context),separators=(',',':')),
            conversation=[*history,Message(role='user',content=question or body.message)]),
            Operation(account,revision,stage),current_revision=lambda:revision,validate_output=validate)
        return result.data

    async def plan_context(state):
        goal,research=await thread(store.fetch,account,row,'overview')
        index=context_index(goal,research,row['workspace'].get('edit_draft'))
        allowed={item['ref'] for item in index['items']}
        def validate(plan):
            if not set(plan.item_refs)<=allowed or any(topic not in GOAL_FIELDS for topic in plan.related_topics):
                raise AIError('invalid_output',True,reason='provenance',fields=('item_refs','related_topics'))
        history=[m.model_copy(update={'content':m.content[:400]}) for m in body.conversation[-6:]]
        plan=ContextPlan.model_validate((await generate('context_route',{'index':index},history,validate=validate)).model_dump())
        validate(plan)
        return {'plan':plan,'title':index['goal']}

    async def retrieve(state):
        plan=state['plan']
        if plan.topic in ('edit','off_topic') or plan.clarification or plan.missing:return state
        # Fixed projections and owner/linked-research checks remain backend-owned.
        from app.domain.context import PREFIXES
        topics=list(dict.fromkeys([plan.topic,*plan.related_topics,*[PREFIXES[ref[0]][0] for ref in plan.item_refs]]))
        if 'overview' in topics:topics=['overview']
        goal={};research={}
        for topic in topics:
            g,r=await thread(store.fetch,account,row,topic,plan.include_evidence)
            goal.update(g);research=merge_projection(research,r)
        facts,links,partial=selected_facts(plan,goal,research)
        return {**state,'facts':facts,'links':links,'partial':partial}

    async def answer(state):
        plan=state['plan']
        if plan.topic=='off_topic':return {'result':JDReply(reply=REFUSAL,proposed_skills=None)}
        if plan.topic=='edit':return {'result':None}  # Existing validated GPT edit workflow.
        if plan.clarification:return {'result':JDReply(reply=plan.clarification,proposed_skills=None)}
        if plan.missing or not state.get('facts'):return {'result':JDReply(reply=MISSING,proposed_skills=None)}
        stage='focused_answer' if plan.needs_reasoning else 'context_answer'
        def validate(output):
            if output.status=='answered' and (not output.references or any(ref not in state['links'] for ref in output.references)):
                raise AIError('invalid_output',True,reason='provenance',fields=('references',))
        result=await generate(stage,{'goal':state['title'],'facts':state['facts'],'partial':state['partial']},
                              question=plan.resolved_question,validate=validate)
        validate(result)
        if result.status!='answered':return {'result':JDReply(reply=REFUSAL if result.status=='off_topic' else MISSING,proposed_skills=None)}
        # Citation URLs are restored from saved sources, never supplied by either model.
        sources={v['source_id']:v for ref in result.references for v in state['links'].get(ref,[])}
        reply=result.reply
        for i,source in enumerate(sources.values(),1):
            link=f'[Source {i}]({source["url"]})'
            if len(reply)+len(link)+12>4000:break
            reply+= ('\n\nSources: ' if i==1 else ' · ')+link
        return {'result':JDReply(reply=reply,proposed_skills=None)}

    graph=StateGraph(dict)
    for name,node in (('understand_context',plan_context),('retrieve_selected_facts',retrieve),('answer',answer)):
        graph.add_node(name,structured_node(node) if name!='retrieve_selected_facts' else node)
    graph.add_edge(START,'understand_context');graph.add_edge('understand_context','retrieve_selected_facts')
    graph.add_edge('retrieve_selected_facts','answer');graph.add_edge('answer',END)
    with tracing_context(enabled=False):result=await graph.compile().ainvoke({})
    return result['result']
