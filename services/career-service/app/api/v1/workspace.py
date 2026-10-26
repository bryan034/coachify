"""One live career goal/chat per account. Drafts publish automatically."""
from uuid import uuid4
from typing import Literal
from bson import ObjectId
from pydantic import Field
from fastapi import APIRouter,Depends,Request,Response,Header
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.api.v1.goals import owner,request_key
from app.api.v1.reviews import view
from app.ai.contracts import Message
from app.repositories.goals import GoalError,fingerprint,stable_id,now
from app.schemas.analysis import Contract
from app.schemas.jd import JDSource,SaveReview,ChatText
from app.schemas.workspace import WorkspaceView,OperationView,WorkspaceChatReply

router=APIRouter(prefix='/api/v1/career/workspace',tags=['Single career workspace / LangGraph'])

def store(request):
    if request.app.state.workspace_store is None:raise GoalError('Career storage is unavailable.',503)
    return request.app.state.workspace_store

async def state(request,account):
    repo=store(request);row=await thread(repo.row,account);w=row.get('workspace',{})
    # Adopt an existing active goal once, without exposing a session chooser.
    if not w and row.get('goal_id'):
        review=await thread(repo.reviews.get,str(row['goal_id']),account)
        await thread(repo.rows.update_one,{'_id':account,'workspace':{'$exists':False}},{'$set':{'workspace':{
            'session_id':str(row['goal_id']),'kind':'jd' if review.target_type=='specific_job' else 'exploration','review_id':review.id,
            'revision':review.version,'run_id':str(ObjectId()),'phase':'research_pending','expires_at':now()}}})
        row=await thread(repo.row,account);w=row.get('workspace',{})
    review=await thread(repo.reviews.get,w['review_id'],account) if w.get('review_id') else None
    current=await thread(repo.goals.current,account)
    research=None
    if w.get('research_id') and current['goal']:
        record=await thread(request.app.state.research_store.read,account,current['goal'].id,w['research_id'])
        if record:research=record
    expired=bool(w and w.get('expires_at',now())<=now())
    return jsonable_encoder({'session_id':w.get('session_id'),'revision':w.get('revision',0),'kind':w.get('kind'),
        'phase':'expired' if expired else w.get('phase','empty'),'review':view(review) if review else None,
        'current':current,'research':research,'coverage':w.get('coverage',[]),'error':w.get('error'),'error_code':w.get('error_code'),
        'edit_question':(w.get('edit_draft') or {}).get('question'),'retry_after':w.get('retry_after'),'expires_at':w.get('expires_at'),'exploration_id':w.get('exploration_id')},by_alias=True)

@router.get('',response_model=WorkspaceView)
async def read(request:Request,account=Depends(owner)):
    value=await state(request,account)
    if value['phase'] in ('research_pending','researching','waiting_quota'):request.app.state.workflow.launch(account)
    return value

@router.post('/jd',status_code=202,response_model=WorkspaceView|OperationView)
async def ingest(body:JDSource,request:Request,account=Depends(owner),key=Depends(request_key),prefer:str|None=Header(default=None,alias='Prefer')):
    if prefer == 'respond-async':
        return request.app.state.operations.submit(account,key,fingerprint(body.model_dump(mode='json')),'jd',
            lambda: ingest_jd(body,request,account,key))
    return await ingest_jd(body,request,account,key)

async def ingest_jd(body,request,account,key):
    repo=store(request);digest=fingerprint(body.model_dump(mode='json'))
    if not await thread(repo.claim_input,account,key,digest):return await state(request,account)
    try:
        result=await request.app.state.workflow.extract(body,account,key)
        review=await thread(repo.reviews.create,account,key,digest,result.data,result.generation,'url' if body.source_url else body.source_kind)
        await thread(repo.activate,account,stable_id(account,key,'workspace'),review,input_key=key,digest=digest)
    except BaseException:
        await thread(repo.rows.update_one,{'_id':account,'incoming.key':key},{'$unset':{'incoming':''}})
        raise
    request.app.state.workflow.launch(account,replace=True)
    return await state(request,account)

