"""J08/J09 authenticated orchestration; raw CV buffers never enter repositories."""
import hashlib
import json
import asyncio
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool
from app.ai.adapter import AIError, Operation
from app.workflows.exploration import exploration_turn
from app.ai.contracts import AIInput, Message
from app.core.auth import bearer, current_account
from app.repositories.goals import GoalError, fingerprint, now
from app.schemas.analysis import object_id
from app.schemas.goals import Answer, AssessmentStatus, CvContext, GoalDraft, QUESTIONS, SaveGoal, SendAnswer, StartExploration, Turn

router=APIRouter(prefix='/api/v1/career', tags=['J08 exploration / J09 goal confirmation'])


async def owner(request: Request, credentials=Depends(bearer)):
    return await current_account(request, credentials)


def store(request):
    if request.app.state.goal_store is None:
        raise GoalError('Career storage is not configured. Check the setup guide.',503)
    return request.app.state.goal_store


def request_key(idempotency_key: str = Header(alias='Idempotency-Key')):
    try:
        if str(UUID(idempotency_key)) != idempotency_key: raise ValueError
    except ValueError: raise HTTPException(422,'Use a unique UUID Idempotency-Key for this action.') from None
    return idempotency_key


def identifier(value):
    try: return object_id(value)
    except ValueError: raise HTTPException(404,'This record was not found.') from None


def draft_view(draft):
    return {**draft.model_dump(mode='json',by_alias=True), 'suggestions': [s.model_dump(mode='json') for s in draft.suggestions] if draft.next_question() is None else [], 'next_question':draft.next_question(),
            'question_text':draft.agent_question, 'context_complete':draft.next_question() is None}


async def selected_cv(request, cv_id, account):
    if request.app.state.cv is None:
        raise GoalError('The CV service is unavailable. Retry or continue without a CV.',503)
    return await request.app.state.cv.get(cv_id, request.headers.get('authorization',''), account)


@router.get('/context')
async def context(request: Request, account=Depends(owner)):
    items=[]; available=True
    if request.app.state.cv is None: available=False
    else:
        try:
            cvs=await request.app.state.cv.list(request.headers.get('authorization',''))
            items=[{'id':cv.id,'filename':cv.file_name,'status':cv.extraction_status,
                    'version':cv.version,'extraction_version':cv.extraction_version} for cv in cvs if cv.user_id in (None,account)]
        except GoalError: available=False
    return {'cvs':items, 'cv_service_available':available,
            'ai_available':request.app.state.ai.settings.enabled}


@router.get('/context/assessment', response_model=AssessmentStatus)
async def assessment_status(request: Request, account=Depends(owner)):
    """Read readiness through CV's owner API; a successful empty CV is not assessed."""
    cv_client=request.app.state.cv
    uploaded=None
    try:
        if cv_client is None:raise GoalError('CV service unavailable.',503)
        token=request.headers.get('authorization','')
        # Saved-CV summaries are already scoped by the forwarded session and omit
        # owner metadata. Detail reads below still verify the exact owner.
        rows=[cv for cv in (await cv_client.list(token))[:50] if cv.user_id in (None,account)]
        uploaded=bool(rows)
        if not rows:return AssessmentStatus(status='no_cv',cv_uploaded=False,skills_evaluated=False)
        ready=[cv for cv in rows if cv.extraction_status=='succeeded']
        # Inspect at most four snapshots concurrently, without returning their private evidence.
        failed=False
        for offset in range(0,len(ready),4):
            snapshots=await asyncio.gather(*(cv_client.get(cv.id,token,account) for cv in ready[offset:offset+4]),return_exceptions=True)
            if any(not isinstance(cv,BaseException) and cv.user_id==account and cv.extraction_status=='succeeded' and cv.skills for cv in snapshots):
                return AssessmentStatus(status='evaluated',cv_uploaded=True,skills_evaluated=True)
            failed=failed or any(isinstance(cv,BaseException) for cv in snapshots)
        if failed:raise GoalError('CV service unavailable.',503)
        return AssessmentStatus(status='not_evaluated',cv_uploaded=True,skills_evaluated=False)
    except GoalError:
        return AssessmentStatus(status='unavailable',cv_uploaded=uploaded,skills_evaluated=None)


