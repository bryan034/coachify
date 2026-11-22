"""Transient public-only retrieval alongside full JD extraction; never persists raw JD."""
from elo_shared.model_budget import budget_owner
import asyncio
from datetime import timedelta
from app.clients.search_sources import SourceRateLimit
from app.ai.waiting import quota_progress
from app.repositories.goals import now, GoalError
from app.schemas.analysis import ResearchContext
from app.workflows.activity import activity

from app.ai.adapter import Operation
from app.ai.contracts import AIInput
from app.ai.recovery import recover_responses
from app.workflows.opportunity.queries import ACTIVITIES,planned_queries,topic_queries
from app.workflows.opportunity.topics import GROUP_CANDIDATES,GROUPS,owner as topic_owner
import json
import httpx
from app.ai.errors import AIError
from app.ai.metrics import COUNTERS,usage_observer

IDENTITY=('role','field','company','location','seniority_level','employment_type')

def matches(identity,goal):
    # Every employer/title/location/position value used in the retrieval query must match.
    def normalized(value):return ' '.join((value or '').casefold().split())
    return all(normalized(getattr(identity,k))==normalized(getattr(goal,k)) for k in IDENTITY if k!='field')

async def prefetch(engine,identity,owner,revision):
    context=ResearchContext(**{k:(identity.field or identity.role) if k=='field' else getattr(identity,k) for k in IDENTITY if k!='employment_type'})
    result={'queries':{},'group_queries':{},'group_history':{},'evidence':{},'waits':{},'searches_used':0,'metrics':{}}
    def record(stage,usage,**counts):
        metrics=result['metrics'].setdefault(stage,{})
        for name in COUNTERS:
            count=sum(v.get(name,0) for v in usage)
            if count:counts[name]=count
        for name,count in counts.items():metrics[name]=metrics.get(name,0)+count
    provider=getattr(engine.source,'provider',None)
    if provider:result['source_provider']=provider
    # Plan before retrieval while full JD extraction proceeds independently.
    recovery=recover_responses.set(False)
    waiting=quota_progress.set(None)
    activity('planning_research')
    usage=[];observer=usage_observer.set(usage.append)
    try:
        model_settings=getattr(engine.ai,'settings',None)
        # Planning uses the durable planner's per-call deadline (60s by default).
        seconds=getattr(model_settings,'timeout_seconds',60)
        async with asyncio.timeout(seconds):
            plan=await engine.ai.generate(AIInput(stage='opportunity_plan',context=json.dumps({
                'opportunity':{k:getattr(identity,k) for k in IDENTITY},'recruitment_year':now().year})),
                Operation(owner,revision,'opportunity_plan'),current_revision=lambda:revision)
        public={k:getattr(identity,k) for k in IDENTITY}
        result['group_queries']=planned_queries(plan.data,public)
        result['queries']=topic_queries(public,engine.settings.topic_searches)
        result['queries_planned']=True
    except (AIError,GoalError,TimeoutError,ValueError):
        return result
    finally:
        usage_observer.reset(observer);record('opportunity_plan',usage,model_calls=1)
        recover_responses.reset(recovery);quota_progress.reset(waiting)
    async def retrieve(group):
        query=result['group_queries'].get(group)
        if not query or result['searches_used']>=engine.settings.run_searches:return
        result['searches_used']+=1
        activity(ACTIVITIES[topic_owner(GROUPS[group][0])])
        usage=[];observer=usage_observer.set(usage.append)
        try:
            async with engine.slots:
                async with asyncio.timeout(engine.settings.timeout_seconds):
                    with budget_owner(owner):values=await engine.source.collect_opportunity_query(context,query,max_sources=GROUP_CANDIDATES)
            result['group_history'][group]=[query]
            for topic in GROUPS[group]:result['evidence'][topic]=[s.model_dump(mode='json') for s in values]
            activity('checking_sources')
        except SourceRateLimit as error:
            for category in {topic_owner(topic) for topic in GROUPS[group]}:
                result['waits'][category]=max(result['waits'].get(category,now()),now()+timedelta(seconds=error.retry_after))
        except (AIError,GoalError,TimeoutError,ValueError,httpx.HTTPError,OSError):
            return
        finally:
            usage_observer.reset(observer);record('research_search',usage,searches=1)
    token=quota_progress.set(None)
    try:await asyncio.gather(*(retrieve(group) for group in GROUPS))
    finally:quota_progress.reset(token)
    return result
