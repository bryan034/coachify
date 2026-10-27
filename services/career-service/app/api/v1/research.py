"""J12 acquisition/reuse and J13 owner-scoped versioned evidence reads."""
import asyncio
from pymongo.errors import PyMongoError
from bson import ObjectId
from fastapi import APIRouter, Depends, Request, Query
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool
from app.api.v1.goals import owner,identifier,request_key,store as goals
from app.ai.adapter import AIError,Operation
from app.ai.contracts import AIInput
from app.domain.review import MAPPING_VERSION
from app.repositories.goals import GoalError,fingerprint,now
from app.repositories.research import FRESHNESS
from app.schemas.analysis import ResearchContext,InterviewResearch
from app.schemas.research import ResearchRequest
from app.clients.research import normalize_batch
from app.domain.interview import topics_from

router=APIRouter(prefix='/api/v1/career/goals',tags=['J12/J13 interview research'])

def context_for(goal):return ResearchContext(**{k:getattr(goal,k,None) for k in ResearchContext.model_fields})

def repository(request):
    if request.app.state.research_store is None:raise GoalError('Research storage is unavailable.',503)
    return request.app.state.research_store

def goal_for(request,account,goal_id):
    row=goals(request).goals.find_one({'_id':ObjectId(identifier(goal_id)),'user_id':account,
        'record_type':{'$nin':['exploration_draft','requirement_review']}})
    if not row:raise GoalError('Confirmed career goal was not found.',404)
    from app.schemas.analysis import CareerGoal
    return CareerGoal.model_validate({k:v for k,v in row.items() if k in CareerGoal.model_fields or k=='_id'})

def presentation(record,context,*,status=None,reused=False,historical=False):
    return {'status':status or (record.research_status if record else 'missing'),'research':record,
        'context':context,'reused':reused,'stale':bool(record and record.last_researched_at<now()-FRESHNESS),
        'historical':historical,'general':context.company is None,
        'note':'Research is preparation guidance, not a guaranteed interview question or a JD requirement. Independent report counts remain unknown where authorship cannot be verified.'}

@router.get('/{goal_id}/interview-research')
async def read(goal_id:str,request:Request,research_id:str|None=Query(default=None),account=Depends(owner)):
    goal=await run_in_threadpool(goal_for,request,account,goal_id);repo=repository(request)
    record=await run_in_threadpool(repo.read,account,goal.id,identifier(research_id) if research_id else None)
    context=context_for(goal);cache=await run_in_threadpool(repo.cache.find_one,{'_id':context.reuse_key()}) or {}
    state=await run_in_threadpool(goals(request).current,account)
    status=record.research_status if research_id and record else cache.get('status','missing')
    if status=='processing' and cache.get('lease',{}).get('expires_at',now())<=now():status='failed'
    history=await run_in_threadpool(repo.linked,account,goal.id)
    reused=await run_in_threadpool(repo.was_reused,account,goal.id,record)
    return jsonable_encoder({**presentation(record,context,status=status,reused=reused,historical=bool(research_id) or not state['goal'] or state['goal'].id!=goal.id),'history':history},by_alias=True)

@router.post('/{goal_id}/interview-research')
async def acquire(goal_id:str,body:ResearchRequest,request:Request,account=Depends(owner),key=Depends(request_key)):
    goal=await run_in_threadpool(goal_for,request,account,goal_id);repo=repository(request)
    context=context_for(goal);digest=fingerprint({'goal':goal.id,**body.model_dump()})
    previous=await run_in_threadpool(repo.replay,account,key,digest)
    if previous:return jsonable_encoder(presentation(previous,context,reused=True),by_alias=True)
    selected=await run_in_threadpool(goals(request).current,account)
    if selected['selection_version']!=body.expected_selection_version or not selected['goal'] or selected['goal'].id!=goal.id or goal.version!=body.expected_version:
        raise GoalError('Your selected goal changed. Reload before researching.')
    started=await run_in_threadpool(repo.begin,context,body.refresh)
    if started.get('processing'):
        old=await run_in_threadpool(repo.read,account,goal.id)
        return jsonable_encoder(presentation(old,context,status='processing'),by_alias=True)
    if started.get('record'):
        record=started['record']
        await run_in_threadpool(repo.attach,account,goal.id,body.expected_selection_version,key,digest,record,reused=True)
        return jsonable_encoder(presentation(record,context,reused=True),by_alias=True)
    token=started['token']
    try:
        async with asyncio.timeout(85):
            batch=normalize_batch(await request.app.state.research_client.collect(context));sources=batch.sources
            result=await request.app.state.ai.generate(AIInput(stage='interview_synthesis',public_context=context,sources=sources,summaries=batch.summaries),
                Operation(account,goal.id,'interview_synthesis'),current_revision=lambda:goal.id)
            skills=topics_from(result.data,sources,batch.summaries)
            stamp=now()
            record=InterviewResearch(_id=str(ObjectId()),version=started['version'],skill_mapping_version=MAPPING_VERSION,
                created_at=stamp,updated_at=stamp,**context.model_dump(),sources=sources,summaries=batch.summaries,skills=skills,process=result.data.process,
                research_status='succeeded' if skills or result.data.process.stages or result.data.process.round_count is not None else 'no_findings',last_researched_at=stamp,generation=result.generation)
            record=await run_in_threadpool(repo.finish,context,token,record)
            await run_in_threadpool(repo.attach,account,goal.id,body.expected_selection_version,key,digest,record)
            return jsonable_encoder(presentation(record,context),by_alias=True)
    except (GoalError,AIError,TimeoutError,ValueError,PyMongoError,asyncio.CancelledError) as error:
        await run_in_threadpool(repo.fail,context,token,'unavailable' if isinstance(error,GoalError) and error.status==503 else 'failed')
        if isinstance(error,TimeoutError):raise AIError('timeout',True) from None
        raise
