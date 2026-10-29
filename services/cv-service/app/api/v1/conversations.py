"""Authenticated additive chat routes, registered before generic CV identifiers."""
from fastapi import APIRouter, Depends, Request, Query
from starlette.concurrency import run_in_threadpool
from app.api.v1.cv import authenticated
from app.conversation.service import view
from app.domain.service import iso
from app.schemas.cv import ApiError
from app.schemas.conversation import ConversationStart, ConversationSend, ConversationDecision, ConversationView, ConversationList

router = APIRouter(prefix='/api/v1/cv/conversations', tags=['C-series conversation'],
    responses={code: {'model': ApiError} for code in (401, 403, 404, 409, 413, 422, 503)})


@router.get('', response_model=ConversationList)
async def listing(request: Request, cv_id: str | None = Query(default=None, max_length=100), account=Depends(authenticated)):
    service = request.app.state.conversations
    if cv_id: await run_in_threadpool(service.cv.get, account['id'], cv_id)
    documents = await run_in_threadpool(service.repository.summaries, account['id'], cv_id)
    return {'conversations': [{'id': d['_id'], 'cv_id': d['cv_id'], 'updated_at': iso(d['updated_at']),
        'read_only': d.get('at_capacity', False), 'message_count': d.get('message_count', 0)} for d in documents]}


@router.post('', response_model=ConversationView)
async def start(mutation: ConversationStart, request: Request, account=Depends(authenticated)):
    service = request.app.state.conversations
    document = await run_in_threadpool(service.start, account['id'], mutation)
    return view(await service.refresh(request.app, account, document['_id']))


@router.get('/{conversation_id}', response_model=ConversationView)
async def read(conversation_id: str, request: Request, before: int | None = Query(default=None, ge=1),
        limit: int = Query(default=40, ge=1, le=100), account=Depends(authenticated)):
    return view(await request.app.state.conversations.refresh(request.app, account, conversation_id), before, limit)


@router.post('/{conversation_id}/messages', response_model=ConversationView)
async def send(conversation_id: str, mutation: ConversationSend, request: Request, account=Depends(authenticated)):
    return view(await request.app.state.conversations.send(request.app, account, conversation_id, mutation))


@router.post('/{conversation_id}/actions/{action_id}', response_model=ConversationView)
async def decide(conversation_id: str, action_id: str, mutation: ConversationDecision, request: Request,
        account=Depends(authenticated)):
    return view(await request.app.state.conversations.decide(request.app, account, conversation_id, action_id, mutation))
