"""One live career goal/chat per account. Drafts publish automatically."""
import json
from bson import ObjectId
from pydantic import Field
from fastapi import APIRouter,Depends,Request
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool as thread
from app.api.v1.goals import owner,request_key
from app.api.v1.reviews import view
from app.ai.adapter import Operation
from app.ai.contracts import AIInput,Message
from app.repositories.goals import GoalError,fingerprint,stable_id,now
from app.schemas.analysis import Contract
from app.schemas.jd import JDSource,SaveReview,ChatText
from app.schemas.workspace import WorkspaceView

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
        'retry_after':w.get('retry_after'),'expires_at':w.get('expires_at'),'exploration_id':w.get('exploration_id')},by_alias=True)

@router.get('',response_model=WorkspaceView)
async def read(request:Request,account=Depends(owner)):
    value=await state(request,account)
    if value['phase'] in ('research_pending','researching','waiting_quota'):request.app.state.workflow.launch(account)
    return value

@router.post('/jd',status_code=202,response_model=WorkspaceView)
async def ingest(body:JDSource,request:Request,account=Depends(owner),key=Depends(request_key)):
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
    conversation:list[Message]=Field(default_factory=list,max_length=12)

@router.post('/messages')
async def message(body:Chat,request:Request,account=Depends(owner)):
    repo=store(request);row=await thread(repo.check,account,body.session_id,body.expected_version);w=row['workspace']
    if w.get('expires_at',now())<=now():raise GoalError('Temporary workflow expired. Resume your saved career goal.')
    if w['phase']!='ready' or not w.get('research_id'):raise GoalError('Interview research must finish before the agent can answer. Retry research first.')
    from app.workflows.chat import focused_chat
    answer=await focused_chat(request,account,row,body)
    if answer is not None:
        await thread(repo.check,account,body.session_id,body.expected_version)
        await thread(repo.touch,account,body.session_id)
        return answer.model_dump(mode='json')
    # Explicit skill edits retain the separate, fully validated edit contract.
    review=await thread(repo.reviews.get,w['review_id'],account)
    context={'career_goal':review.content.model_dump(mode='json')}
    from app.api.v1.jd import validate_skills
    from app.workflows.chat import review_chat
    def validate(output):
        if output.proposed_skills is None:return
        normalized=[]
        facts=('name','category','priority','required_proficiency','required_experience_months')
        for skill in output.proposed_skills:
            if skill.origin=='employer':
                matches=[s for s in review.content.skills if s.origin=='employer' and all(getattr(s,f)==getattr(skill,f) for f in facts)]
                if len(matches)!=1:raise GoalError('The assistant proposed an unsupported employer requirement. Retry.',503)
                normalized.append(matches[0].model_copy(deep=True))
            else:normalized.append(skill)
        output.proposed_skills=normalized
        validate_skills(output.proposed_skills,body.message,review.content.skills)
    result=await review_chat(lambda:request.app.state.ai.generate(AIInput(stage='workspace_chat',context=json.dumps(context),conversation=[Message(role='user',content=body.message)]),
        Operation(account,str(review.version),'workspace_chat'),current_revision=lambda:str(review.version),validate_output=validate),validate)
    validate(result.data)
    await thread(repo.check,account,body.session_id,body.expected_version)
    # A chat answer itself is temporary; applying an edit publishes a new goal version.
    await thread(repo.touch,account,body.session_id)
    return result.data.model_dump(mode='json')

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
