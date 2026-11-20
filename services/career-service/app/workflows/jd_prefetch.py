"""Transient public-only retrieval alongside full JD extraction; never persists raw JD."""
from elo_shared.model_budget import budget_owner
import asyncio
from datetime import timedelta
from app.clients.search_sources import SourceRateLimit
from app.ai.waiting import quota_progress
from app.repositories.goals import now
from app.schemas.analysis import ResearchContext
from app.workflows.activity import activity

from app.ai.adapter import Operation
from app.ai.contracts import AIInput
from app.ai.recovery import recover_responses
from app.workflows.opportunity.queries import ACTIVITIES,planned_queries
from app.workflows.opportunity.topics import TOPICS,owner as topic_owner,policy
import json

IDENTITY=('role','field','company','location','seniority_level','employment_type')

def matches(identity,goal):
    # Every employer/title/location/position value used in the retrieval query must match.
    def normalized(value):return ' '.join((value or '').casefold().split())
    return all(normalized(getattr(identity,k))==normalized(getattr(goal,k)) for k in IDENTITY if k!='field')

async def prefetch(engine,identity,owner,revision):
    context=ResearchContext(**{k:(identity.field or identity.role) if k=='field' else getattr(identity,k) for k in IDENTITY if k!='employment_type'})
    result={'queries':{},'history':{},'evidence':{},'waits':{},'searches_used':0}
    provider=getattr(engine.source,'provider',None)
    if provider:result['source_provider']=provider
    # Plan before retrieval while full JD extraction proceeds independently.
    recovery=recover_responses.set(False)
    waiting=quota_progress.set(None)
    activity('planning_research')
    try:
        model_settings=getattr(engine.ai,'settings',None)
        # Planning uses the durable planner's per-call deadline (60s by default).
        seconds=getattr(model_settings,'timeout_seconds',60)
        async with asyncio.timeout(seconds):
            plan=await engine.ai.generate(AIInput(stage='opportunity_plan',context=json.dumps({
                'opportunity':{k:getattr(identity,k) for k in IDENTITY},'recruitment_year':now().year})),
                Operation(owner,revision,'opportunity_plan'),current_revision=lambda:revision)
        result['queries']=planned_queries(plan.data,engine.settings.topic_searches,{k:getattr(identity,k) for k in IDENTITY})
        result['queries_planned']=True
    except Exception:
        return result
    finally:
        recover_responses.reset(recovery);quota_progress.reset(waiting)
    async def retrieve(topic):
        queries=result['queries'].get(topic) or []
        if not queries or result['searches_used']>=engine.settings.run_searches:return
        result['searches_used']+=1;query=queries[0]
        activity(ACTIVITIES[topic_owner(topic)])
        try:
            async with engine.slots:
                async with asyncio.timeout(engine.settings.timeout_seconds):
                    with budget_owner(owner):values=await engine.source.collect_opportunity_query(context,query,max_sources=policy(topic).urls_per_search)
            result['history'][topic]=[query]
            result['evidence'][topic]=[s.model_dump(mode='json') for s in values]
            activity('checking_sources')
        except SourceRateLimit as error:
            category=topic_owner(topic)
            result['waits'][category]=max(result['waits'].get(category,now()),now()+timedelta(seconds=error.retry_after))
        except Exception:
            return
    token=quota_progress.set(None)
    try:await asyncio.gather(*(retrieve(topic) for topic in TOPICS))
    finally:quota_progress.reset(token)
    return result