@router.post('/explorations')
async def start(body: StartExploration, request: Request, account=Depends(owner), key=Depends(request_key)):
    workspace=getattr(request.app.state,'workspace_store',None)
    if workspace:
        active=(await run_in_threadpool(workspace.row,account)).get('workspace',{})
        if active.get('exploration_id') and active.get('kind')=='exploration' and not active.get('review_id'):
            existing=await run_in_threadpool(store(request).draft,active['exploration_id'],account)
            if body.cv_id!=existing.cv.cv_id or body.temporary_filename!=(existing.cv.filename if existing.cv.mode=='temporary' else None):
                raise GoalError('The current conversation already has its CV context. Continue it instead of creating another session.')
            return draft_view(existing)
        if active.get('review_id'):raise GoalError('Continue your existing career conversation, or import a new JD to replace it.')
    cv_context=CvContext()
    if body.cv_id:
        cv=await selected_cv(request,body.cv_id,account)
        cv_context=CvContext(mode='saved',cv_id=cv.id,filename=cv.file_name,version=cv.version,extraction_version=cv.extraction_version,profile_version=cv.profile_version)
    elif body.temporary_filename:
        cv_context=CvContext(mode='temporary',filename=body.temporary_filename)
    draft=await run_in_threadpool(store(request).start,account,key,body.model_dump(mode='json'),cv_context)
    if workspace:
        from datetime import timedelta
        await run_in_threadpool(workspace.rows.update_one,{'_id':account},{'$setOnInsert':{'version':0,'goal_id':None,'receipts':[]},
            '$set':{'workspace':{'session_id':draft.id,'kind':'exploration','exploration_id':draft.id,'revision':draft.version,'phase':'exploring',
                'run_id':draft.id,'expires_at':now()+timedelta(hours=24)}}},upsert=True)
    return draft_view(draft)


@router.get('/explorations/{draft_id}')
async def get_draft(draft_id: str, request: Request, account=Depends(owner)):
    return draft_view(await run_in_threadpool(store(request).draft,identifier(draft_id),account))


@router.post('/explorations/{draft_id}/messages')
async def answer(draft_id: str, body: SendAnswer, request: Request, account=Depends(owner), key=Depends(request_key)):
    identifier(draft_id)
    workspace=getattr(request.app.state,'workspace_store',None)
    if workspace:
        active=(await run_in_threadpool(workspace.row,account)).get('workspace',{})
        if active and (active.get('exploration_id')!=draft_id or active.get('review_id')):raise GoalError('This conversation has been replaced. Open your current career goal.')
    repository=store(request)
    digest=fingerprint(body.model_dump(mode='json'))
    replay=await run_in_threadpool(repository.replay_turn,draft_id,account,key,digest)
    if replay: return draft_view(replay)
    draft=await run_in_threadpool(repository.claim_turn,draft_id,account,body.expected_version,key,digest)
    try:
        cv_data=None
        if draft.cv.mode=='saved':
            cv=await selected_cv(request,draft.cv.cv_id,account)
            if cv.version!=draft.cv.version or cv.extraction_version!=draft.cv.extraction_version or cv.profile_version!=draft.cv.profile_version:
                raise GoalError('Your CV changed. Start a fresh exploration with its latest version.')
            cv_data={'skills':[s.model_dump(mode='json') for s in cv.skills], 'profile_version':cv.profile_version}
        if draft.cv.mode=='temporary':
            if not body.attachment_text: raise GoalError('Reattach your temporary CV to continue, or start without it.',422)
            checksum=hashlib.sha256(body.attachment_text.encode()).hexdigest()
            if draft.cv.attachment_sha256 and checksum!=draft.cv.attachment_sha256:
                raise GoalError('The temporary CV changed. Start a new exploration to use it.')
            draft.cv.attachment_sha256=checksum
            cv_data={'temporary_cv_text':body.attachment_text,
                     'limitation':'Career-goal model, not dedicated current-skill extraction. Ask for personal contribution; no inferred proficiency.'}
        elif body.attachment_text:
            raise GoalError('Start a new exploration to change its CV context.',422)
        question=draft.next_question()
        declared=Answer(status='skipped' if body.skip else 'answered',value=None if body.skip else body.answer)
        if body.skip and question:
            draft.answers[question]=Answer(status='skipped',value=None)
        payload={'answers':{k:v.model_dump(mode='json') for k,v in draft.answers.items()},
                 'required_topics':list(QUESTIONS),
                 'unresolved_topics':[k for k in QUESTIONS if k not in draft.answers or draft.answers[k].status=='partial'],
                 'current_focus':question, 'explicit_skip':question if body.skip else None,
                 'previous_interests':draft.interests,'previous_preferences':draft.preferences,
                 'previous_suggestions':[r.model_dump(mode='json') for r in draft.suggestions], 'cv_context':cv_data}
        messages=[]
        for turn in draft.turns[-12:]:
            messages.extend([Message(role='user',content=turn.answer.value or 'I explicitly skipped that question.'),
                             Message(role='assistant',content=turn.reply)])
        messages.append(Message(role='user',content=body.answer or 'I am unsure; skip this question.'))
        ai_request=AIInput(stage='exploration',context=json.dumps(payload,ensure_ascii=False),conversation=messages)
        op=Operation(account,str(body.expected_version),'exploration')
        result=await exploration_turn(lambda:request.app.state.ai.generate(ai_request,op,current_revision=lambda:str(body.expected_version)))
        # Check mutable external CV inputs again before committing.
        if draft.cv.mode=='saved':
            latest=await selected_cv(request,draft.cv.cv_id,account)
            if latest.version!=draft.cv.version or latest.extraction_version!=draft.cv.extraction_version or latest.profile_version!=draft.cv.profile_version:
                raise GoalError('Your CV changed while generating. Please start a fresh exploration.')
        output=result.data
        # The model can interpret multiple topics from one message, but cannot
        # mark a question complete merely because it was asked. Each update must
        # cite the current human message; no CV text or model answer counts as a declaration.
        for update in output.context_updates:
            if body.skip or update.quote not in (body.answer or ''):
                raise AIError('invalid_output',True)
            draft.answers[update.topic]=Answer(status='skipped' if update.status=='unknown' else update.status,
                value=update.value,quote=update.quote)
        missing=[k for k in QUESTIONS if k not in draft.answers or draft.answers[k].status=='partial']
        if missing and (output.focus not in missing or not output.follow_up):
            raise AIError('invalid_output',True)
        draft.focus=output.focus if output.focus in missing else (missing[0] if missing else None)
        draft.agent_question=output.follow_up
        draft.interests=output.interests; draft.preferences=output.preferences
        draft.suggestions=output.suggestions if not missing else []
        message=output.reply + ('\n\n'+output.follow_up if output.follow_up else '')
        draft.total_turns=max(draft.total_turns,len(draft.turns))+1
        draft.turns=([*draft.turns,Turn(question=question or 'refinement',answer=declared,reply=message)])[-30:]
        draft.generation=result.generation
        draft.version+=1; draft.updated_at=now()
        draft=GoalDraft.model_validate(draft)
        await run_in_threadpool(repository.finish_turn,draft,account,body.expected_version,key,digest)
        if workspace: await run_in_threadpool(workspace.touch,account,draft.id)
        return draft_view(draft)
    finally:
        await run_in_threadpool(repository.release_turn,draft_id,account,key)


