"""Interpret saved context and retrieve public evidence when needed."""
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
from app.workflows.current import workspace_revision
from app.ai.routing import chat_models
from app.workflows.activity import activity
from app.workflows.citations import fact_citations
from app.domain.question_memory import direct_public_plan,focused_saved_facts,exact_question_findings,excerpt_facts,saved_fact_reply

PUBLIC_FOCUS={'role':'role_details','skills':'role_details','requirements':'eligibility',
    'interview_process':'interviews','interview_skills':'interviews','preparation':'interviews',
    'overview':'role_details','opportunity':'workplace'}


async def semantic_chat(request,account,row,body):
    repo=request.app.state.workspace_store
    store=QuestionStore(repo,request.app.state.research_store)
    revision=str(body.expected_version)
    searched=None
    async def public_facts(title,focus):
        nonlocal searched
        from app.workflows.goal_question import research_question
        current=workspace_revision(repo,account,body.session_id,body.expected_version)
        async def check():
            if await current()!=revision:raise AIError('stale_input',True)
        await check()
        # Reuse paid evidence during structured-response repairs. At most one
        # scoped retrieval per question; no private message enters the query.
        if searched is None:searched=await research_question(request,title,focus,check)
        return searched
    async def generate(stage,context,history=(),question=None,validate=None):
        await thread(repo.check,account,body.session_id,body.expected_version)
        result=await chat_models(request.app.state).generate(AIInput(stage=stage,
            context=json.dumps(jsonable_encoder(context),separators=(',',':')),
            conversation=[*history,Message(role='user',content=question or body.message)]),
            Operation(account,revision,stage),current_revision=workspace_revision(repo,account,body.session_id,body.expected_version),validate_output=validate)
        return result.data

    async def plan_context(state):
        activity('understanding_question')
        goal,research=await thread(store.fetch,account,row,'overview')
        index=context_index(goal,research,row['workspace'].get('edit_draft'))
        direct=direct_public_plan(body.message)
        if direct:return {'plan':direct,'title':index['goal'],'direct':True}
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
        # Fixed projections and owner/linked-research checks remain backend-owned.
        from app.domain.context import PREFIXES
        topics=list(dict.fromkeys([plan.topic,*plan.related_topics,*[PREFIXES[ref[0]][0] for ref in plan.item_refs]]))
        if 'overview' in topics:topics=['overview']
        goal={};research={}
        for topic in topics:
            g,r=await thread(store.fetch,account,row,topic,plan.include_evidence)
            goal.update(g);research=merge_projection(research,r)
        facts,links,partial=focused_saved_facts(plan.research_focus,goal,research) if plan.research_focus else selected_facts(plan,goal,research)
        focus=plan.research_focus or PUBLIC_FOCUS.get(plan.topic)
        return {**state,'facts':facts,'links':links,'partial':partial,'focus':focus,'needs_search':not facts and bool(focus)}

    async def search_public(state):
        facts,links=await public_facts(state['title'],state['focus'])
        return {**state,'retrieved_facts':facts,'retrieved_links':links,'needs_search':False}

    async def save_findings(state):
        findings,sources=exact_question_findings(state['focus'],state['retrieved_facts'],state['retrieved_links'])
        current=await thread(repo.check,account,body.session_id,body.expected_version)
        if findings:
            activity('saving_question_findings')
            await thread(store.save_question,account,current,state['focus'],findings,sources)
        # Never answer with an unvalidated generated extract or an unrelated page.
        facts,links=excerpt_facts(findings,sources)
        return {**state,'facts':facts,'links':links,'partial':False,'needs_search':False}

    async def answer(state):
        plan=state['plan']
        if plan.topic=='off_topic':return {'result':JDReply(reply=REFUSAL,proposed_skills=None)}
        if plan.topic=='edit':return {'result':None}  # Existing validated edit workflow.
        if plan.clarification:return {'result':JDReply(reply=plan.clarification,proposed_skills=None)}
        def missing():
            return 'I could not verify that detail in the public sources retrieved for this goal. What would you like to clarify or research next?' if searched is not None else MISSING
        if not state.get('facts'):
            return {'result':JDReply(reply=missing(),proposed_skills=None)}
        if state.get('direct'):
            reply=saved_fact_reply(state['facts'],state['links'],state['partial'])
            if reply:
                await thread(repo.check,account,body.session_id,body.expected_version)
                return {'result':JDReply(reply=reply,proposed_skills=None),'needs_search':False}
        activity('answering_question')
        stage='focused_answer' if plan.needs_reasoning else 'context_answer'
        def validate(output):
            if output.status=='answered':
                fact_citations(output.reply,output.references,state['links'])
        @structured_node
        async def answer_facts(_):
            result=await generate(stage,{'goal':state['title'],'facts':state['facts'],'partial':state['partial']},
                                  question=plan.resolved_question,validate=validate)
            validate(result)
            return result
        try:result=await answer_facts({})
        except AIError as error:
            if error.code not in ('invalid_output','incomplete_output','context_limit'):raise
            reply=saved_fact_reply(state['facts'],state['links'],state['partial'])
            if not reply:raise
            await thread(repo.check,account,body.session_id,body.expected_version)
            return {'result':JDReply(reply=reply,proposed_skills=None),'needs_search':False}
        if result.status=='not_found' and searched is None and state.get('focus'):
            return {**state,'needs_search':True}
        validate(result)
        if result.status!='answered':return {'result':JDReply(reply=REFUSAL if result.status=='off_topic' else missing(),proposed_skills=None)}
        reply=fact_citations(result.reply,result.references,state['links'])
        await thread(repo.check,account,body.session_id,body.expected_version)
        return {'result':JDReply(reply=reply,proposed_skills=None),'needs_search':False}

    graph=StateGraph(dict)
    for name,node in (('understand_context',plan_context),('retrieve_saved_facts',retrieve),('search_public_sources',search_public),('validate_and_save_findings',save_findings),('answer',answer)):
        graph.add_node(name,structured_node(node) if name=='understand_context' else node)
    graph.add_edge(START,'understand_context');graph.add_edge('understand_context','retrieve_saved_facts')
    graph.add_conditional_edges('retrieve_saved_facts',lambda s:'search' if s.get('needs_search') else 'answer',{'search':'search_public_sources','answer':'answer'})
    graph.add_edge('search_public_sources','validate_and_save_findings');graph.add_edge('validate_and_save_findings','answer')
    graph.add_conditional_edges('answer',lambda s:'search' if s.get('needs_search') else 'done',{'search':'search_public_sources','done':END})
    with tracing_context(enabled=False):result=await graph.compile().ainvoke({})
    return result['result']