class WorkspaceEdit(SaveReview):
    session_id:str=Field(pattern=r'^[0-9a-f]{24}$')

@router.patch('/review',response_model=WorkspaceView)
async def edit(body:WorkspaceEdit,request:Request,account=Depends(owner),key=Depends(request_key)):
    repo=store(request);row=await thread(repo.row,account);w=row.get('workspace',{})
    if not w.get('review_id'):raise GoalError('Add a job description or explore a role first.',404)
    await thread(repo.check,account,body.session_id)
    if body.content and (not body.content.role or not body.content.field):
        raise GoalError('Keep a role and field in your career goal before saving.',422)
    command=SaveReview.model_validate(body.model_dump(exclude={'session_id'}))
    review=await thread(repo.reviews.save,w['review_id'],account,key,command)
    updated=await thread(repo.activate,account,w['session_id'],review)
    request.app.state.workflow.launch(account,replace=updated['workspace']['run_id']!=w['run_id'])
    return await state(request,account)

class Chat(Contract):
    session_id:str=Field(pattern=r'^[0-9a-f]{24}$')
    expected_version:int=Field(strict=True,ge=1)
    message:ChatText=Field(max_length=600)
    mode:Literal['question','refine']='question'
    conversation:list[Message]=Field(default_factory=list,max_length=12)

@router.post('/messages',response_model=WorkspaceChatReply|OperationView,responses={202:{'model':OperationView}})
async def message(body:Chat,request:Request,response:Response,account=Depends(owner),prefer:str|None=Header(default=None,alias='Prefer'),idempotency_key:str|None=Header(default=None,alias='Idempotency-Key')):
    if prefer == 'respond-async':
        key=request_key(idempotency_key or '')
        response.status_code=202
        return request.app.state.operations.submit(account,key,fingerprint(body.model_dump(mode='json')),'chat',
            lambda: answer_message(body,request,account,key))
    return await answer_message(body,request,account,request_key(idempotency_key) if idempotency_key else str(uuid4()))

@router.get('/operations/{operation_id}',response_model=OperationView)
async def operation(operation_id:str,request:Request,account=Depends(owner)):
    return request.app.state.operations.read(account,operation_id)

async def answer_message(body,request,account,key):
    repo=store(request);digest=fingerprint(body.model_dump(mode='json'))
    if await thread(repo.chat_replay,account,key,digest,body.session_id):
        return {'reply':'Your requested career goal changes have already been saved.','proposed_skills':None,'edit_status':'saved','workspace':await state(request,account)}
    row=await thread(repo.check,account,body.session_id,body.expected_version);w=row['workspace']
    if w.get('expires_at',now())<=now():raise GoalError('Temporary workflow expired. Resume your saved career goal.')
    answer=None
    if body.mode!='refine':
        if w['phase']!='ready' or not w.get('research_id'):raise GoalError('Interview research must finish before the agent can answer. Retry research first.')
        from app.workflows.chat import focused_chat
        answer=await focused_chat(request,account,row,body)
    if answer is not None:
        await thread(repo.check,account,body.session_id,body.expected_version)
        await thread(repo.touch,account,body.session_id)
        return answer.model_dump(mode='json')
    from app.workflows.chat import edit_goal
    from app.domain.goal_edits import apply_changes
    from app.domain.questions import REFUSAL
    decision,review=await edit_goal(request,account,row,body)
    await thread(repo.check,account,body.session_id,body.expected_version)
    if decision.status=='off_topic':
        return {'reply':REFUSAL,'proposed_skills':None}
    if decision.status=='clarify':
        draft={'intent':decision.intent,'changes':[c.model_dump(mode='json') for c in decision.changes],
            'question':decision.reply[:600],'version':body.expected_version}
        await thread(repo.edit_draft,account,body.session_id,body.expected_version,draft)
        await thread(repo.touch,account,body.session_id)
        return {'reply':decision.reply,'proposed_skills':None,'edit_status':'clarifying'}
    if decision.status=='cancel':
        await thread(repo.edit_draft,account,body.session_id,body.expected_version,None)
        return {'reply':decision.reply,'proposed_skills':None,'edit_status':'cancelled'}
    content=apply_changes(review.content,decision.changes,decision.intent)
    updated=await thread(repo.reviews.save,review.id,account,key,SaveReview(expected_version=body.expected_version,
        content=content,acknowledge_context=decision.acknowledge_context))
    if updated.version!=review.version:
        await thread(repo.activate,account,body.session_id,updated,chat_receipt={'key':key,'hash':digest})
        request.app.state.workflow.launch(account,replace=True)
    else:
        await thread(repo.edit_draft,account,body.session_id,body.expected_version,None)
        # The requested values already match the goal; do not create another version.
        await thread(repo.rows.update_one,{'_id':account,'workspace.session_id':body.session_id},
            {'$push':{'chat_receipts':{'$each':[{'key':key,'hash':digest}],'$slice':-100}}})
    await thread(repo.touch,account,body.session_id)
    return {'reply':decision.reply,'proposed_skills':None,'edit_status':'saved','workspace':await state(request,account)}

