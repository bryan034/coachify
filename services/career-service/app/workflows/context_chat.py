from app.repositories.goals import GoalError
"""Interpret saved context and retrieve public evidence when needed."""
from elo_shared.model_budget import budget_owner
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
from app.workflows.goal_question import research_question,question_queries
from app.workflows.citations import citation_error,fact_citations
from app.domain.question_memory import (direct_public_plan,focused_saved_facts,scoped_question_findings,excerpt_facts,
    saved_fact_reply,factual_reply,trusted_fact,market_scoped,cited_foreign_currency)
from app.domain.source_scope import related_places

PUBLIC_FOCUS={'role':'role_details','skills':'role_details','requirements':'eligibility',
    'interview_process':'interviews','interview_skills':'interviews','preparation':'interviews',
    'overview':'role_details','opportunity':'workplace'}


async def semantic_chat(request,account,row,body):
    import re
    if re.search(r'```|(?m:^\s*(?:def |class |function |import |const |let |public static ))',body.message):
        raise GoalError('Pasted code is not supported here. Ask your career question in plain language.',422)
    repo=request.app.state.workspace_store
    store=QuestionStore(repo,request.app.state.research_store)
    revision=str(body.expected_version)
    search_count=0
    refining=getattr(body,'mode','question')=='refine'
    async def public_facts(title,focus,query):
        nonlocal search_count
        current=workspace_revision(repo,account,body.session_id,body.expected_version)
        async def check():
            if await current()!=revision:raise AIError('stale_input',True)
        await check()
        # Completed queries are recorded for this turn; quota waits retry only the unfinished request.
        with budget_owner(account):result=await research_question(request,title,focus,check,query=query)
        search_count+=1
        return result
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
        # Places the saved JD names widen public search and tell the answer model which markets relate.
        descriptions=[item.get('description') for item in goal.get('non_skill_requirements',[])]
        places=related_places(goal,[goal.get('summary'),*goal.get('responsibilities',[]),*descriptions])
        if places:index['goal']={**index['goal'],'related_locations':places}
        direct=direct_public_plan(body.message)
        if direct:return {'plan':direct,'title':index['goal'],'direct':True}
        if refining:index['scope']='career'
        allowed={item['ref'] for item in index['items']}
        def validate(plan):
            if not set(plan.item_refs)<=allowed or any(topic not in GOAL_FIELDS for topic in plan.related_topics):
                raise AIError('invalid_output',True,reason='provenance',fields=('item_refs','related_topics'))
        history=[m.model_copy(update={'content':m.content[:400]}) for m in body.conversation[-6:]]
        plan=ContextPlan.model_validate((await generate('context_route',{'index':index},history,validate=validate)).model_dump())
        validate(plan)
        if plan.topic=='career_guidance' and not refining:plan=plan.model_copy(update={'topic':'off_topic'})
        return {'plan':plan,'title':index['goal'],'skills':[str(s.get('name'))[:80] for s in goal.get('skills',[])[:20] if s.get('name')]}

    async def retrieve(state):
        plan=state['plan']
        if plan.topic in ('edit','off_topic','career_guidance') or plan.clarification:return state
        from app.domain.context import PREFIXES
        topics=list(dict.fromkeys([plan.topic,*plan.related_topics,*[PREFIXES[ref[0]][0] for ref in plan.item_refs]]))
        if 'overview' in topics:topics=['overview']
        goal={};research={}
        for topic in topics:
            g,r=await thread(store.fetch,account,row,topic,plan.include_evidence)
            goal.update(g);research=merge_projection(research,r)
        facts,links,partial=focused_saved_facts(plan.research_focus,goal,research) if plan.research_focus else selected_facts(plan,goal,research)
        # Saved findings about another market remain context but are never trusted job facts.
        facts=[market_scoped(fact,state['title'],links[fact['ref']]) for fact in facts]
        focus=plan.research_focus or PUBLIC_FOCUS.get(plan.topic)
        # Database first: search only when no trusted fact (direct lookups) or nothing relevant (other questions) is saved.
        untrusted=state.get('direct') and not any(trusted_fact(fact) for fact in facts)
        queries=question_queries(state['title'],focus,plan.public_search_terms) if focus else []
        return {**state,'facts':facts,'links':links,'partial':partial,'focus':focus,'queries':queries,'saved_facts':facts,'saved_links':links,
                'needs_search':bool(focus) and (not facts or plan.missing or bool(untrusted))}

    async def search_public(state):
        facts,links=await public_facts(state['title'],state['focus'],state['queries'][search_count])
        return {**state,'retrieved_facts':facts,'retrieved_links':links,'needs_search':False}

    async def persist(state,findings,sources):
        current=await thread(repo.check,account,body.session_id,body.expected_version)
        if findings:
            activity('saving_question_findings')
            await thread(store.save_question,account,current,state['focus'],findings,sources)

    async def prepare_findings(state):
        verified,verified_sources,unverified,unverified_sources=scoped_question_findings(
            state['focus'],state['retrieved_links'],state['title'],terms=state['plan'].public_search_terms,
            require_focus=bool(state.get('direct')))
        # Only passages that pass every deterministic scope check become saved job facts.
        known={f.finding_id for f in state.get('candidates',[])}
        fresh=[f for f in verified if f.finding_id not in known]
        if fresh:await persist(state,fresh,[s for s in verified_sources if s.source_id in {i for f in fresh for i in f.source_ids}])
        findings=[*verified,*unverified];sources=[*verified_sources,*unverified_sources]
        candidates={f.finding_id:f for f in state.get('candidates',[])}
        candidates.update({f.finding_id:f for f in findings})
        findings=list(candidates.values())[-12:]
        source_map={s.source_id:s for s in [*state.get('candidate_sources',[]),*sources]}
        # Preserve each exact passage if another query returns a different excerpt
        # from the same canonical URL/source identity.
        for sid,source in list(source_map.items()):
            quotes=[quote for f in findings for source_id,quote in zip(f.source_ids,f.quotes) if source_id==sid]
            source_map[sid]=source.model_copy(update={'evidence':'\n'.join(dict.fromkeys(quotes))})
        sources=list(source_map.values())
        facts,links=excerpt_facts(findings,sources)
        facts=[*state.get('saved_facts',[]),*facts];links={**state.get('saved_links',{}),**links}
        return {**state,'facts':facts,'links':links,'partial':False,'needs_search':False,
                'candidates':findings,'candidate_sources':sources}

    async def answer(state):
        plan=state['plan']
        if plan.topic=='off_topic':return {'result':JDReply(reply=REFUSAL,proposed_skills=None)}
        if plan.topic=='edit':return {'result':None}
        if plan.clarification:return {'result':JDReply(reply=plan.clarification,proposed_skills=None)}
        if plan.topic=='career_guidance':
            activity('answering_question')
            history=[m.model_copy(update={'content':m.content[:300]}) for m in body.conversation[-2:]] if plan.followup else []
            result=await generate('career_guidance',{'goal':state['title'],'saved_skills':state.get('skills',[]),'scope':'career'},history)
            if result.status!='answered':return {'result':JDReply(reply=REFUSAL,proposed_skills=None)}
            await thread(repo.check,account,body.session_id,body.expected_version)
            return {'result':JDReply(reply=result.reply,proposed_skills=None),'needs_search':False}
        if state.get('direct'):
            reply=factual_reply(state.get('facts',[]),state.get('links',{}))
            if reply:
                await thread(repo.check,account,body.session_id,body.expected_version)
                return {'result':JDReply(reply=reply,proposed_skills=None),'needs_search':False}
        def missing():
            return 'I could not verify that detail in the public sources retrieved for this goal. What would you like to clarify or research next?' if search_count else MISSING
        if not state.get('facts'):
            if search_count<len(state.get('queries',[])):
                return {**state,'needs_search':True}
            return {'result':JDReply(reply=missing(),proposed_skills=None)}
        activity('answering_question')
        stage='focused_answer' if plan.needs_reasoning else 'context_answer'
        def validate(output):
            if output.status=='answered':
                fact_citations(output.reply,output.references,state['links'])
                if not cited_foreign_currency(output.reply,output.references,state['facts']):
                    raise citation_error('unsupported_foreign_currency')
        @structured_node
        async def answer_facts(_):
            result=await generate(stage,{'goal':state['title'],'facts':state['facts'],'partial':state['partial']},
                                  question=plan.resolved_question,validate=validate)
            validate(result)
            return result
        try:result=await answer_facts({})
        except AIError as error:
            if error.code not in ('invalid_output','incomplete_output','context_limit'):raise
            if search_count:
                verified=factual_reply(state['facts'],state['links'])
                if verified:
                    await thread(repo.check,account,body.session_id,body.expected_version)
                    return {'result':JDReply(reply=verified,proposed_skills=None),'needs_search':False}
                if search_count<len(state['queries']):return {**state,'needs_search':True}
                return {'result':JDReply(reply=missing(),proposed_skills=None),'needs_search':False}
            reply=saved_fact_reply(state['facts'],state['links'],state['partial'])
            if not reply:raise
            await thread(repo.check,account,body.session_id,body.expected_version)
            return {'result':JDReply(reply=reply,proposed_skills=None),'needs_search':False}
        if result.status=='not_found' and search_count<len(state['queries']):
            return {**state,'needs_search':True}
        validate(result)
        if result.status!='answered':return {'result':JDReply(reply=REFUSAL if result.status=='off_topic' else missing(),proposed_skills=None)}
        reply=fact_citations(result.reply,result.references,state['links'])
        await thread(repo.check,account,body.session_id,body.expected_version)
        return {'result':JDReply(reply=reply,proposed_skills=None),'needs_search':False}

    graph=StateGraph(dict)
    for name,node in (('understand_context',plan_context),('retrieve_saved_facts',retrieve),('search_public_sources',search_public),('prepare_question_evidence',prepare_findings),('answer',answer)):
        graph.add_node(name,structured_node(node) if name=='understand_context' else node)
    graph.add_edge(START,'understand_context');graph.add_edge('understand_context','retrieve_saved_facts')
    graph.add_conditional_edges('retrieve_saved_facts',lambda s:'search' if s.get('needs_search') else 'answer',{'search':'search_public_sources','answer':'answer'})
    graph.add_edge('search_public_sources','prepare_question_evidence');graph.add_edge('prepare_question_evidence','answer')
    graph.add_conditional_edges('answer',lambda s:'search' if s.get('needs_search') else 'done',{'search':'search_public_sources','done':END})
    with tracing_context(enabled=False):result=await graph.compile().ainvoke({})
    return result['result']
