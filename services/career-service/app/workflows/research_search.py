"""Checkpoint-friendly Gemini search planning and useful-source assessment."""
import re
import asyncio
from app.ai.recovery import validation_budget
from starlette.concurrency import run_in_threadpool as thread
from app.ai.adapter import AIError,Operation
from app.ai.contracts import AIInput
from app.api.v1.research import context_for
from app.clients.research import normalize_sources
from app.clients.search_sources import error_excerpt
from app.repositories.goals import GoalError,now
from datetime import timedelta

TARGET_SOURCES=3
MAX_SEARCHES=6


def enabled(workflow):
    provider=workflow.app.state.research_client
    return bool(getattr(workflow.app.state.ai,'context_enabled',False) and
        callable(getattr(provider,'collect_query',None)) and getattr(provider,'brave_mode','llm_context') in ('llm_context','search'))


def candidates(state):
    result=[];ids=set();seen=set()
    for value in state.get('sources',[])[:MAX_SEARCHES*6]:
        if value['source_id'] in ids:continue
        ids.add(value['source_id'])
        for source in normalize_sources([value]):
            quote=re.sub(r'\W+',' ',(source.evidence or '').casefold())
            if source.url in seen or quote in seen:continue
            seen.update((source.url,quote));result.append(source)
    return result


def query_key(query):return ' '.join(query.casefold().split())


def next_query(state,context):
    # Deterministic fallbacks keep employer/location rather than becoming global advice.
    base=' '.join(v[:limit] for v,limit in ((context.company,50),(context.role,40),(context.location,35),(context.field,20)) if v)
    fallbacks=[base+' '+focus for focus in ('interview process rounds','online assessment coding test',
        'technical interview questions','candidate interview experience','recruitment selection stages','assessment centre interview')]
    history={query_key(q) for q in state.get('query_history',[])}
    return next((q for q in [*state.get('planned_queries',[]),*fallbacks] if query_key(q) not in history),None)


async def renew(workflow,state):
    await workflow.valid(state)
    expires=now()+timedelta(seconds=240)
    await thread(workflow.db.career_state.update_one,{'_id':state['owner'],'workspace.run_id':state['run']},
                 {'$set':{'workspace.worker_until':expires}})
    token=state.get('cache',{}).get('token')
    if token:
        lease=await thread(workflow.db.research_contexts.update_one,{'lease.token':token,'lease.expires_at':{'$gt':now()}},
                           {'$set':{'lease.expires_at':expires}})
        if not lease.matched_count:raise GoalError('Research lease expired. Retry the saved research.')


async def plan(workflow,state):
    goal=await workflow.goal(state);await renew(workflow,state)
    hints=list(dict.fromkeys(skill.name for skill in goal.skills))[:8]
    result=await workflow.app.state.ai.generate(AIInput(stage='research_plan',public_context=context_for(goal),research_hints=hints),
        Operation(state['owner'],goal.id,'research_plan'),current_revision=lambda:goal.id)
    return {'planned_queries':list(dict.fromkeys(result.data.queries)),'query_history':[],
            'useful_source_ids':[],'latest_source_ids':[],'assessed_source_ids':[],
            'stalled_rounds':0,'search_exhausted':False}


async def assess(workflow,state):
    goal=await workflow.goal(state)
    if state.get('source_error'):
        # Later acquisition failures must not discard already assessed evidence.
        if state.get('useful_source_ids'):
            return {'search_exhausted':True}
        raise GoalError(state['source_error'],503)
    all_sources=candidates(state)
    wanted=set(state.get('useful_source_ids',[])+state.get('latest_source_ids',[]))
    assessed=set(state.get('assessed_source_ids',[]))
    previous=set(state.get('useful_source_ids',[]))
    fresh=[s for s in all_sources if s.source_id in wanted and s.source_id not in assessed]
    sources=[s for s in all_sources if s.source_id in previous or s in fresh]
    useful=state.get('useful_source_ids',[]);extra=[]
    if fresh:
        await renew(workflow,state)
        def validate(output):
            for item in output.useful_sources:
                index=int(item.ref[1:])
                if index>=len(sources) or item.quote not in (sources[index].evidence or '') or error_excerpt(item.quote) or error_excerpt(sources[index].evidence):
                    raise AIError('invalid_output',True,reason='provenance',fields=('useful_sources','quote'))
        result=await workflow.app.state.ai.generate(AIInput(stage='research_assess',public_context=context_for(goal),
            sources=sources,search_queries=state.get('query_history',[])),
            Operation(state['owner'],goal.id,'research_assess'),current_revision=lambda:goal.id,validate_output=validate)
        validate(result.data)
        useful=list(dict.fromkeys(sources[int(item.ref[1:])].source_id for item in result.data.useful_sources))
        extra=result.data.next_queries
        assessed.update(s.source_id for s in sources)
    round=state.get('round',0)+1
    stalled=0 if set(useful)-previous else state.get('stalled_rounds',0)+1
    budget=validation_budget.get()
    # Reserve a retrieval, assessment and synthesis before starting another round.
    settings=getattr(workflow.app.state.ai,'settings',None)
    primary=getattr(settings,'timeout_seconds',45)
    context=getattr(getattr(workflow.app.state.ai,'context',None),'settings',settings)
    reserve=40+getattr(context,'timeout_seconds',45)+primary+5
    out_of_time=budget is not None and budget.when() is not None and budget.when()-asyncio.get_running_loop().time()<reserve
    exhausted=round>=MAX_SEARCHES or stalled>=2 or out_of_time
    coverage={'platform':'brave','status':'succeeded' if useful else 'no_findings','round':round-1,
              'useful_sources':len(useful),'target_sources':TARGET_SOURCES,
              'limit_reached':exhausted and len(useful)<TARGET_SOURCES}
    await thread(workflow.workspaces.phase,state['owner'],state['session'],state['run'],'researching',
                 coverage=[*state.get('coverage',[]),coverage])
    history={query_key(q) for q in state.get('query_history',[])}
    pending=list(dict.fromkeys([*extra,*state.get('planned_queries',[])]))
    return {'round':round,'useful_source_ids':useful,'coverage':[coverage],
            'stalled_rounds':stalled,'search_exhausted':exhausted,
            'planned_queries':[q for q in pending if query_key(q) not in history][:8],
            'assessed_source_ids':sorted(assessed)}
