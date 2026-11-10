"""Owned discovery conversation with automatic, resumable market research."""
from fastapi import APIRouter,Depends,Request,Query
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.api.v1.goals import owner,request_key,identifier
from app.api.v1.reviews import view as review_view
from app.repositories.goals import GoalError,now
from app.schemas.goals import SaveGoal
from pydantic import BaseModel,Field
from app.schemas.discovery import StartDiscovery,DiscoveryMessage,ResearchDiscovery,DiscoveryView

from app.domain.discovery_conversation import INTRODUCTION,conversation_messages

router=APIRouter(prefix='/api/v1/career/discoveries',tags=['Career discovery'])

def engine(request):
    value=request.app.state.discovery
    if value is None:raise GoalError('Career storage is not configured.',503)
    return value

async def view(service,row):
    available=bool(getattr(service.ai,'context_enabled',False) and getattr(service.ai.settings,'enabled',False) and getattr(service.source,'configured',True))
    if row is None:return {'available':available,'session':None}
    review=await thread(service.app.state.review_store.get,row['review_id'],row['owner']) if row.get('review_id') else None
    aggregate=row.get('aggregate') or {}
    return jsonable_encoder({'available':available,'session':{
        'id':row['_id'],'version':row['version'],'status':row['status'],'stage':row.get('stage'),
        'decision':row['decision'],'scope':row.get('scope'),'related_roles':(row.get('plan') or {}).get('related_roles',[]),
        'messages':conversation_messages(row.get('messages',[])),'summary':row.get('summary'),
        'sources':row.get('sources') or [],'stats':aggregate.get('stats',[]),'warnings':aggregate.get('warnings',[]),
        'listings_analysed':len(aggregate.get('listings',[])),'employers_analysed':aggregate.get('employers',0),'coverage':aggregate.get('coverage'),
        'error_code':row.get('error_code'),'limit_scope':row.get('limit_scope'),'provider':row.get('provider'),
        'retry_after':max(0,int((row['next_attempt_at']-now()).total_seconds())) if row['status']=='waiting' else None,
        'review':review_view(review) if review else None}},by_alias=True)

@router.get('/current',response_model=DiscoveryView,response_model_exclude_unset=True)
async def current(request:Request,fresh:bool=False,account=Depends(owner)):
    """Restore the owner's latest saved chat; empty chats include display-only copy.

    The legacy fresh flag returns display-only copy without changing the saved chat.
    No model or research calls are made by this read.
    """
    service=engine(request)
    if fresh:return {'available':(await view(service,None))['available'],'session':None,'introduction':INTRODUCTION}
    row=await thread(service.current,account)
    result=await view(service,row)
    if row is None or not conversation_messages(row.get('messages',[])):result['introduction']=INTRODUCTION
    return result

@router.post('',response_model=DiscoveryView,response_model_exclude_unset=True)
async def start(body:StartDiscovery,request:Request,account=Depends(owner),key=Depends(request_key)):
    """Persist a distinct empty chat immediately; retries with the same key reuse it."""
    service=engine(request)
    result=await view(service,await thread(service.start,account,key))
    if not result['session']['messages']:result['introduction']=INTRODUCTION
    return result

class PublishDiscovery(BaseModel):
    expected_version:int=Field(ge=1)
    expected_selection_version:int=Field(ge=0)

@router.get('')
async def sessions(request:Request,before:str|None=None,limit:int=Query(20,ge=1,le=50),account=Depends(owner)):
    service=engine(request)
    query={'owner':account,'kind':'career_discovery'}
    if before:
        anchor=await thread(service.get,identifier(before),account)
        query['$or']=[{'updated_at':{'$lt':anchor['updated_at']}},{'updated_at':anchor['updated_at'],'_id':{'$lt':anchor['_id']}}]
    rows=await thread(lambda:list(service.rows.find(query).sort([('updated_at',-1),('_id',-1)]).limit(limit+1)))
    items=[{'id':row['_id'],'version':row['version'],'status':row['status'],'title':(row.get('scope') or {}).get('area') or 'Career discovery',
            'last_message':(conversation_messages(row.get('messages',[])) or [{}])[-1].get('content',''),'updated_at':row['updated_at']} for row in rows[:limit]]
    return jsonable_encoder({'items':items,'next_cursor':rows[limit-1]['_id'] if len(rows)>limit else None})

@router.post('/{session_id}/publish',response_model=DiscoveryView,response_model_exclude_unset=True)
async def publish(session_id:str,body:PublishDiscovery,request:Request,account=Depends(owner),key=Depends(request_key)):
    service=engine(request);row=await thread(service.get,identifier(session_id),account)
    if row['version']!=body.expected_version:raise GoalError('This discovery changed. Reload it before replacing your goal.')
    if row.get('stage')!='awaiting_goal_confirmation':
        if row.get('published_key')==key:return await view(service,row)
        raise GoalError('There is no completed direction awaiting confirmation.')
    review=await thread(service.app.state.review_store.get,row['review_id'],account)
    content=review.content
    command=SaveGoal(target_type='career_exploration',role=content.role,field=content.field,company=None,
        job_url=None,location=content.location,seniority_level=content.seniority_level,employment_type=content.employment_type,
        review_id=review.id,expected_review_version=review.version,expected_selection_version=body.expected_selection_version,replace_current=True)
    goal=await thread(service.app.state.review_store.goal,review,account,key,command,allow_pending_context=True)
    await thread(service.app.state.goal_store.confirm,account,key,command,goal,discovery_id=row['_id'])
    await thread(service.rows.update_one,{'_id':row['_id'],'owner':account,'version':body.expected_version},
        {'$set':{'stage':'career_goal_updated','published_key':key,'updated_at':now()},'$inc':{'version':1},
         '$push':{'messages':{'role':'assistant','content':'Your Career Goal has been replaced with this direction.'}}})
    return await view(service,await thread(service.get,row['_id'],account))

@router.get('/{session_id}',response_model=DiscoveryView,response_model_exclude_unset=True)
async def get(session_id:str,request:Request,account=Depends(owner)):
    service=engine(request);row=await thread(service.get,identifier(session_id),account)
    if row['status'] in ('researching','waiting'):service.launch(row['_id'])
    result=await view(service,row)
    if not result['session']['messages']:result['introduction']=INTRODUCTION
    return result

@router.post('/{session_id}/messages',response_model=DiscoveryView,response_model_exclude_unset=True)
async def message(session_id:str,body:DiscoveryMessage,request:Request,account=Depends(owner),key=Depends(request_key)):
    """Converse/refine; validated synthesis updates this chat's own goal, but replacing another goal awaits /publish."""
    service=engine(request);row=await service.converse(identifier(session_id),account,key,body)
    if row['status'] in ('researching','waiting'):service.launch(row['_id'])
    return await view(service,row)

@router.post('/{session_id}/research',status_code=202,response_model=DiscoveryView,response_model_exclude_unset=True)
async def research(session_id:str,body:ResearchDiscovery,request:Request,account=Depends(owner),key=Depends(request_key)):
    service=engine(request);row=await thread(service.begin,identifier(session_id),account,key,body)
    service.launch(row['_id']);return await view(service,row)