@router.post('/retry',status_code=202,response_model=WorkspaceView)
async def retry(request:Request,account=Depends(owner)):
    repo=store(request);row=await thread(repo.row,account);w=row.get('workspace',{})
    if not w.get('review_id'):raise GoalError('No saved career goal is available.',404)
    restarted=False
    if w.get('phase') not in ('research_pending','researching','waiting_quota') or w.get('expires_at',now())<=now():
        restarted=True
        await thread(repo.phase,account,w['session_id'],w['run_id'],'research_pending',run_id=str(ObjectId()),error=None,retry_after=None)
    await thread(repo.touch,account,w['session_id'])
    request.app.state.workflow.launch(account,replace=restarted)
    return await state(request,account)

class Direction(Contract):
    expected_version:int=Field(strict=True,ge=1)
    index:int=Field(strict=True,ge=0,le=4)

@router.post('/direction',status_code=202,response_model=WorkspaceView)
async def direction(body:Direction,request:Request,account=Depends(owner),key=Depends(request_key)):
    repo=store(request);row=await thread(repo.row,account);w=row.get('workspace',{})
    if w.get('kind')!='exploration' or not w.get('exploration_id'):raise GoalError('Start career exploration first.')
    draft=await thread(repo.goals.draft,w['exploration_id'],account)
    if draft.version!=body.expected_version or draft.next_question() or body.index>=len(draft.suggestions):raise GoalError('The available directions changed. Reload the conversation.')
    suggestion=draft.suggestions[body.index]
    if w.get('review_id'):return await state(request,account)
    from app.schemas.analysis import CareerGoal,mongo_document
    from app.schemas.jd import JDExtraction
    stamp=now()
    goal=CareerGoal(_id=stable_id(account,key,'exploration-context'),user_id=account,version=1,skill_mapping_version='skills-v1',
        created_at=stamp,updated_at=stamp,target_type='career_exploration',field=suggestion.field,role=suggestion.role,
        interests=draft.interests,preferences=draft.preferences,skills=[],requirements_source='career_exploration',
        generation_version='pending-skills',generation=draft.generation,readiness='pending',exploration_draft_id=draft.id,exploration_draft_version=draft.version,
        source_cv_id=draft.cv.cv_id,source_cv_version=draft.cv.version,source_extraction_version=draft.cv.extraction_version,source_profile_version=draft.cv.profile_version)
    from pymongo.errors import DuplicateKeyError
    try:await thread(repo.goals.goals.insert_one,mongo_document(goal))
    except DuplicateKeyError:pass
    content=JDExtraction(role=goal.role,field=goal.field,company=None,skills=[])
    review=await thread(repo.reviews.create_guidance,account,key,fingerprint(body.model_dump()),goal,content,draft.generation)
    await thread(repo.activate,account,w['session_id'],review)
    await thread(repo.touch,account,w['session_id'])
    request.app.state.workflow.launch(account,replace=True)
    return await state(request,account)
