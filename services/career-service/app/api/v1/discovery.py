"""Owned discovery conversation with automatic, resumable market research."""
from fastapi import APIRouter,Depends,Request
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.api.v1.goals import owner,request_key,identifier
from app.api.v1.reviews import view as review_view
from app.repositories.goals import GoalError,now
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
    # A fresh opening returns static copy/capabilities, not an older conversation.
    # Neither this read nor session creation launches research or invokes Gemini.
    service=engine(request)
    if fresh:return {'available':(await view(service,None))['available'],'session':None,'introduction':INTRODUCTION}
    return await view(service,await thread(service.current,account))

@router.post('',response_model=DiscoveryView,response_model_exclude_unset=True)
async def start(body:StartDiscovery,request:Request,account=Depends(owner),key=Depends(request_key)):
    service=engine(request);return await view(service,await thread(service.start,account,key))

@router.get('/{session_id}',response_model=DiscoveryView,response_model_exclude_unset=True)
async def get(session_id:str,request:Request,account=Depends(owner)):
    service=engine(request);row=await thread(service.get,identifier(session_id),account)
    if row['status'] in ('researching','waiting'):service.launch(row['_id'])
    return await view(service,row)

@router.post('/{session_id}/messages',response_model=DiscoveryView,response_model_exclude_unset=True)
async def message(session_id:str,body:DiscoveryMessage,request:Request,account=Depends(owner),key=Depends(request_key)):
    service=engine(request);row=await service.converse(identifier(session_id),account,key,body)
    if row['status'] in ('researching','waiting'):service.launch(row['_id'])
    return await view(service,row)

@router.post('/{session_id}/research',status_code=202,response_model=DiscoveryView,response_model_exclude_unset=True)
async def research(session_id:str,body:ResearchDiscovery,request:Request,account=Depends(owner),key=Depends(request_key)):
    service=engine(request);row=await thread(service.begin,identifier(session_id),account,key,body)
    service.launch(row['_id']);return await view(service,row)
