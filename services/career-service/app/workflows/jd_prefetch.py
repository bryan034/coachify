"""Transient public-only retrieval alongside full JD extraction; never persists raw JD."""
import asyncio
from datetime import timedelta
from app.clients.search_sources import SourceRateLimit
from app.ai.waiting import quota_progress
from app.repositories.goals import now
from app.schemas.analysis import ResearchContext
from app.schemas.opportunity import CATEGORIES
from app.workflows.activity import activity

from app.ai.adapter import Operation
from app.ai.contracts import AIInput
from app.ai.recovery import recover_responses
from app.workflows.opportunity.queries import ACTIVITIES,planned_queries
import json

IDENTITY=('role','field','company','location','seniority_level','employment_type')

def matches(identity,goal):
    # The inferred job-family label is not part of the retrieval query; every
    # employer/title/location/position value actually used in that query must match.
    def normalized(value):return ' '.join((value or '').casefold().split())
    return all(normalized(getattr(identity,k))==normalized(getattr(goal,k)) for k in IDENTITY if k!='field')

async def prefetch(engine,identity,owner,revision):
    context=ResearchContext(**{k:(identity.field or identity.role) if k=='field' else getattr(identity,k) for k in IDENTITY if k!='employment_type'})
    result={'queries':{category:[] for category in CATEGORIES},'history':{},'evidence':{},'waits':{},'source_provider':getattr(engine.source,'provider','brave')}
    # Plan before retrieval while full JD extraction proceeds independently.
    # If planning fails, the durable job retries; never substitute template queries.
    recovery=recover_responses.set(False)
    waiting=quota_progress.set(None)
    activity('planning_research')
    try:
        model_settings=getattr(engine.ai,'settings',None)
        seconds=model_settings.timeout_seconds if getattr(model_settings,'provider',None)=='local' else engine.settings.timeout_seconds
        async with asyncio.timeout(seconds):
            plan=await engine.ai.generate(AIInput(stage='opportunity_plan',context=json.dumps({
                'opportunity':{k:getattr(identity,k) for k in IDENTITY},'recruitment_year':now().year})),
                Operation(owner,revision,'opportunity_plan'),current_revision=lambda:revision)
        result['queries']=planned_queries(plan.data,engine.settings.max_searches)
        result['queries_planned']=True
    except Exception:
        return result
    finally:
        recover_responses.reset(recovery);quota_progress.reset(waiting)
    async def retrieve(category):
        stage=ACTIVITIES[category];query=result['queries'][category][0]
        activity(stage)
        try:
            async with engine.slots:
                async with asyncio.timeout(engine.settings.timeout_seconds):
                    values=await engine.source.collect_opportunity_query(context,query)
            result['history'][category]=[query]
            result['evidence'][category]=[s.model_dump(mode='json') for s in values]
            activity('checking_sources')
        except SourceRateLimit as error:
            result['waits'][category]=now()+timedelta(seconds=error.retry_after)
        except Exception:
            # A speculative retrieval cannot fail JD saving. The durable worker
            # owns normal bounded retry/quota handling after the goal is saved.
            return
    token=quota_progress.set(None)
    try:await asyncio.gather(*(retrieve(category) for category in CATEGORIES))
    finally:quota_progress.reset(token)
    return result
