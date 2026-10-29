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
from app.ai.routing import chat_models
from app.workflows.activity import activity
from app.workflows.citations import fact_citations


async def semantic_chat(request,account,row,body):
    repo=request.app.state.workspace_store
    store=QuestionStore(repo,request.app.state.research_store)
    revision=str(body.expected_version)
    async def generate(stage,context,history=(),question=None,validate=None):
        await thread(repo.check,account,body.session_id,body.expected_version)
        result=await chat_models(request.app.state).generate(AIInput(stage=stage,
            context=json.dumps(jsonable_encoder(context),separators=(',',':')),
            conversation=[*history,Message(role='user',content=question or body.message)]),
            Operation(account,revision,stage),current_revision=lambda:revision,validate_output=validate)
        return result.data

    async def plan_context(state):
        activity('understanding_question')
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
        if plan.topic in ('edit','off_topic') or plan.clarification:return state
        if plan.research_focus:
            from app.workflows.goal_question import research_question
            async def check():
                await thread(repo.check,account,body.session_id,body.expected_version)
            facts,links=await research_question(request,state['title'],plan.research_focus,check)
            return {**state,'facts':facts,'links':links,'partial':False}
        if plan.missing:return state
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
        missing='I could not verify that detail in the public sources retrieved for this goal. What would you like to clarify or research next?' if plan.research_focus else MISSING
        if not state.get('facts'):
            return {'result':JDReply(reply=missing,proposed_skills=None)}
        activity('answering_question')
        stage='focused_answer' if plan.needs_reasoning else 'context_answer'
        def validate(output):
            if output.status=='answered':
                fact_citations(output.reply,output.references,state['links'])
        result=await generate(stage,{'goal':state['title'],'facts':state['facts'],'partial':state['partial']},
                              question=plan.resolved_question,validate=validate)
        validate(result)
        if result.status!='answered':return {'result':JDReply(reply=REFUSAL if result.status=='off_topic' else missing,proposed_skills=None)}
        reply=fact_citations(result.reply,result.references,state['links'])
        return {'result':JDReply(reply=reply,proposed_skills=None)}

    graph=StateGraph(dict)
    for name,node in (('understand_context',plan_context),('retrieve_selected_facts',retrieve),('answer',answer)):
        graph.add_node(name,structured_node(node) if name!='retrieve_selected_facts' else node)
    graph.add_edge(START,'understand_context');graph.add_edge('understand_context','retrieve_selected_facts')
    graph.add_edge('retrieve_selected_facts','answer');graph.add_edge('answer',END)
    with tracing_context(enabled=False):result=await graph.compile().ainvoke({})
    return result['result']
