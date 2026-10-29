"""Transient follow-up graph: explain from structured JD + interview evidence."""
from langgraph.graph import StateGraph,START,END
from langsmith import tracing_context
from app.workflows.structured import structured_node
from app.workflows.current import workspace_revision
from app.ai.routing import chat_models

async def focused_chat(request,account,row,body):
    """Route -> projected retrieval -> answer. Only ambiguous questions need routing AI."""
    if getattr(chat_models(request.app.state),'context_enabled',False):
        from app.workflows.context_chat import semantic_chat
        return await semantic_chat(request,account,row,body)
    import json
    import re
    from app.ai.adapter import Operation,AIError
    from app.ai.contracts import AIInput,Message
    from app.ai.qa_contracts import QuestionRoute
    from app.domain.questions import direct_route,facts_for,REFUSAL,MISSING
    from app.repositories.questions import QuestionStore
    from app.schemas.jd import JDReply
    from fastapi.encoders import jsonable_encoder
    from starlette.concurrency import run_in_threadpool as thread
    repo=request.app.state.workspace_store
    store=QuestionStore(repo,request.app.state.research_store)
    if row['workspace'].get('edit_draft'):
        chosen=direct_route(body.message)
        if chosen is not None and chosen.topic=='off_topic':return JDReply(reply=REFUSAL,proposed_skills=None)
        return None
    title=await thread(store.metadata,account,row['workspace']['review_id'])
    revision=str(body.expected_version)
    async def generate(stage,context,history=()):
        await thread(repo.check,account,body.session_id,body.expected_version)
        result=await request.app.state.ai.generate(AIInput(stage=stage,context=json.dumps(jsonable_encoder(context)),conversation=[*history,Message(role='user',content=body.message)]),
            Operation(account,revision,stage),current_revision=workspace_revision(repo,account,body.session_id,body.expected_version))
        return result.data
    async def route(state):
        chosen=direct_route(body.message)
        if chosen is None:
            previous=[m.model_copy(update={'content':m.content[:200]}) for m in body.conversation[-2:]]
            chosen=QuestionRoute.model_validate((await generate('question_route',{'goal':title},previous)).model_dump())
        return {'route':chosen}
    async def retrieve(state):
        chosen=state['route']
        if chosen.topic in ('off_topic','edit'):return state
        include_evidence=bool(re.search(r'\b(why|evidence|source|quote|explain|detail|mean)\b',body.message,re.I))
        goal,research=await thread(store.fetch,account,row,chosen.topic,include_evidence)
        facts,links,truncated=facts_for(chosen,goal,research,include_evidence)
        return {**state,'facts':facts,'links':links,'partial':truncated}
    def finish(reply,refs,links):
        sources={v['source_id']:v for ref in refs for v in links.get(ref,[])}
        if sources:
            # URLs come from stored validated sources, never model output.
            for i,v in enumerate(sources.values(),1):
                citation=f'[Source {i}]({v["url"]})'
                if len(reply)+len(citation)+12>4000:break
                reply+=('\n\nSources: ' if i==1 else ' · ')+citation
        return JDReply(reply=reply,proposed_skills=None)
    async def answer(state):
        chosen=state['route']
        if chosen.topic=='edit':return {'result':None}
        if chosen.topic=='off_topic':return {'result':JDReply(reply=REFUSAL,proposed_skills=None)}
        facts=state['facts']
        if not facts:return {'result':JDReply(reply=MISSING,proposed_skills=None)}
        if chosen.topic=='interview_process' and chosen.terms==['round_count']:
            count=facts[0]['data']['round_count']
            return {'result':finish(f'The saved interview research reports **{count} rounds**. This is reported guidance, not a guaranteed process.',[facts[0]['ref']],state['links'])}
        if chosen.topic=='role' and chosen.terms==['location']:
            return {'result':JDReply(reply='The saved job location is **'+facts[0]['data']['location']+'**.',proposed_skills=None)}
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
    import json
    from app.ai.adapter import AIError,Operation
    from app.ai.contracts import AIInput,Message
    from app.domain.goal_edits import edit_context,apply_changes
    from starlette.concurrency import run_in_threadpool as thread
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
