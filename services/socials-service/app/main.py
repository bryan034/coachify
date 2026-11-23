import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import httpx
from elo_shared.runtime import BodyLimit, ErrorView, Problem, Upstream, authenticated
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool

from app.bookings import Socials
from app.schemas import (
    Access, AccessUpdate, Booking, DecideChat, Expert, ExpertUpdate, FollowUp,
    Identifier, Report, ReportCreate, ReportReceipt, RequestChat, Slot, SlotCreate, Workspace,
)

logger = logging.getLogger(__name__)
PREFIX = '/api/v1/socials'
Account = Annotated[dict, Depends(authenticated)]


def get_socials(request: Request):
    store = request.app.state.socials
    if store is None:
        raise Problem('Chats & Socials storage is unavailable.', 503, 'storage')
    return store


Store = Annotated[Socials, Depends(get_socials)]


def operator(request: Request, account: Account):
    if account['id'] not in request.app.state.operators:
        raise Problem('A Chats & Socials operator account is required.', 403, 'operator_required')


async def recovery(store: Socials, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await run_in_threadpool(store.recover)
        except PyMongoError:
            logger.warning('Bookings could not be checked for recovery. The next check will retry.')
        try:
            await asyncio.wait_for(stop.wait(), timeout=3)
        except TimeoutError:
            pass


def create_app(*, store=None, upstream=None, operator_ids=None, recover=True):
    @asynccontextmanager
    async def lifespan(application):
        mongo = None
        task = None
        stop = asyncio.Event()
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as http:
            try:
                active_store = store
                uri = os.getenv('MONGODB_URI')
                if active_store is None and uri:
                    mongo = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000, timeoutMS=5000)
                    active_store = Socials(mongo[os.getenv('MONGODB_DATABASE', 'elo_socials')])
                application.state.socials = active_store
                application.state.upstream = upstream or Upstream(http)
                application.state.operators = frozenset(
                    operator_ids if operator_ids is not None else
                    (value.strip() for value in os.getenv('SOCIALS_OPERATOR_ACCOUNT_IDS', '').split(',') if value.strip())
                )
                if active_store is not None:
                    await run_in_threadpool(active_store.ensure_indexes)
                    if recover:
                        task = asyncio.create_task(recovery(active_store, stop))
                yield
            finally:
                stop.set()
                if task is not None:
                    await task
                if mongo is not None:
                    mongo.close()

    errors = {
        401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found', 409: 'Conflict',
        413: 'Content Too Large', 422: 'Unprocessable Content', 503: 'Service Unavailable',
    }
    app = FastAPI(title='elo Chats & Socials API', version='0.1.0', lifespan=lifespan,
                  responses={status: {'model': ErrorView, 'description': description}
                             for status, description in errors.items()})
    app.add_middleware(BodyLimit)

    @app.middleware('http')
    async def private_response(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @app.exception_handler(Problem)
    async def problem(request, error):
        return JSONResponse({'detail': error.detail, 'code': error.code}, error.status)

    @app.exception_handler(RequestValidationError)
    async def validation(request, error):
        return JSONResponse({'detail': 'Check the supplied values and field limits.', 'code': 'validation'}, 422)

    @app.exception_handler(PyMongoError)
    async def storage(request, error):
        return JSONResponse({'detail': 'Chats & Socials storage is unavailable. Retry this action.', 'code': 'storage'}, 503)

    @app.get('/health', include_in_schema=False)
    async def health():
        return {'status': 'ok'}

    @app.get(f'{PREFIX}/workspace', response_model=Workspace)
    async def workspace(request: Request, account: Account, socials: Store):
        goal = {}
        access = await run_in_threadpool(socials.access, account['id'])
        if access.access == 'enabled':
            try:
                current = await asyncio.wait_for(
                    request.app.state.upstream.read('career', '/api/v1/career/goals/current', account['token']),
                    timeout=3,
                )
                candidate = current.get('goal')
                if isinstance(candidate, dict):
                    goal = candidate
            except Problem as error:
                if error.status in (401, 403):
                    raise
            except TimeoutError:
                pass
        return await run_in_threadpool(socials.workspace, account['id'], goal)

    @app.get(f'{PREFIX}/experts/{{expert_id}}/slots', response_model=list[Slot])
    def list_slots(expert_id: Identifier, account: Account, socials: Store):
        return socials.slots(account['id'], expert_id)

    @app.post(f'{PREFIX}/bookings', response_model=Booking)
    def request_chat(command: RequestChat, account: Account, socials: Store):
        return socials.request_chat(account, command)

    @app.get(f'{PREFIX}/expert/requests', response_model=list[Booking])
    def expert_requests(account: Account, socials: Store):
        return socials.assigned(account['id'])

    @app.post(f'{PREFIX}/bookings/{{booking_id}}/decision', response_model=Booking)
    def decide_chat(booking_id: UUID, command: DecideChat, account: Account, socials: Store):
        return socials.decision(account['id'], str(booking_id), command)

    @app.post(f'{PREFIX}/bookings/{{booking_id}}/reports', response_model=ReportReceipt)
    def submit_report(booking_id: UUID, command: ReportCreate, account: Account, socials: Store):
        return socials.report(account['id'], str(booking_id), command)

    @app.get(f'{PREFIX}/agenda', response_model=list[Booking])
    def agenda(account: Account, socials: Store):
        return socials.agenda(account['id'])

    @app.patch(f'{PREFIX}/bookings/{{booking_id}}/follow-up', response_model=Booking)
    def update_follow_up(booking_id: UUID, command: FollowUp, account: Account, socials: Store):
        return socials.follow_up(account['id'], str(booking_id), command)

    @app.put(f'{PREFIX}/operator/members/{{member_id}}/access', response_model=Access, dependencies=[Depends(operator)])
    def set_access(member_id: Identifier, command: AccessUpdate, socials: Store):
        return socials.set_access(member_id, command)

    @app.put(f'{PREFIX}/operator/experts/{{expert_id}}', response_model=Expert, dependencies=[Depends(operator)])
    def put_expert(expert_id: Identifier, command: ExpertUpdate, socials: Store):
        return socials.put_expert(expert_id, command)

    @app.post(f'{PREFIX}/operator/experts/{{expert_id}}/slots', response_model=Slot, dependencies=[Depends(operator)])
    def publish_slot(expert_id: Identifier, command: SlotCreate, socials: Store):
        return socials.publish_slot(expert_id, command)

    @app.get(f'{PREFIX}/operator/reports', response_model=list[Report], dependencies=[Depends(operator)])
    def report_queue(socials: Store):
        return socials.report_queue()

    return app


app = create_app()