@router.get('/goals/current')
async def current(request: Request, account=Depends(owner)):
    return jsonable_encoder(await run_in_threadpool(store(request).current,account),by_alias=True)


@router.get('/goals')
async def goals(request: Request, account=Depends(owner)):
    result=await run_in_threadpool(store(request).list,account)
    reviews=await run_in_threadpool(lambda:list(store(request).goals.find({'user_id':account,'record_type':'requirement_review'}).sort('updated_at',-1).limit(20)))
    return {'reviews':[{'review_id':str(r['_id']),'role':r['content']['role'],'version':r['version']} for r in reviews], 'goals':[g.model_dump(mode='json',by_alias=True) for g in result['goals']],
            'explorations':[draft_view(d) for d in result['explorations']]}


@router.post('/goals/confirm')
async def confirm(body: SaveGoal, request: Request, account=Depends(owner), key=Depends(request_key)):
    replay=await run_in_threadpool(store(request).replay_confirmation,account,key,body)
    if replay is not None: return jsonable_encoder(replay,by_alias=True)
    if body.review_id:
        from app.api.v1.reviews import store as review_store
        repository=review_store(request)
        draft=await run_in_threadpool(repository.claim_confirmation,body.review_id,account,body.expected_review_version,key)
        try:
            goal=repository.goal(draft,account,key,body)
            selected=await run_in_threadpool(store(request).confirm,account,key,body,goal)
            if draft.discovery:
                research_id=draft.discovery.research_id.split(':')[0]
                await run_in_threadpool(store(request).db.research_contexts.update_one,{'_id':research_id,'owner':account,'review_id':draft.id},{'$set':{'status':'confirmed'}})
            return jsonable_encoder(selected,by_alias=True)
        finally:
            await run_in_threadpool(repository.release_confirmation,body.review_id,account,key)
    if body.draft_id:
        draft=await run_in_threadpool(store(request).draft,body.draft_id,account)
        if draft.cv.mode=='saved':
            cv=await selected_cv(request,draft.cv.cv_id,account)
            if cv.version!=draft.cv.version or cv.extraction_version!=draft.cv.extraction_version or cv.profile_version!=draft.cv.profile_version:
                raise GoalError('Your CV changed after these suggestions. Start a fresh exploration before confirming.')
    return jsonable_encoder(await run_in_threadpool(store(request).confirm,account,key,body),by_alias=True)
