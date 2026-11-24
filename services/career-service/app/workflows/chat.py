"""Transient follow-up graph: explain from structured JD + interview evidence."""
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from app.workflows.structured import structured_node
from app.workflows.current import workspace_revision
from app.ai.routing import chat_models
from app.domain.questions import REFUSAL, facts_for, MISSING
from app.schemas.jd import JDReply
import json
import re
from app.ai.adapter import Operation
from app.ai.errors import AIError
from app.ai.contracts import AIInput,Message
from app.ai.qa_contracts import QuestionRoute
from app.repositories.questions import QuestionStore
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.domain.goal_edits import edit_context,apply_changes
from app.workflows.context_chat import semantic_chat
from app.workflows.citations import fact_citations

async def focused_chat(request,account,row,body):
    """Route -> projected retrieval -> answer."""
    if row['workspace'].get('edit_draft'):
        return None
    if getattr(chat_models(request.app.state),'context_enabled',False):
        return await semantic_chat(request,account,row,body)
    repo=request.app.state.workspace_store
    store=QuestionStore(repo,request.app.state.research_store)
    title=await thread(store.metadata,account,row['workspace']['review_id'])
    revision=str(body.expected_version)
    async def generate(stage,context,history=()):
        await thread(repo.check,account,body.session_id,body.expected_version)
        result=await request.app.state.ai.generate(AIInput(stage=stage,context=json.dumps(jsonable_encoder(context)),conversation=[*history,Message(role='user',content=body.message)]),
            Operation(account,revision,stage),current_revision=workspace_revision(repo,account,body.session_id,body.expected_version))
        return result.data
    async def route(state):
        previous=[m.model_copy(update={'content':m.content[:200]}) for m in body.conversation[-2:]]
        chosen=QuestionRoute.model_validate((await generate('question_route',{'goal':title,**({'scope':'career'} if getattr(body,'mode','question')=='refine' else {})},previous)).model_dump())
        if chosen.topic=='career_guidance' and getattr(body,'mode','question')!='refine':chosen=QuestionRoute(topic='off_topic')
        return {'route':chosen}
    async def retrieve(state):
        chosen=state['route']
        if chosen.topic in ('off_topic','edit','career_guidance'):return state
        include_evidence=bool(re.search(r'\b(why|evidence|source|quote|explain|detail|mean)\b',body.message,re.I))
        goal,research=await thread(store.fetch,account,row,chosen.topic,include_evidence)
        facts,links,truncated=facts_for(chosen,goal,research,include_evidence)
        return {**state,'facts':facts,'links':links,'partial':truncated}
    def finish(reply,refs,links):
        return JDReply(reply=fact_citations(reply,refs,links),proposed_skills=None)
    async def answer(state):
        chosen=state['route']
        if chosen.topic=='edit':return {'result':None}
        if chosen.topic=='off_topic':return {'result':JDReply(reply=REFUSAL,proposed_skills=None)}
        if chosen.topic=='career_guidance':
            history=[m.model_copy(update={'content':m.content[:300]}) for m in body.conversation[-2:]] if chosen.followup else []
            result=await generate('career_guidance',{'goal':title,'scope':'career'},history)
            if result.status!='answered':return {'result':JDReply(reply=REFUSAL,proposed_skills=None)}
            return {'result':JDReply(reply=result.reply,proposed_skills=None)}
        facts=state['facts']
        if not facts:return {'result':JDReply(reply=MISSING,proposed_skills=None)}
        history=[m.model_copy(update={'content':m.content[:300]}) for m in body.conversation[-2:]] if chosen.followup else []
        result=await generate('focused_answer',{'goal':title,'facts':facts,'partial':state['partial']},history)
        if result.status!='answered':return {'result':JDReply(reply=REFUSAL if result.status=='off_topic' else MISSING,proposed_skills=None)}
        if not result.references or any(ref not in state['links'] for ref in result.references):raise AIError('invalid_output',True,reason='provenance',fields=('references',))
        return {'result':finish(result.reply,result.references,state['links'])}
    graph=StateGraph(dict)
    for name,node in (('route_question',route),('retrieve_relevant_fields',retrieve),('answer_from_facts',answer)):graph.add_node(name,structured_node(node) if name!='retrieve_relevant_fields' else node)
    graph.add_edge(START,'route_question');graph.add_edge('route_question','retrieve_relevant_fields');graph.add_edge('retrieve_relevant_fields','answer_from_facts');graph.add_edge('answer_from_facts',END)
    with tracing_context(enabled=False):value=await graph.compile().ainvoke({})
    return value['result']


async def edit_goal(request,account,row,body):
    """A model proposes a narrow change set; validation precedes all persistence."""
    repo=request.app.state.workspace_store;w=row['workspace']
    review=await thread(repo.reviews.get,w['review_id'],account)
    pending=w.get('edit_draft')
    context=edit_context(review.content,pending)
    def validate(decision):
        if decision.status=='ready':
            content=apply_changes(review.content,decision.changes,decision.intent)
            if review.target_type=='career_exploration' and any(item.origin=='employer' for item in [*content.skills,*content.non_skill_requirements]):
                raise AIError('invalid_output',True,reason='unexpected_origin',fields=('origin',))
    async def decide(state):
        await thread(repo.check,account,body.session_id,body.expected_version)
        result=await request.app.state.ai.generate(AIInput(stage='goal_edit',context=json.dumps(context,separators=(',',':')),
            conversation=[Message(role='user',content=body.message)]),
            Operation(account,str(body.expected_version),'goal_edit'),current_revision=workspace_revision(repo,account,body.session_id,body.expected_version),validate_output=validate)
        validate(result.data)
        return {'decision':result.data}
    graph=StateGraph(dict);graph.add_node('clarify_or_apply_goal_change',structured_node(decide))
    graph.add_edge(START,'clarify_or_apply_goal_change');graph.add_edge('clarify_or_apply_goal_change',END)
    with tracing_context(enabled=False):result=await graph.compile().ainvoke({})
    return result['decision'],review
