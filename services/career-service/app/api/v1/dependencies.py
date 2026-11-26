"""Request dependencies shared by Career routes."""
from uuid import UUID
from fastapi import Depends, Header, HTTPException, Request
from app.core.auth import VerifiedAccount, current_account
from app.repositories.goals import GoalError
from app.schemas.analysis import object_id


async def owner(account: VerifiedAccount = Depends(current_account)):
    return account['id']


async def plan(account: VerifiedAccount = Depends(current_account)):
    return account['account_type']


def request_key(idempotency_key: str = Header(alias='Idempotency-Key')):
    try:
        if str(UUID(idempotency_key)) != idempotency_key: raise ValueError
    except ValueError: raise HTTPException(422,'Use a unique UUID Idempotency-Key for this action.') from None
    return idempotency_key


def identifier(value):
    try: return object_id(value)
    except ValueError: raise HTTPException(404,'This record was not found.') from None


def review_store(request):
    if request.app.state.review_store is None:
        raise GoalError('Career storage is not configured. Check the setup guide.',503)
    return request.app.state.review_store


def review_view(draft):
    return {'current':{'goal':{'_id':draft.id,'version':draft.version,'target_type':draft.target_type,
        **draft.content.model_dump(mode='json'),'generation':draft.generation,'discovery':draft.discovery,
        'requirements_need_review':draft.requirements_need_review,'metadata_origins':draft.metadata_origins}}}
